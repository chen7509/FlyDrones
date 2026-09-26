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
    aggregate_takeoff_readiness_artifacts,
    align_distributed_traces,
    build_distributed_agent_commands,
    evaluate_gps_fault_artifacts,
    evaluate_gps_vio_fallback_artifacts,
    evaluate_local_state_health,
    run_distributed_px4_agent,
)
from flydrones.gazebo_depth import DepthObservation
from flydrones.motor.command import FlightCommand
from flydrones.peer_udp import PeerTrack
from flydrones.safety import Telemetry
from flydrones.takeoff_readiness import TakeoffEvidence, TakeoffFailureReason, TakeoffStage
from flydrones.vio_stream_monitor import VioStreamHealth


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
        return TakeoffEvidence(
            target_system=1,
            target_component=1,
            terminal_stage=TakeoffStage.MISSION_READY,
            accepted=True,
            baseline_altitude_m=0.0,
            maximum_altitude_gain_m=1.8,
        )

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
            armed=self.altitude > 0.15,
            landed=self.altitude <= 0.15,
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


@pytest.mark.parametrize(
    ("reason", "stage"),
    [
        (TakeoffFailureReason.ARM_COMMAND_REJECTED, TakeoffStage.ARM_SENT),
        (TakeoffFailureReason.TAKEOFF_COMMAND_TIMEOUT, TakeoffStage.TAKEOFF_SENT),
        (TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT, TakeoffStage.TAKEOFF_ACCEPTED),
    ],
)
def test_worker_never_enters_mission_after_takeoff_readiness_failure(tmp_path, reason, stage):
    class FailedTakeoffDrone(LocalKinematicDrone):
        def takeoff(self):
            self.takeoff_called = True
            return TakeoffEvidence(
                target_system=3,
                target_component=1,
                terminal_stage=stage,
                accepted=False,
                failure_reason=reason,
                baseline_altitude_m=0.0,
                maximum_altitude_gain_m=0.0,
            )

    clock = Clock()
    drone = FailedTakeoffDrone(clock)
    clock.drone = drone
    policy = ForwardPolicy()
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
        policy=policy,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert not result["accepted"]
    assert not result["checks"]["takeoff_mission_ready"]
    assert result["takeoff"]["failure_reason"] == reason.value
    assert policy.predict_calls == 0
    assert all(row["phase"] != "escaping" for row in trace)
    assert drone.land_called


