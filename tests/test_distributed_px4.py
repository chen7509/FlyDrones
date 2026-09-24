from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from flydrones.distributed_px4 import (
    DistributedAgentConfig,
    LocalFrameContinuity,
    _px4_execution_planner_config,
    aggregate_distributed_artifacts,
    align_distributed_traces,
    build_distributed_agent_commands,
    evaluate_local_state_health,
    evaluate_gps_fault_artifacts,
    evaluate_gps_vio_fallback_artifacts,
    run_distributed_px4_agent,
)
from flydrones.gazebo_depth import DepthObservation
from flydrones.motor.command import FlightCommand
from flydrones.peer_udp import PeerTrack
from flydrones.safety import Telemetry


class ForwardPolicy:
    def __init__(self):
        self.predict_calls = 0

    def predict(self, _observation):
        self.predict_calls += 1
        return np.asarray((1.0, 0.0), dtype=np.float32)


class LocalPeerNode:
    def __init__(self):
        self.broadcasts = []
        self.poll_positions = []
        self.closed = False
        self.metrics = {
            "attempted_packets": 0,
            "sent_packets": 0,
            "random_dropped_packets": 0,
            "blackout_dropped_packets": 0,
            "received_packets": 0,
            "malformed_packets": 0,
            "out_of_range_packets": 0,
            "stale_tracks_expired": 0,
            "out_of_order_packets": 0,
        }

    def broadcast(self, position, velocity, *, mission_elapsed_s):
        self.broadcasts.append((position, velocity, mission_elapsed_s))

    def poll(self, own_position, *, now=None):
        self.poll_positions.append((own_position, now))
        return [
            PeerTrack(
                sender_id=4,
                sequence=1,
                sent_at=float(now) - 0.1,
                received_at=float(now) - 0.05,
                position=(50.0, 50.0, 1.8),
                velocity=(0.4, -0.2, 0.0),
            )
        ]

    def neighbors(self):
        return []

    def close(self):
        self.closed = True


class LocalDepthCamera:
    def __init__(self):
        self.started = False
        self.closed = False
        self.frame_counts = {0: 100, 1: 100, 2: 100, 3: 100, 4: 100}
        self.decode_errors = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    def start(self):
        self.started = True

    def wait_until_ready(self, timeout_s):
        return True

    def latest(self, vehicle_id, *, now, max_age_s):
        return DepthObservation(now, 19.1, 0.0, 19.1, 19.1, 0.0, (19.1,) * 9)

    def close(self):
        self.closed = True


class LocalKinematicDrone:
    def __init__(self, clock):
        self.clock = clock
        self.local_north = 0.0
        self.local_east = 0.0
        self.altitude = 0.0
        self.yaw_deg = 90.0
        self.last_command = None
        self.connected = False
        self.takeoff_called = False
        self.landing = False
        self.land_called = False

    def connect(self):
        self.connected = True

    def takeoff(self):
        self.takeoff_called = True
        self.altitude = 1.8

    def send(self, command):
        self.last_command = command

    def telemetry(self):
        return Telemetry(
            t=self.clock.now,
            x_m=self.local_north,
            y_m=self.local_east,
            alt_m=self.altitude,
            yaw_deg=self.yaw_deg,
            battery_pct=100.0,
            position_updated_at=self.clock.now,
            attitude_updated_at=self.clock.now,
            estimator_updated_at=self.clock.now,
            position_valid=True,
            attitude_valid=True,
            estimator_healthy=True,
        )

    def land(self):
        self.land_called = True
        self.landing = True

    def advance(self, dt):
        if self.landing:
            self.altitude = max(0.0, self.altitude - 0.8 * dt)
            return
        if self.last_command is None:
            return
        self.local_east += self.last_command.forward * 0.8 * dt
        self.altitude = max(0.0, self.altitude + self.last_command.throttle * 0.5 * dt)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.drone = None

    def time(self):
        return self.now

    def wall_time(self):
        return 1_800_000_000.0 + self.now

    def sleep(self, seconds):
        if self.drone is not None:
            self.drone.advance(seconds)
        self.now += seconds


