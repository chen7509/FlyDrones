from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np

from flydrones.gazebo_depth import DepthObservation
from flydrones.safety import Telemetry
from flydrones.sitl_swarm import (
    DistilledForestAgent,
    LearnedDepthForestAgent,
    PeerBroadcastConfig,
    PeerBroadcastNetwork,
    SwarmVehicleSpec,
    evaluate_px4_swarm_trial,
    px4_swarm_obstacles,
    px4_swarm_specs,
    render_gazebo_forest_world,
    run_px4_swarm_trial,
    write_px4_swarm_artifacts,
)


class FakeLearnedPolicy:
    def __init__(self, action=(1.0, 0.0)):
        self.action = action
        self.predict_calls = 0
        self.observations = []

    def predict(self, observation):
        self.predict_calls += 1
        self.observations.append(observation.copy())
        return np.asarray(self.action, dtype=np.float32)


def test_peer_broadcast_network_exposes_only_delayed_in_range_local_tracks():
    network = PeerBroadcastNetwork(
        vehicle_count=3,
        config=PeerBroadcastConfig(
            range_m=2.0,
            latency_s=0.10,
            jitter_s=0.0,
            packet_loss=0.0,
            track_ttl_s=0.40,
            seed=7,
        ),
        epoch_s=10.0,
    )
    positions = [(0.0, 0.0, 1.8), (1.0, 0.0, 1.8), (4.0, 0.0, 1.8)]

    network.exchange(10.0, positions)
    assert network.neighbors(0, 10.05) == []

    network.advance(10.11)
    assert network.neighbors(0, 10.11) == [(1.0, 0.0, 1.8)]
    assert network.neighbors(2, 10.11) == []

    network.advance(10.51)
    assert network.neighbors(0, 10.51) == []
    assert network.metrics["out_of_range_packets"] > 0


def test_peer_broadcast_network_models_full_radio_blackout():
    network = PeerBroadcastNetwork(
        vehicle_count=2,
        config=PeerBroadcastConfig(
            latency_s=0.0,
            jitter_s=0.0,
            packet_loss=0.0,
            blackout_windows_s=((1.0, 2.0),),
        ),
        epoch_s=100.0,
    )

    network.exchange(101.5, [(0.0, 0.0, 1.8), (1.0, 0.0, 1.8)])

    assert network.neighbors(0, 101.5) == []
    assert network.metrics["blackout_dropped_packets"] == 2


def test_learned_px4_agent_uses_nine_camera_rays_and_local_goal_only():
    policy = FakeLearnedPolicy((0.8, 0.25))
    agent = LearnedDepthForestAgent(0, (6.5, 0.0), policy, target_altitude_m=1.8)
    depth = DepthObservation(1.0, 8.0, 0.0, 8.0, 8.0, 0.3, (8.0,) * 9)

    command = agent.command(1.0, (0.0, 0.0, 1.8), math.pi / 2, [], depth)

    assert policy.predict_calls == 1
    assert policy.observations[0].shape == (16,)
    assert command.forward > 0.5
    assert math.isclose(command.yaw, -0.25, abs_tol=1e-6)
    assert agent.policy_calls == 1
    assert not agent.last_safety_override


def test_learned_px4_agent_depth_shield_overrides_dangerous_ppo_action():
    policy = FakeLearnedPolicy((1.0, -0.1))
    agent = LearnedDepthForestAgent(0, (6.5, 0.0), policy, target_altitude_m=1.8)
    rays = (4.0, 4.0, 4.0, 0.65, 0.60, 0.70, 8.0, 8.0, 8.0)
    depth = DepthObservation(1.0, 0.6, 0.0, 1.0, 8.0, 0.3, rays)

    command = agent.command(1.0, (1.0, 0.0, 1.8), math.pi / 2, [], depth)

    assert command.forward < 0.3
    assert command.yaw > 0.2
    assert agent.last_safety_override
    assert agent.neural_triggers == 1