def test_takeoff_only_mode_holds_locally_without_policy_or_planner_calls(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    policy = ForwardPolicy()

    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            takeoff_only_hold_s=2.0,
            land_timeout_s=5.0,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=policy,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert result["accepted"], result
    assert result["checks"]["takeoff_only_hold_completed"]
    assert result["metrics"]["policy_calls"] == 0
    assert result["metrics"]["planner_calls"] == 0
    assert policy.predict_calls == 0
    assert any(row["phase"] == "takeoff_hold" for row in trace)
    assert all(row["phase"] != "escaping" for row in trace)
    assert drone.last_command == FlightCommand.hover("takeoff-only hold")
    assert drone.land_called
    assert clock.now >= 2.0


def test_worker_rejects_low_altitude_without_px4_landed_confirmation(tmp_path):
    class UnconfirmedLandingDrone(LocalKinematicDrone):
        def telemetry(self):
            telemetry = super().telemetry()
            if self.land_called:
                telemetry.armed = True
                telemetry.landed = False
            return telemetry

    clock = Clock()
    drone = UnconfirmedLandingDrone(clock)
    clock.drone = drone

    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            takeoff_only_hold_s=0.2,
            land_timeout_s=0.4,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert not result["accepted"]
    assert not result["checks"]["landed"]
    assert "landing confirmation timed out" in result["error"]


def test_takeoff_readiness_aggregation_requires_all_five_ready_and_landed(tmp_path):
    for vehicle_id in range(5):
        result = {
            "accepted": True,
            "checks": {"takeoff_mission_ready": True, "landed": True},
            "takeoff": {
                "accepted": True,
                "terminal_stage": "mission-ready",
                "failure_reason": None,
            },
        }
        (tmp_path / f"agent-{vehicle_id}.json").write_text(json.dumps(result), encoding="utf-8")

    workers, summary = aggregate_takeoff_readiness_artifacts(tmp_path, vehicle_count=5)

    assert len(workers) == 5
    assert summary["accepted"]
    assert summary["metrics"]["mission_ready"] == 5
    assert summary["metrics"]["landed"] == 5

    failed = json.loads((tmp_path / "agent-3.json").read_text(encoding="utf-8"))
    failed["accepted"] = False
    failed["checks"]["takeoff_mission_ready"] = False
    failed["takeoff"].update({
        "accepted": False,
        "terminal_stage": "takeoff-accepted",
        "failure_reason": "actuator-response-timeout",
    })
    (tmp_path / "agent-3.json").write_text(json.dumps(failed), encoding="utf-8")

    _workers, rejected = aggregate_takeoff_readiness_artifacts(tmp_path, vehicle_count=5)

    assert not rejected["accepted"]
    assert rejected["metrics"]["mission_ready"] == 4


def test_coordinator_plumbs_takeoff_only_hold_to_every_worker(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
        takeoff_only_hold_s=2.0,
    )

    assert all(command[command.index("--takeoff-only-hold-s") + 1] == "2.0" for command in commands)


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


def test_worker_stops_autonomous_setpoints_on_vio_blackout_and_requests_land(tmp_path):
    class RecordingDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.sent_at = []

        def send(self, command):
            self.sent_at.append(self.clock.now)
            super().send(command)

    class BlackoutMonitor:
        def __init__(self):
            self.closed = False

        def health(self, *, now):
            if now < 0.4:
                return VioStreamHealth(True, None, 0.02, 0.001, now - 0.001)
            return VioStreamHealth(False, "stale-vio-frame", 0.27, 0.001, now - 0.27)

        def close(self):
            self.closed = True

    clock = Clock()
    drone = RecordingDrone(clock)
    clock.drone = drone
    monitor = BlackoutMonitor()
    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, land_timeout_s=5.0),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        vio_monitor=monitor,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.sent_at and max(drone.sent_at) < 0.4
    assert drone.land_called and monitor.closed
    assert result["metrics"]["fail_closed_land"]
    assert result["metrics"]["last_state_health_reason"] == "stale-vio-frame"
    assert 0.4 <= result["metrics"]["fail_closed_triggered_at_s"] < 0.5
    assert result["metrics"]["land_command_at_s"] >= result["metrics"]["fail_closed_triggered_at_s"]
    assert any(row["phase"] == "fail_closed" and not row["command_sent"] for row in trace)


def test_worker_waits_for_fresh_vio_after_blocking_takeoff_before_mission(tmp_path):
    class BlockingTakeoffDrone(LocalKinematicDrone):
        def takeoff(self):
            evidence = super().takeoff()
            self.clock.now += 1.0
            return evidence

    class BackloggedMonitor:
        def __init__(self):
            self.post_takeoff_checks = 0

        def health(self, *, now):
            if now >= 1.0:
                self.post_takeoff_checks += 1
                if self.post_takeoff_checks == 1:
                    return VioStreamHealth(False, "stale-vio-frame", 1.0, 0.001, now - 1.0)
            return VioStreamHealth(True, None, 0.02, 0.001, now - 0.001)

        def close(self):
            pass

    clock = Clock()
    drone = BlockingTakeoffDrone(clock)
    clock.drone = drone
    monitor = BackloggedMonitor()
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, mission_timeout_s=70.0),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        vio_monitor=monitor,
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert monitor.post_takeoff_checks >= 2
    assert result["metrics"]["policy_calls"] > 0
    assert not result["metrics"]["fail_closed_land"]


