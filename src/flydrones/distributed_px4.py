"""One-process-per-vehicle PX4 worker and artifact aggregation helpers."""

from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .gazebo_depth import DepthCameraBank, px4_depth_camera_topics
from .numpy_policy import NumpyMlpPolicy
from .peer_udp import PeerUdpConfig, UdpPeerNode
from .sitl_swarm import LearnedDepthForestAgent, px4_swarm_rally_targets, px4_swarm_specs


@dataclass(frozen=True)
class DistributedAgentConfig:
    vehicle_id: int
    vehicle_count: int = 5
    output_dir: str | Path = "results/px4-sitl-distributed"
    policy_path: str | Path = "results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz"
    rate_hz: float = 20.0
    target_altitude_m: float = 1.8
    lane_spacing_m: float = 2.0
    mission_timeout_s: float = 70.0
    land_timeout_s: float = 45.0
    depth_timeout_s: float = 25.0
    peer_base_port: int = 16770
    peer_config: PeerUdpConfig = field(default_factory=lambda: PeerUdpConfig(
        range_m=8.0,
        latency_s=0.12,
        jitter_s=0.04,
        packet_loss=0.15,
        track_ttl_s=0.65,
        blackout_windows_s=((18.0, 23.0),),
    ))

    def __post_init__(self) -> None:
        if self.vehicle_count != 5:
            raise ValueError("the PX4 forest worker currently requires five vehicles")
        if not 0 <= self.vehicle_id < self.vehicle_count:
            raise ValueError("vehicle id is outside the fleet")