def test_learned_px4_agent_creeps_into_confirmed_clear_space_after_emergency_turn():
    policy = FakeLearnedPolicy((1.0, 0.0))
    agent = LearnedDepthForestAgent(0, (6.5, 0.0), policy, target_altitude_m=1.8)
    danger = DepthObservation(1.0, 0.35, 0.0, 0.4, 3.0, 0.3, (0.35,) * 4 + (0.4,) + (3.0,) * 4)
    clear = DepthObservation(1.1, 19.1, 0.0, 19.1, 19.1, 0.3, (19.1,) * 9)

    first = agent.command(1.0, (1.8, 0.0, 1.8), math.pi / 2, [], danger)
    latched = agent.command(1.5, (1.8, 0.0, 1.8), math.pi / 2, [], clear)
    released = agent.command(2.3, (1.8, 0.0, 1.8), math.pi / 2, [], clear)

    assert first.forward == 0.0
    assert latched.forward == 0.0
    assert latched.yaw == first.yaw
    assert released.forward > 0.0
    assert agent.emergency_latch_overrides == 3


def test_learned_px4_agent_goal_homes_after_crossing_the_recovery_geofence():
    policy = FakeLearnedPolicy((-1.0, 1.0))
    agent = LearnedDepthForestAgent(0, (6.5, 0.0), policy, target_altitude_m=1.8)
    clear = DepthObservation(1.0, 19.1, 0.0, 19.1, 19.1, 0.3, (19.1,) * 9)

    command = agent.command(3.0, (-0.75, 0.0, 1.8), math.pi / 2, [], clear)

    assert command.forward >= 0.3
    assert abs(command.yaw) < 0.05
    assert agent.recovery_overrides == 1


def test_learned_px4_agent_turns_in_place_when_facing_away_from_its_local_corridor():
    policy = FakeLearnedPolicy((1.0, 1.0))
    agent = LearnedDepthForestAgent(
        2,
        (6.5, 0.0),
        policy,
        target_altitude_m=1.8,
        corridor_center_y=0.0,
    )
    clear = DepthObservation(1.0, 19.1, 0.0, 19.1, 19.1, 0.3, (19.1,) * 9)

    command = agent.command(3.0, (1.5, -1.2, 1.8), math.pi / 2, [], clear)

    assert command.forward == 0.0
    assert command.yaw < -0.2
    assert agent.corridor_overrides == 1


def test_learned_px4_agent_relaxes_peer_spacing_only_after_leaving_the_forest():
    clear = DepthObservation(1.0, 19.1, 0.0, 19.1, 19.1, 0.3, (19.1,) * 9)
    escaping = LearnedDepthForestAgent(0, (8.0, 0.0), FakeLearnedPolicy((1.0, 0.0)))
    rallying = LearnedDepthForestAgent(0, (8.0, 0.0), FakeLearnedPolicy((1.0, 0.0)), phase="rally")

    forest_command = escaping.command(1.0, (2.0, 0.0, 1.8), math.pi / 2, [(3.2, 0.0, 1.8)], clear)
    rally_command = rallying.command(1.0, (4.5, 0.0, 1.8), math.pi / 2, [(5.7, 0.0, 1.8)], clear)

    assert escaping.neural_triggers == 1
    assert rallying.neural_triggers == 0
    assert forest_command.yaw != rally_command.yaw


def test_learned_px4_agent_goal_homes_throughout_the_open_rally_phase():
    policy = FakeLearnedPolicy((-1.0, 1.0))
    agent = LearnedDepthForestAgent(0, (6.5, 0.0), policy, phase="rally")
    clear = DepthObservation(1.0, 19.1, 0.0, 19.1, 19.1, 0.3, (19.1,) * 9)

    command = agent.command(4.0, (12.0, 0.0, 1.8), math.pi / 2, [], clear)

    assert command.forward >= 0.3
    assert abs(command.yaw) >= 0.7
    assert agent.docking_overrides == 1


