from __future__ import annotations

import csv

import numpy as np

from flydrones.distributed_px4 import DistributedAgentConfig, run_distributed_px4_agent
from flydrones.gazebo_depth import DepthObservation
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
        return []

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
        self.landing = False
        self.land_called = False

    def connect(self):
        self.connected = True

    def takeoff(self):
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