def test_blocking_gnss_fusion_change_cannot_send_a_command_after_vio_expires(tmp_path):
    class BlockingFusionDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.sent_at = []

        def enable_external_vision_fusion(self):
            pass

        def disable_gps_fusion(self):
            self.clock.now += 0.5

        def send(self, command):
            self.sent_at.append(self.clock.now)
            super().send(command)

    class ExpiringMonitor:
        def health(self, *, now):
            if now < 0.25:
                return VioStreamHealth(True, None, 0.02, 0.001, now - 0.001)
            return VioStreamHealth(False, "stale-vio-frame", 0.5, 0.001, now - 0.5)

        def close(self):
            pass

    clock = Clock()
    drone = BlockingFusionDrone(clock)
    clock.drone = drone
    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(
            vehicle_id=0,
            output_dir=tmp_path,
            gps_failure_at_s=0.0,
            gps_failure_mode="fusion-off",
            external_vision_fusion=True,
        ),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        vio_monitor=ExpiringMonitor(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.sent_at == []
    assert drone.land_called
    assert result["metrics"]["last_state_health_reason"] == "stale-vio-frame"
    assert any(row["phase"] == "fail_closed" and not row["command_sent"] for row in trace)


def test_blocking_gnss_change_cannot_send_a_plan_based_on_old_position(tmp_path):
    class BlockingFusionDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.sent_at = []

        def disable_gps_fusion(self):
            self.clock.now += 0.5

        def send(self, command):
            self.sent_at.append(self.clock.now)
            super().send(command)

    class FreshMonitor:
        def health(self, *, now):
            return VioStreamHealth(True, None, 0.01, 0.001, now - 0.001)

        def close(self):
            pass

    clock = Clock()
    drone = BlockingFusionDrone(clock)
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
        vio_monitor=FreshMonitor(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.sent_at == []
    assert drone.land_called
    assert result["metrics"]["last_state_health_reason"] == "stale-control-observation"


def test_depth_frame_expiring_during_planning_cannot_be_used_for_a_command(tmp_path):
    class NearExpiryDepth(LocalDepthCamera):
        def latest(self, vehicle_id, *, now, max_age_s):
            return DepthObservation(now - 0.34, 19.1, 0.0, 19.1, 19.1, 0.0, (19.1,) * 9)

    class SlowAgent:
        phase = "escaping"
        should_land = False
        policy_calls = 1
        last_decision = None
        previous_action = (0.0, 0.0)

        def command(self, **_kwargs):
            clock.now += 0.05
            return FlightCommand.hover("slow planning")

    class RecordingDrone(LocalKinematicDrone):
        def __init__(self, clock):
            super().__init__(clock)
            self.sent = 0

        def send(self, command):
            self.sent += 1
            super().send(command)

    clock = Clock()
    drone = RecordingDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone,
        depth_camera=NearExpiryDepth(),
        peer_node=LocalPeerNode(),
        agent=SlowAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert drone.sent == 0
    assert drone.land_called
    assert result["metrics"]["last_state_health_reason"] == "stale-depth-observation"


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
            fault_marker_path=tmp_path / "activation.json",
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
    marker = json.loads((tmp_path / "activation.json").read_text(encoding="utf-8"))
    assert marker["vehicle_id"] == 0
    assert marker["monotonic_s"] >= 0.0


def test_worker_enables_external_vision_before_takeoff(tmp_path):
    events = []

    class VisionFusionDrone(LocalKinematicDrone):
        def enable_external_vision_fusion(self):
            events.append("vision-fusion")

        def takeoff(self):
            events.append("takeoff")
            return super().takeoff()

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


def test_worker_calibrates_arbitrary_px4_local_origin_to_known_launch_pose(tmp_path):
    class WorldOriginDrone(LocalKinematicDrone):
        def enable_external_vision_fusion(self):
            pass

    clock = Clock()
    drone = WorldOriginDrone(clock)
    drone.local_north = -4.0
    clock.drone = drone
    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, external_vision_fusion=True),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        agent=FailClosedAgent(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )

    assert result["metrics"]["local_origin_calibrated"] is True
    assert trace[0]["x_m"] == 0.0
    assert trace[0]["y_m"] == -4.0


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
        fault_marker_path=tmp_path / "fault-start.json",
    )

    faulted = [command for command in commands if "--gps-failure-at" in command]
    assert len(faulted) == 1
    assert faulted[0][faulted[0].index("--vehicle-id") + 1] == "2"
    assert faulted[0][faulted[0].index("--gps-failure-mode") + 1] == "off"
    assert faulted[0][faulted[0].index("--fault-marker") + 1] == str(tmp_path / "fault-start.json")
    assert sum("--fault-marker" in command for command in commands) == 1