def safe_trace() -> tuple[list[dict], list[tuple[float, float]], list[tuple[float, float, float]]]:
    homes = [(0.0, -3.0), (0.0, -1.5), (0.0, 0.0), (0.0, 1.5), (0.0, 3.0)]
    rally = [(6.5, -1.8), (6.5, -0.9), (6.5, 0.0), (6.5, 0.9), (6.5, 1.8)]
    obstacles = [(2.5, y + 0.05, 0.22) for _, y in homes]
    rows = []
    for step, (phase, x, altitude) in enumerate([
        ("takeoff", 0.0, 1.8),
        ("escaping", 5.6, 1.8),
        ("rally", 6.5, 1.8),
        ("land", 6.5, 0.1),
    ]):
        for vehicle_id, (_, home_y) in enumerate(homes):
            y = rally[vehicle_id][1] if phase in {"rally", "land"} else home_y
            rows.append({
                "step": step,
                "vehicle_id": vehicle_id,
                "phase": phase,
                "x_m": x,
                "y_m": y,
                "alt_m": altitude,
            })
    return rows, rally, obstacles


def test_px4_swarm_specs_assign_five_independent_ports_and_home_positions():
    specs = px4_swarm_specs()

    assert [spec.connection for spec in specs] == [f"udpin:0.0.0.0:{port}" for port in range(14540, 14545)]
    assert [spec.system_id for spec in specs] == [1, 2, 3, 4, 5]
    assert len({spec.home_xy for spec in specs}) == 5


def test_evaluate_px4_swarm_trial_accepts_safe_five_vehicle_escape_rally_and_landing():
    rows, rally, obstacles = safe_trace()

    result = evaluate_px4_swarm_trial(rows, rally, obstacles)

    assert result["accepted"]
    assert result["metrics"]["vehicles"] == 5
    assert result["metrics"]["escaped"] == 5
    assert result["metrics"]["rallied"] == 5
    assert result["metrics"]["landed"] == 5
    assert result["metrics"]["minimum_intervehicle_distance_m"] >= 0.72
    assert result["metrics"]["minimum_forest_clearance_m"] > 0


def test_evaluate_px4_swarm_trial_rejects_a_tree_contact():
    rows, rally, obstacles = safe_trace()
    rows.append({
        "step": 10,
        "vehicle_id": 2,
        "phase": "escaping",
        "x_m": obstacles[2][0],
        "y_m": obstacles[2][1],
        "alt_m": 1.8,
    })

    result = evaluate_px4_swarm_trial(rows, rally, obstacles)

    assert not result["accepted"]
    assert not result["checks"]["zero_forest_contacts"]


def test_evaluate_px4_swarm_trial_rejects_less_than_ten_centimetres_tree_clearance():
    rows, rally, obstacles = safe_trace()
    obstacle_x, obstacle_y, obstacle_radius = obstacles[2]
    rows.append({
        "step": 10,
        "vehicle_id": 2,
        "phase": "escaping",
        "x_m": obstacle_x,
        "y_m": obstacle_y + obstacle_radius + 0.25 + 0.05,
        "alt_m": 1.8,
    })

    result = evaluate_px4_swarm_trial(rows, rally, obstacles)

    assert result["checks"]["zero_forest_contacts"]
    assert not result["checks"]["safe_forest_clearance"]
    assert not result["accepted"]


def test_each_distilled_agent_owns_and_triggers_its_neural_saccade_state():
    obstacle = (2.5, 0.05, 0.22)
    first = DistilledForestAgent(vehicle_id=0, rally_target=(6.5, 0.0), obstacles=[obstacle], ready_at=0.0)
    second = DistilledForestAgent(vehicle_id=1, rally_target=(6.5, 1.5), obstacles=[obstacle], ready_at=0.0)

    first_command = first.command(now=1.0, global_position=(1.5, 0.0, 1.8), yaw_rad=math.pi / 2, neighbors=[])
    second_command = second.command(now=1.0, global_position=(1.5, 1.5, 1.8), yaw_rad=math.pi / 2, neighbors=[])

    assert first.neural_triggers == 1
    assert abs(first_command.lateral) > 0.1
    assert second.neural_triggers == 0
    assert math.isclose(second_command.lateral, 0.0, abs_tol=0.05)
    assert first.neural_state is not second.neural_state