def test_px4_execution_planner_keeps_margin_for_flight_controller_lag():
    config = _px4_execution_planner_config()
    assert 0.57 <= config.vehicle_radius_m + config.static_margin_m <= 0.59
    assert config.peer_minimum_m >= 1.20
    assert config.integration_step_s <= 0.20
    assert 1.55 <= config.horizon_s <= 1.65


def test_local_frame_continuity_absorbs_an_authorized_estimator_origin_reset():
    continuity = LocalFrameContinuity(reset_jump_m=1.5)

    first, reset = continuity.update((0.70, 0.47, 1.80), now=5.00, allow_realign=False)
    second, reset_after_switch = continuity.update(
        (0.72, -3.48, 1.80),
        now=5.05,
        allow_realign=True,
    )
    third, reset_again = continuity.update(
        (0.82, -3.45, 1.80),
        now=5.10,
        allow_realign=False,
    )

    assert first == pytest.approx((0.70, 0.47, 1.80))
    assert reset is False
    assert reset_after_switch is True
    assert second == pytest.approx(first)
    assert reset_again is False
    assert third == pytest.approx((0.80, 0.50, 1.80))
    assert continuity.realignments == 1


def test_local_frame_continuity_never_masks_an_unexpected_jump():
    continuity = LocalFrameContinuity(reset_jump_m=1.5)
    continuity.update((0.0, 0.0, 1.8), now=1.0, allow_realign=False)

    position, reset = continuity.update((0.0, 4.0, 1.8), now=1.1, allow_realign=False)

    assert position == pytest.approx((0.0, 4.0, 1.8))
    assert reset is False
    assert continuity.realignments == 0


class FailClosedAgent:
    phase = "escaping"
    should_land = True
    policy_calls = 0
    last_decision = None

    def command(self, **_kwargs):
        return FlightCommand.hover("planner fail closed")


class NonFiniteAgent(FailClosedAgent):
    should_land = False

    def command(self, **_kwargs):
        return FlightCommand(forward=float("nan"), note="invalid planner output")


def test_local_state_health_requires_fresh_finite_pose_and_attitude():
    telemetry = Telemetry(
        t=10.0,
        x_m=1.0,
        y_m=-2.0,
        alt_m=1.8,
        yaw_deg=45.0,
        position_updated_at=9.9,
        attitude_updated_at=9.95,
        estimator_updated_at=9.98,
        position_valid=True,
        attitude_valid=True,
        estimator_healthy=True,
    )

    healthy = evaluate_local_state_health(telemetry, now=10.0, max_age_s=0.35)
    stale = evaluate_local_state_health(telemetry, now=10.4, max_age_s=0.35)
    telemetry.x_m = float("nan")
    non_finite = evaluate_local_state_health(telemetry, now=10.0, max_age_s=0.35)

    assert healthy.healthy
    assert healthy.position_age_s == pytest.approx(0.1)
    assert stale.reason == "stale-local-position"
    assert not non_finite.healthy
    assert non_finite.reason == "non-finite-local-position"


def test_local_state_health_requires_a_fresh_healthy_px4_estimator():
    telemetry = Telemetry(
        t=10.0,
        x_m=1.0,
        y_m=-2.0,
        alt_m=1.8,
        yaw_deg=45.0,
        position_updated_at=9.9,
        attitude_updated_at=9.95,
        position_valid=True,
        attitude_valid=True,
    )

    missing = evaluate_local_state_health(telemetry, now=10.0, max_age_s=0.35)
    telemetry.estimator_healthy = False
    telemetry.estimator_updated_at = 9.98
    unhealthy = evaluate_local_state_health(telemetry, now=10.0, max_age_s=0.35)
    telemetry.estimator_healthy = True
    telemetry.estimator_updated_at = 9.0
    stale = evaluate_local_state_health(telemetry, now=10.0, max_age_s=0.35)

    assert missing.reason == "missing-estimator-status"
    assert unhealthy.reason == "unhealthy-estimator"
    assert stale.reason == "stale-estimator-status"