def test_renderer_trial_disables_gps_fusion_on_every_vehicle_but_marks_one_fault(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
        gps_failure_vehicle_id=0,
        gps_failure_all=True,
        gps_failure_at_s=5.0,
        gps_failure_mode="fusion-off",
        fault_marker_path=tmp_path / "fault-start.json",
    )

    assert all("--gps-failure-at" in command for command in commands)
    assert all(command[command.index("--gps-failure-mode") + 1] == "fusion-off" for command in commands)
    marked = [command for command in commands if "--fault-marker" in command]
    assert len(marked) == 1
    assert marked[0][marked[0].index("--vehicle-id") + 1] == "0"


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


def test_coordinator_routes_vio_health_to_each_matching_worker(tmp_path):
    commands = build_distributed_agent_commands(
        python_executable="python3",
        agent_script=Path("tools/px4_distributed_agent.py"),
        output_dir=tmp_path,
        model_path=Path("actor.npz"),
        vehicle_count=5,
        vio_health_base_port=16880,
    )

    assert [int(command[command.index("--vio-health-port") + 1]) for command in commands] == [
        16880, 16881, 16882, 16883, 16884,
    ]


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

    for vehicle_id in range(5):
        path = tmp_path / f"agent-{vehicle_id}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["metrics"]["udp_blackout_dropped_packets"] = 0
        path.write_text(json.dumps(result), encoding="utf-8")
    _trace, strict = aggregate_distributed_artifacts(tmp_path)
    _trace, renderer_trial = aggregate_distributed_artifacts(
        tmp_path,
        require_udp_blackout=False,
    )
    assert not strict["accepted"]
    assert renderer_trial["accepted"]
    assert not renderer_trial["acceptance_policy"]["udp_blackout_required"]
    for vehicle_id in range(5):
        path = tmp_path / f"agent-{vehicle_id}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["metrics"]["udp_blackout_dropped_packets"] = 10
        path.write_text(json.dumps(result), encoding="utf-8")

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

    (tmp_path / "px4-ekf-fusion-evidence.json").write_text(json.dumps({
        "accepted": True,
        "checks": {
            "external_vision_position_fused_before_gnss_loss": True,
            "external_vision_position_fused_after_gnss_loss": True,
            "external_vision_velocity_control_active_after_gnss_loss": True,
            "gnss_fusion_stopped": True,
            "no_inertial_dead_reckoning_after_switch": True,
            "visual_odometry_stream_continued": True,
            "local_position_valid_after_switch": True,
            "local_origin_reset_observed": True,
        },
        "metrics": {
            "switch_timestamp_s": 30.0,
            "external_vision_position_fused_samples_after_switch": 100,
            "external_vision_position_samples_after_switch": 100,
            "local_position_duration_after_switch_s": 10.0,
        },
    }), encoding="utf-8")

    _trace, summary = evaluate_gps_vio_fallback_artifacts(tmp_path, fault_vehicle_id=0)

    assert summary["accepted"], summary
    assert summary["checks"]["fault_vehicle_completed_after_gps_loss"]
    assert summary["checks"]["all_vehicles_acknowledged_external_vision_configuration"]
    assert summary["metrics"]["fleet_rallied"] == 5
    assert summary["checks"]["fault_vehicle_ekf_fusion_proven_from_ulog"]

    (tmp_path / "px4-ekf-fusion-evidence.json").unlink()
    _trace, missing_evidence = evaluate_gps_vio_fallback_artifacts(tmp_path, fault_vehicle_id=0)
    assert not missing_evidence["accepted"]
    assert not missing_evidence["checks"]["fault_vehicle_ekf_fusion_proven_from_ulog"]