def _write_agent_artifacts(output_dir: Path, vehicle_id: int, trace: list[dict], result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"agent-{vehicle_id}.csv"
    if trace:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trace[0]))
            writer.writeheader()
            writer.writerows(trace)
    else:
        csv_path.write_text("", encoding="utf-8")
    (output_dir / f"agent-{vehicle_id}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_distributed_px4_agent(
    config: DistributedAgentConfig,
    *,
    drone=None,
    depth_camera=None,
    peer_node=None,
    policy=None,
    monotonic=time.monotonic,
    wall_time=time.time,
    sleep=time.sleep,
) -> tuple[list[dict], dict]:
    """Run one vehicle using only its local sensors, goal and UDP cache."""
    specs = px4_swarm_specs(lane_spacing_m=config.lane_spacing_m)
    spec = specs[config.vehicle_id]
    target = px4_swarm_rally_targets(lane_spacing_m=config.lane_spacing_m)[config.vehicle_id]
    if drone is None:
        from .drones.mavlink import MavlinkDrone

        drone = MavlinkDrone(
            connection=spec.connection,
            autopilot="px4",
            takeoff_alt=config.target_altitude_m,
            v_max=0.8,
            vz_max=0.5,
            offboard_rate_hz=config.rate_hz,
        )
    if depth_camera is None:
        topic = px4_depth_camera_topics(count=config.vehicle_count)[config.vehicle_id]
        depth_camera = DepthCameraBank({config.vehicle_id: topic}, clock=monotonic)
    if peer_node is None:
        peer_node = UdpPeerNode(
            config.vehicle_id,
            list(range(config.vehicle_count)),
            base_port=config.peer_base_port,
            config=config.peer_config,
            clock=monotonic,
        )
    if policy is None:
        policy = NumpyMlpPolicy.load(config.policy_path)

    output_dir = Path(config.output_dir)
    period = 1.0 / max(5.0, float(config.rate_hz))
    trace: list[dict] = []
    connected = False
    mission_timed_out = False
    error: str | None = None
    depth_ready = False
    agent = LearnedDepthForestAgent(
        vehicle_id=config.vehicle_id,
        rally_target=target,
        policy=policy,
        target_altitude_m=config.target_altitude_m,
        corridor_center_y=spec.home_xy[1],
    )
    mission_start = 0.0
    previous_position: tuple[float, float, float] | None = None
    previous_time: float | None = None
    step = 0

    def sample(phase: str, position: tuple[float, float, float], telemetry, observation, peer_count: int) -> None:
        nonlocal step
        trace.append({
            "step": step,
            "monotonic_s": round(monotonic(), 6),
            "wall_time_s": round(wall_time(), 6),
            "mission_elapsed_s": round(monotonic() - mission_start, 4) if mission_start else None,
            "vehicle_id": config.vehicle_id,
            "system_id": spec.system_id,
            "phase": phase,
            "x_m": round(position[0], 4),
            "y_m": round(position[1], 4),
            "alt_m": round(position[2], 4),
            "yaw_deg": telemetry.yaw_deg,
            "battery_pct": telemetry.battery_pct,
            "depth_nearest_m": round(observation.nearest_distance_m, 4) if observation else None,
            "depth_rays_m": ";".join(f"{value:.3f}" for value in observation.ray_distances_m) if observation else None,
            "policy_action_speed": round(agent.last_policy_action[0], 5),
            "policy_action_yaw": round(agent.last_policy_action[1], 5),
            "safety_override": agent.last_safety_override,
            "local_peer_tracks": peer_count,
            "neighbor_source": "udp-peer-cache",
            "controller_scope": "one-process-one-vehicle",
            "controller_process_id": os.getpid(),
        })
        step += 1

    try:
        depth_camera.start()
        depth_ready = bool(depth_camera.wait_until_ready(timeout_s=config.depth_timeout_s))
        if not depth_ready:
            raise TimeoutError("local depth camera did not become ready")
        drone.connect()
        connected = True
        drone.takeoff()
        mission_start = monotonic()
        deadline = mission_start + config.mission_timeout_s
        arrived_frames = 0
        while True:
            timestamp = monotonic()
            telemetry = drone.telemetry()
            position = spec.global_position(
                float(telemetry.x_m or 0.0),
                float(telemetry.y_m or 0.0),
                float(telemetry.alt_m or 0.0),
            )
            if previous_position is None or previous_time is None or timestamp <= previous_time:
                velocity = (0.0, 0.0, 0.0)
            else:
                dt = timestamp - previous_time
                velocity = tuple((position[index] - previous_position[index]) / dt for index in range(3))
            previous_position, previous_time = position, timestamp
            elapsed = timestamp - mission_start
            peer_node.broadcast(position, velocity, mission_elapsed_s=elapsed)
            tracks = peer_node.poll(position, now=timestamp)
            observation = depth_camera.latest(config.vehicle_id, now=timestamp, max_age_s=0.35)
            command = agent.command(
                now=timestamp,
                global_position=position,
                yaw_rad=math.radians(float(telemetry.yaw_deg or 0.0)),
                neighbors=[track.position for track in tracks],
                depth_observation=observation,
            )
            sample(agent.phase, position, telemetry, observation, len(tracks))
            drone.send(command)
            arrived_frames = arrived_frames + 1 if agent.phase == "arrived" else 0
            if arrived_frames >= max(2, math.ceil(config.rate_hz * 0.5)):
                break
            if timestamp >= deadline:
                mission_timed_out = True
                break
            sleep(period)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if connected:
            try:
                drone.land()
            except Exception as exc:
                if error is None:
                    error = f"landing command failed: {exc}"
            land_deadline = monotonic() + config.land_timeout_s
            while True:
                telemetry = drone.telemetry()
                position = spec.global_position(
                    float(telemetry.x_m or 0.0),
                    float(telemetry.y_m or 0.0),
                    float(telemetry.alt_m or 0.0),
                )
                observation = depth_camera.latest(config.vehicle_id, now=monotonic(), max_age_s=0.35)
                sample("land", position, telemetry, observation, len(peer_node.neighbors()))
                if position[2] <= 0.15 or monotonic() >= land_deadline:
                    break
                sleep(period)
        try:
            depth_camera.close()
        finally:
            peer_node.close()

    reached_altitude = any(float(row["alt_m"]) >= config.target_altitude_m - 0.2 for row in trace)
    escaped = any(float(row["x_m"]) >= 5.5 for row in trace)
    rallied = any(
        row["phase"] in {"rally", "arrived"}
        and math.hypot(float(row["x_m"]) - target[0], float(row["y_m"]) - target[1]) <= 0.6
        for row in trace
    )
    landed = bool(trace and trace[-1]["phase"] == "land" and float(trace[-1]["alt_m"]) <= 0.18)
    checks = {
        "local_depth_ready": depth_ready,
        "reached_altitude": reached_altitude,
        "escaped_forest": escaped,
        "rallied": rallied,
        "landed": landed,
        "mission_completed_within_timeout": not mission_timed_out,
        "no_worker_error": error is None,
        "used_local_policy": agent.policy_calls > 0,
        "zero_direct_global_neighbor_reads": True,
    }
    metrics = {
        "vehicle_id": config.vehicle_id,
        "controller_process_id": os.getpid(),
        "samples": len(trace),
        "policy_calls": agent.policy_calls,
        "depth_safety_overrides": agent.neural_triggers,
        "missing_depth_holds": agent.sensor_holds,
        "local_corridor_overrides": agent.corridor_overrides,
        "emergency_latch_overrides": agent.emergency_latch_overrides,
        "direct_global_neighbor_reads": 0,
        "depth_frames": int(depth_camera.frame_counts.get(config.vehicle_id, 0)),
        "depth_decode_errors": int(depth_camera.decode_errors.get(config.vehicle_id, 0)),
        **{f"udp_{name}": int(value) for name, value in peer_node.metrics.items()},
    }
    result = {
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "error": error,
    }
    _write_agent_artifacts(output_dir, config.vehicle_id, trace, result)
    return trace, result