def test_one_distributed_worker_owns_its_drone_depth_policy_and_udp_cache(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    depth = LocalDepthCamera()
    peer = LocalPeerNode()
    policy = ForwardPolicy()
    config = DistributedAgentConfig(vehicle_id=2, output_dir=tmp_path, mission_timeout_s=20.0, land_timeout_s=5.0)

    trace, result = run_distributed_px4_agent(
        config,
        drone=drone,
        depth_camera=depth,
        peer_node=peer,
        policy=policy,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert result["accepted"], result
    assert result["metrics"]["direct_global_neighbor_reads"] == 0
    assert result["metrics"]["controller_process_id"] > 0
    assert policy.predict_calls > 0
    assert peer.broadcasts and len(peer.broadcasts[0][0]) == 3
    assert all(row["vehicle_id"] == 2 for row in trace)
    assert all(row["controller_scope"] == "one-process-one-vehicle" for row in trace)
    assert drone.land_called and depth.closed and peer.closed
    assert (tmp_path / "agent-2.csv").is_file()
    assert (tmp_path / "agent-2.json").is_file()
    with (tmp_path / "agent-2.csv").open(encoding="utf-8") as handle:
        assert next(csv.DictReader(handle))["neighbor_source"] == "udp-peer-cache"


def test_worker_records_hybrid_planner_diagnostics(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=2,
            output_dir=tmp_path,
            mission_timeout_s=20.0,
            land_timeout_s=5.0,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )
    assert result["accepted"], result
    assert result["metrics"]["planner_calls"] > 0
    assert result["metrics"]["planner_p95_ms"] >= 0.0
    assert result["metrics"]["central_control_commands"] == 0
    assert all("planner_mode" in row for row in trace if row["phase"] != "land")
    assert all("planner_candidate_id" in row for row in trace if row["phase"] != "land")
    assert all("predicted_peer_separation_m" in row for row in trace if row["phase"] != "land")


def test_worker_retries_one_transient_px4_arm_timeout(tmp_path):
    class TransientArmTimeoutDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.takeoff_calls = 0

        def takeoff(self):
            self.takeoff_calls += 1
            if self.takeoff_calls == 1:
                raise TimeoutError("PX4 did not arm within 10 seconds")
            super().takeoff()

    clock = Clock()
    drone = TransientArmTimeoutDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=2,
            output_dir=tmp_path,
            mission_timeout_s=20.0,
            land_timeout_s=5.0,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )
    assert result["accepted"], result
    assert drone.takeoff_calls == 2


def test_worker_honors_local_fail_closed_landing_without_waiting_for_timeout(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, mission_timeout_s=70.0),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )
    assert result["metrics"]["fail_closed_land"]
    assert clock.now < 10.0
    assert drone.land_called


def test_worker_rejects_non_finite_planner_command_and_lands(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=NonFiniteAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )
    assert not result["accepted"]
    assert "non-finite" in result["error"]
    assert drone.land_called


def test_worker_checks_state_after_mavlink_receipt_timestamp(tmp_path):
    class ReceiptAfterLoopTimestampDrone(LocalKinematicDrone):
        def telemetry(self):
            self.clock.now += 0.001
            return super().telemetry()

    clock = Clock()
    drone = ReceiptAfterLoopTimestampDrone(clock)
    clock.drone = drone

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.takeoff_called
    assert result["error"] is None
    assert result["metrics"]["last_state_health_reason"] is None


def test_worker_injects_its_own_scheduled_gps_failure_once(tmp_path):
    class FaultInjectingDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.failure_injection_enabled = False
            self.injected_modes = []

        def enable_failure_injection(self):
            self.failure_injection_enabled = True

        def inject_gps_failure(self, mode):
            self.injected_modes.append(mode)

    clock = Clock()
    drone = FaultInjectingDrone(clock)
    clock.drone = drone

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            gps_failure_at_s=0.0,
            gps_failure_mode="off",
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.failure_injection_enabled
    assert drone.injected_modes == ["off"]
    assert result["metrics"]["gps_failure_injected"]
    assert result["metrics"]["gps_failure_mode"] == "off"