def test_agent_uses_only_local_neighbor_positions_for_reciprocal_avoidance():
    agent = DistilledForestAgent(vehicle_id=0, rally_target=(6.5, 0.0), obstacles=[], ready_at=0.0)

    clear = agent.command(now=1.0, global_position=(1.0, 0.0, 1.8), yaw_rad=math.pi / 2, neighbors=[])
    avoiding = agent.command(
        now=1.05,
        global_position=(1.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        neighbors=[(1.0, 0.55, 1.8)],
    )

    assert abs(clear.lateral) < 0.05
    assert avoiding.lateral > 0.1


def test_neural_saccade_selects_the_side_with_more_clearance_from_adjacent_trees():
    obstacles = [
        (2.5, 0.05, 0.22),
        (2.5, 1.55, 0.22),
        (2.5, 3.05, 0.22),
    ]
    middle = DistilledForestAgent(vehicle_id=3, rally_target=(6.5, 1.3), obstacles=obstacles, ready_at=0.0)
    bottom = DistilledForestAgent(vehicle_id=0, rally_target=(6.5, -2.6), obstacles=[
        (2.5, -2.95, 0.22),
        (2.5, -1.45, 0.22),
    ], ready_at=0.0)

    middle_command = middle.command(1.0, (1.5, 1.5, 1.8), math.pi / 2, [])
    bottom_command = bottom.command(1.0, (1.5, -3.0, 1.8), math.pi / 2, [])

    assert middle.neural_state.side == 1
    assert middle_command.lateral < -0.1
    assert bottom.neural_state.side == -1
    assert bottom_command.lateral > 0.1


def test_neural_saccade_can_be_driven_only_by_a_fresh_depth_camera_observation():
    agent = DistilledForestAgent(vehicle_id=0, rally_target=(6.5, 0.0), obstacles=[], ready_at=0.0)
    observation = DepthObservation(
        captured_at=1.0,
        nearest_distance_m=0.9,
        obstacle_bearing=-0.2,
        left_clearance_m=0.9,
        right_clearance_m=4.0,
        valid_fraction=0.2,
    )

    command = agent.command(
        now=1.0,
        global_position=(1.5, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        neighbors=[],
        depth_observation=observation,
    )

    assert agent.neural_triggers == 1
    assert agent.neural_state.side == -1
    assert command.lateral > 0.1
    assert agent.neural_state.bypass_until_time > agent.neural_state.active_until


def test_agent_without_geometry_or_depth_does_not_invent_an_obstacle():
    agent = DistilledForestAgent(vehicle_id=0, rally_target=(6.5, 0.0), obstacles=[], ready_at=0.0)

    command = agent.command(1.0, (1.5, 0.0, 1.8), math.pi / 2, [])

    assert agent.neural_triggers == 0
    assert abs(command.lateral) < 0.05


def test_vehicle_spec_converts_local_ned_telemetry_to_shared_mission_coordinates():
    spec = SwarmVehicleSpec(2, 3, "udpin:0.0.0.0:14542", (1.0, -2.0))

    assert spec.global_position(0.5, 0.25, 1.8) == (1.25, -1.5, 1.8)


def test_gazebo_forest_world_contains_one_solid_trunk_per_lane():
    _, _, obstacles = safe_trace()

    root = ET.fromstring(render_gazebo_forest_world(obstacles))

    trunks = root.findall(".//model[@name]")
    trunk_names = [model.attrib["name"] for model in trunks if model.attrib["name"].startswith("trunk_")]
    assert trunk_names == [f"trunk_{index}" for index in range(5)]
    assert len(root.findall(".//model[@name]/link/collision/geometry/cylinder")) == 5


def test_gazebo_world_can_preload_named_depth_vehicles():
    root = ET.fromstring(
        render_gazebo_forest_world(
            px4_swarm_obstacles(lane_spacing_m=2.0),
            vehicle_poses_y=(-4.0, -2.0, 0.0, 2.0, 4.0),
        )
    )
    world = root.find("world")
    assert world is not None
    includes = world.findall("include")
    assert [item.findtext("name") for item in includes] == [
        f"x500_depth_fly_{vehicle_id}" for vehicle_id in range(5)
    ]
    assert {item.findtext("uri") for item in includes} == {"model://x500_depth_fly"}
    assert [item.findtext("pose") for item in includes] == [
        "0 -4.0000 0 0 0 0",
        "0 -2.0000 0 0 0 0",
        "0 0.0000 0 0 0 0",
        "0 2.0000 0 0 0 0",
        "0 4.0000 0 0 0 0",
    ]


def test_write_px4_swarm_artifacts_records_csv_json_and_report(tmp_path):
    rows, rally, obstacles = safe_trace()
    summary = evaluate_px4_swarm_trial(rows, rally, obstacles)

    output = write_px4_swarm_artifacts(tmp_path, rows, summary, neural_triggers=[1, 1, 1, 1, 1])

    assert (output / "flight.csv").is_file()
    assert (output / "summary.json").is_file()
    report = (output / "报告.md").read_text(encoding="utf-8")
    assert "五机 PX4/Gazebo" in report
    assert "神经闪避触发: 5" in report


class FakeVehicleConnection:
    def __init__(self):
        self.mode = None
        self.armed = False

    def set_mode(self, mode):
        self.mode = mode

    def arducopter_arm(self):
        self.armed = True

    def recv_match(self, **_kwargs):
        return None

    def motors_armed(self):
        return self.armed


class KinematicDrone:
    def __init__(self, fleet, connection, **_kwargs):
        self.fleet = fleet
        self.connection = connection
        self.vehicle_id = int(connection.rsplit(":", 1)[1]) - 14540
        self.m = FakeVehicleConnection()
        self.local = [0.0, 0.0, 0.0]
        self.last_command = None
        self.flying = False
        self.landing = False
        fleet.drones.append(self)

    def connect(self):
        return None

    def send(self, command):
        self.last_command = command

    def land(self):
        self.landing = True

    def telemetry(self):
        return Telemetry(
            t=self.fleet.now,
            alt_m=self.local[2],
            x_m=self.local[0],
            y_m=self.local[1],
            yaw_deg=90.0,
            battery_pct=100.0,
            flying=self.flying,
        )

    def advance(self, dt):
        if self.landing:
            self.local[2] = max(0.0, self.local[2] - 0.6 * dt)
            return
        if self.last_command is None:
            return
        self.local[0] -= self.last_command.lateral * 0.8 * dt
        self.local[1] += self.last_command.forward * 0.8 * dt
        self.local[2] = max(0.0, self.local[2] + self.last_command.throttle * 0.5 * dt)


class KinematicFleet:
    def __init__(self):
        self.now = 0.0
        self.drones = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        for drone in self.drones:
            drone.advance(seconds)
        self.now += seconds

    def factory(self, **kwargs):
        return KinematicDrone(self, **kwargs)


class FakeDepthCameraBank:
    def __init__(self, fleet):
        self.fleet = fleet
        self.frame_counts = {vehicle_id: 100 for vehicle_id in range(5)}
        self.decode_errors = {vehicle_id: 0 for vehicle_id in range(5)}

    def start(self):
        return None

    def wait_until_ready(self, timeout_s):
        return True

    def latest(self, vehicle_id, *, now, max_age_s):
        return DepthObservation(now, 0.9, -0.2, 0.9, 4.0, 0.2)


class ClearNineRayDepthCameraBank(FakeDepthCameraBank):
    def latest(self, vehicle_id, *, now, max_age_s):
        return DepthObservation(now, 19.1, 0.0, 19.1, 19.1, 0.0, (19.1,) * 9)


def test_run_px4_swarm_trial_drives_five_independent_agents_through_full_mission():
    fleet = KinematicFleet()

    trace, summary, triggers = run_px4_swarm_trial(
        drone_factory=fleet.factory,
        time_fn=fleet.clock,
        sleep_fn=fleet.sleep,
        takeoff_timeout_s=8.0,
        mission_timeout_s=25.0,
        land_timeout_s=8.0,
    )

    assert trace
    assert summary["accepted"], summary
    assert triggers == [1, 1, 1, 1, 1]


def test_run_px4_swarm_trial_can_require_five_independent_depth_cameras():
    fleet = KinematicFleet()

    _trace, summary, triggers = run_px4_swarm_trial(
        drone_factory=fleet.factory,
        depth_camera_bank=FakeDepthCameraBank(fleet),
        require_depth_cameras=True,
        time_fn=fleet.clock,
        sleep_fn=fleet.sleep,
        takeoff_timeout_s=8.0,
        mission_timeout_s=25.0,
        land_timeout_s=8.0,
    )

    assert summary["checks"]["zero_forest_contacts"]
    assert summary["checks"]["all_depth_cameras_streamed"]
    assert summary["checks"]["controller_used_no_obstacle_truth"]
    assert summary["metrics"]["controller_truth_obstacles"] == 0
    assert all(trigger >= 1 for trigger in triggers)


def test_run_px4_swarm_trial_can_execute_exported_ppo_from_nine_depth_rays(tmp_path):
    actor = tmp_path / "actor.npz"
    np.savez(
        actor,
        w1=np.zeros((64, 16), dtype=np.float32),
        b1=np.zeros(64, dtype=np.float32),
        w2=np.zeros((64, 64), dtype=np.float32),
        b2=np.zeros(64, dtype=np.float32),
        wa=np.zeros((2, 64), dtype=np.float32),
        ba=np.array([1.0, 0.0], dtype=np.float32),
    )
    fleet = KinematicFleet()

    _trace, summary, _triggers = run_px4_swarm_trial(
        drone_factory=fleet.factory,
        depth_camera_bank=ClearNineRayDepthCameraBank(fleet),
        require_depth_cameras=True,
        learned_policy_path=actor,
        allow_mission_timeout=True,
        time_fn=fleet.clock,
        sleep_fn=fleet.sleep,
        takeoff_timeout_s=8.0,
        mission_timeout_s=25.0,
        land_timeout_s=8.0,
    )

    assert summary["checks"]["all_vehicles_used_learned_policy"]
    assert summary["checks"]["all_policy_inputs_used_nine_depth_rays"]
    assert summary["metrics"]["learned_policy_calls"] > 0
    assert summary["metrics"]["controller_truth_obstacles"] == 0


def test_run_px4_swarm_trial_uses_only_lossy_peer_caches_for_neighbor_avoidance(tmp_path):
    actor = tmp_path / "actor.npz"
    np.savez(
        actor,
        w1=np.zeros((64, 16), dtype=np.float32),
        b1=np.zeros(64, dtype=np.float32),
        w2=np.zeros((64, 64), dtype=np.float32),
        b2=np.zeros(64, dtype=np.float32),
        wa=np.zeros((2, 64), dtype=np.float32),
        ba=np.array([1.0, 0.0], dtype=np.float32),
    )
    fleet = KinematicFleet()
    radio = PeerBroadcastConfig(
        range_m=5.0,
        latency_s=0.10,
        jitter_s=0.02,
        packet_loss=0.25,
        track_ttl_s=0.50,
        blackout_windows_s=((4.0, 6.0),),
        seed=11,
    )

    trace, summary, _triggers = run_px4_swarm_trial(
        drone_factory=fleet.factory,
        depth_camera_bank=ClearNineRayDepthCameraBank(fleet),
        require_depth_cameras=True,
        learned_policy_path=actor,
        peer_broadcast_config=radio,
        allow_mission_timeout=True,
        time_fn=fleet.clock,
        sleep_fn=fleet.sleep,
        takeoff_timeout_s=8.0,
        mission_timeout_s=25.0,
        land_timeout_s=8.0,
    )

    assert summary["checks"]["neighbor_avoidance_used_no_direct_global_positions"]
    assert summary["checks"]["peer_radio_exercised_loss_and_blackout"]
    assert summary["checks"]["maintained_safe_separation_during_peer_blackout"]
    assert summary["metrics"]["direct_global_neighbor_reads"] == 0
    assert summary["metrics"]["peer_packets_delivered"] > 0
    assert summary["metrics"]["peer_packets_randomly_dropped"] > 0
    assert summary["metrics"]["peer_packets_dropped_in_blackout"] > 0
    assert summary["metrics"]["minimum_blackout_intervehicle_distance_m"] >= 0.72
    assert all("local_peer_tracks" in row for row in trace if row["phase"] not in {"takeoff", "land"})