def test_worker_can_disable_gps_fusion_on_older_px4_sitl(tmp_path):
    class FusionControlDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.gps_fusion_disabled = False

        def disable_gps_fusion(self):
            self.gps_fusion_disabled = True

    clock = Clock()
    drone = FusionControlDrone(clock)
    clock.drone = drone

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            gps_failure_at_s=0.0,
            gps_failure_mode="fusion-off",
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.gps_fusion_disabled
    assert result["metrics"]["gps_failure_injected"]
    assert result["metrics"]["gps_failure_mechanism"] == "ekf2-gps-fusion-disabled"
    assert drone.last_command is None


def test_worker_enables_external_vision_before_takeoff(tmp_path):
    events = []

    class VisionFusionDrone(LocalKinematicDrone):
        def enable_external_vision_fusion(self):
            events.append("vision-fusion")

        def takeoff(self):
            events.append("takeoff")
            super().takeoff()

    clock = Clock()
    drone = VisionFusionDrone(clock)
    clock.drone = drone

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            external_vision_fusion=True,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert events[:2] == ["vision-fusion", "takeoff"]
    assert result["metrics"]["external_vision_fusion_enabled"] is True


def test_worker_lands_before_planning_when_local_position_is_stale(tmp_path):
    class StalePositionDrone(LocalKinematicDrone):
        def telemetry(self):
            telemetry = super().telemetry()
            telemetry.position_updated_at = self.clock.now - 1.0
            return telemetry

    clock = Clock()
    drone = StalePositionDrone(clock)
    clock.drone = drone
    peer = LocalPeerNode()
    policy = ForwardPolicy()

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=peer,
        policy=policy,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert not result["accepted"]
    assert result["metrics"]["fail_closed_land"]
    assert result["metrics"]["state_health_failures"] == 1
    assert result["metrics"]["last_state_health_reason"] == "stale-local-position"
    assert policy.predict_calls == 0
    assert peer.broadcasts == []
    assert drone.last_command is None
    assert not drone.takeoff_called
    assert drone.land_called


def test_worker_lands_before_planning_when_local_position_is_non_finite(tmp_path):
    class NonFinitePositionDrone(LocalKinematicDrone):
        def telemetry(self):
            telemetry = super().telemetry()
            telemetry.x_m = float("nan")
            return telemetry

    clock = Clock()
    drone = NonFinitePositionDrone(clock)
    clock.drone = drone
    peer = LocalPeerNode()
    policy = ForwardPolicy()

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=peer,
        policy=policy,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert not result["accepted"]
    assert result["metrics"]["fail_closed_land"]
    assert result["metrics"]["last_state_health_reason"] == "non-finite-local-position"
    assert policy.predict_calls == 0
    assert peer.broadcasts == []
    assert drone.last_command is None
    assert not drone.takeoff_called
    assert drone.land_called


def test_distributed_worker_lands_and_reports_failure_when_depth_never_becomes_ready(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    depth = LocalDepthCamera()
    depth.wait_until_ready = lambda timeout_s: False
    peer = LocalPeerNode()
    config = DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, depth_timeout_s=0.1)

    trace, result = run_distributed_px4_agent(
        config,
        drone=drone,
        depth_camera=depth,
        peer_node=peer,
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert trace == []
    assert not result["accepted"]
    assert "depth" in result["error"].lower()
    assert not drone.connected
    assert depth.closed and peer.closed


def test_distributed_worker_closes_local_resources_when_landing_telemetry_fails(tmp_path):
    class LostLinkDuringLanding(LocalKinematicDrone):
        def telemetry(self):
            if self.land_called:
                raise RuntimeError("local MAVLink lost during landing")
            return super().telemetry()

    clock = Clock()
    drone = LostLinkDuringLanding(clock)
    clock.drone = drone
    depth = LocalDepthCamera()
    peer = LocalPeerNode()
    config = DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, mission_timeout_s=0.1)

    _trace, result = run_distributed_px4_agent(
        config,
        drone=drone,
        depth_camera=depth,
        peer_node=peer,
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert not result["accepted"]
    assert "landing telemetry failed" in result["error"]
    assert depth.closed and peer.closed


def test_coordinator_commands_contain_only_static_config_and_one_vehicle_id(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
    )

    assert len(commands) == 5
    assert {command[command.index("--vehicle-id") + 1] for command in commands} == {"0", "1", "2", "3", "4"}
    assert all("--neighbor-position" not in command for command in commands)
    assert all("--telemetry" not in command for command in commands)


def test_coordinator_assigns_a_gps_fault_to_only_the_selected_vehicle(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
        gps_failure_vehicle_id=2,
        gps_failure_at_s=12.0,
        gps_failure_mode="off",
    )

    faulted = [command for command in commands if "--gps-failure-at" in command]
    assert len(faulted) == 1
    assert faulted[0][faulted[0].index("--vehicle-id") + 1] == "2"
    assert faulted[0][faulted[0].index("--gps-failure-mode") + 1] == "off"


def test_coordinator_enables_external_vision_independently_on_every_vehicle(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
        external_vision_fusion=True,
    )

    assert all("--external-vision-fusion" in command for command in commands)


def test_time_alignment_builds_complete_frames_from_independent_worker_clocks():
    traces = {
        0: [
            {"wall_time_s": 100.00, "vehicle_id": 0, "x_m": 0.0, "y_m": 0.0, "alt_m": 1.8},
            {"wall_time_s": 100.10, "vehicle_id": 0, "x_m": 0.1, "y_m": 0.0, "alt_m": 1.8},
        ],
        1: [
            {"wall_time_s": 100.02, "vehicle_id": 1, "x_m": 0.0, "y_m": 2.0, "alt_m": 1.8},
            {"wall_time_s": 100.12, "vehicle_id": 1, "x_m": 0.1, "y_m": 2.0, "alt_m": 1.8},
        ],
    }

    aligned = align_distributed_traces(traces, sample_hz=10.0)

    assert aligned
    by_step = {}
    for row in aligned:
        by_step.setdefault(row["step"], []).append(row)
    assert all({row["vehicle_id"] for row in rows} == {0, 1} for rows in by_step.values())


def test_aggregate_distributed_artifacts_accepts_five_distinct_controller_processes(tmp_path):
    homes = [-4.0, -2.0, 0.0, 2.0, 4.0]
    targets = [-3.2, -1.6, 0.0, 1.6, 3.2]
    for vehicle_id in range(5):
        rows = []
        for step, (phase, x_m, alt_m) in enumerate([
            ("escaping", 0.0, 1.8),
            ("escaping", 5.6, 1.8),
            ("arrived", 6.5, 1.8),
            ("land", 6.5, 0.1),
        ]):
            rows.append({
                "step": step,
                "monotonic_s": float(step),
                "wall_time_s": 100.0 + step,
                "mission_elapsed_s": float(step),
                "vehicle_id": vehicle_id,
                "system_id": vehicle_id + 1,
                "phase": phase,
                "x_m": x_m,
                "y_m": targets[vehicle_id] if phase in {"arrived", "land"} else homes[vehicle_id],
                "alt_m": alt_m,
                "yaw_deg": 90.0,
                "battery_pct": 100.0,
                "depth_nearest_m": 19.1,
                "depth_rays_m": ";".join(["19.100"] * 9),
                "policy_action_speed": 1.0,
                "policy_action_yaw": 0.0,
                "safety_override": False,
                "local_peer_tracks": 4,
                "neighbor_source": "udp-peer-cache",
                "controller_scope": "one-process-one-vehicle",
                "controller_process_id": 5000 + vehicle_id,
            })
        with (tmp_path / f"agent-{vehicle_id}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = {
            "accepted": True,
            "checks": {"rallied": True, "landed": True},
            "metrics": {
                "controller_process_id": 5000 + vehicle_id,
                "direct_global_neighbor_reads": 0,
                "udp_sent_packets": 100,
                "udp_received_packets": 100,
                "udp_blackout_dropped_packets": 10,
            },
        }
        (tmp_path / f"agent-{vehicle_id}.json").write_text(json.dumps(result), encoding="utf-8")

    trace, summary = aggregate_distributed_artifacts(tmp_path)

    assert trace
    assert summary["accepted"], summary
    assert summary["checks"]["five_distinct_controller_processes"]
    assert summary["checks"]["zero_direct_global_neighbor_reads"]
    assert summary["metrics"]["controller_process_ids"] == [5000, 5001, 5002, 5003, 5004]

    fault_path = tmp_path / "agent-0.json"
    fault_result = json.loads(fault_path.read_text(encoding="utf-8"))
    fault_result.update({
        "accepted": False,
        "checks": {"landed": True},
        "error": "local state unhealthy: unhealthy-estimator",
    })
    fault_result["metrics"].update({
        "gps_failure_injected": True,
        "gps_failure_mode": "fusion-off",
        "gps_failure_mechanism": "ekf2-gps-fusion-disabled",
        "fail_closed_land": True,
        "state_health_failures": 1,
        "last_state_health_reason": "unhealthy-estimator",
        "central_control_commands": 0,
    })
    fault_path.write_text(json.dumps(fault_result), encoding="utf-8")

    _trace, fault_summary = evaluate_gps_fault_artifacts(tmp_path, fault_vehicle_id=0)

    assert fault_summary["accepted"], fault_summary
    assert fault_summary["checks"]["fault_vehicle_landed_fail_closed"]
    assert fault_summary["checks"]["all_survivors_completed"]
    assert fault_summary["metrics"]["survivors_rallied"] == 4


def test_gps_vio_fallback_requires_faulted_vehicle_to_finish_without_fail_closed_landing(tmp_path):
    homes = [-4.0, -2.0, 0.0, 2.0, 4.0]
    targets = [-3.2, -1.6, 0.0, 1.6, 3.2]
    for vehicle_id in range(5):
        rows = []
        for step, (phase, x_m, alt_m) in enumerate([
            ("escaping", 0.0, 1.8),
            ("escaping", 5.6, 1.8),
            ("arrived", 6.5, 1.8),
            ("land", 6.5, 0.1),
        ]):
            rows.append({
                "step": step,
                "monotonic_s": float(step),
                "wall_time_s": 200.0 + step,
                "mission_elapsed_s": float(step),
                "vehicle_id": vehicle_id,
                "system_id": vehicle_id + 1,
                "phase": phase,
                "x_m": x_m,
                "y_m": targets[vehicle_id] if phase in {"arrived", "land"} else homes[vehicle_id],
                "alt_m": alt_m,
                "yaw_deg": 90.0,
                "battery_pct": 100.0,
                "depth_nearest_m": 19.1,
                "depth_rays_m": ";".join(["19.100"] * 9),
                "policy_action_speed": 1.0,
                "policy_action_yaw": 0.0,
                "safety_override": False,
                "local_peer_tracks": 4,
                "neighbor_source": "udp-peer-cache",
                "controller_scope": "one-process-one-vehicle",
                "controller_process_id": 6000 + vehicle_id,
            })
        with (tmp_path / f"agent-{vehicle_id}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        metrics = {
            "controller_process_id": 6000 + vehicle_id,
            "direct_global_neighbor_reads": 0,
            "central_control_commands": 0,
            "udp_sent_packets": 100,
            "udp_received_packets": 100,
            "udp_blackout_dropped_packets": 10,
            "state_health_failures": 0,
            "fail_closed_land": False,
            "external_vision_fusion_enabled": True,
        }
        if vehicle_id == 0:
            metrics.update({
                "gps_failure_injected": True,
                "gps_failure_mode": "fusion-off",
                "gps_failure_mechanism": "ekf2-gps-fusion-disabled",
                "gps_failure_injected_at_s": 5.0,
            })
        result = {
            "accepted": True,
            "checks": {"rallied": True, "landed": True},
            "metrics": metrics,
            "error": None,
        }
        (tmp_path / f"agent-{vehicle_id}.json").write_text(json.dumps(result), encoding="utf-8")

    _trace, summary = evaluate_gps_vio_fallback_artifacts(tmp_path, fault_vehicle_id=0)

    assert summary["accepted"], summary
    assert summary["checks"]["fault_vehicle_completed_after_gps_loss"]
    assert summary["checks"]["all_vehicles_used_external_vision_fusion"]
    assert summary["metrics"]["fleet_rallied"] == 5
