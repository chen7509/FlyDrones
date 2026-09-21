"""One-process-per-vehicle PX4 worker and artifact aggregation helpers."""

from __future__ import annotations

import bisect
import csv
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .gazebo_depth import DepthCameraBank, px4_depth_camera_topics
from .hybrid_agent import HybridPlannerAgent
from .local_planner import LocalPlannerConfig, PlannerPeer
from .numpy_policy import NumpyMlpPolicy
from .peer_udp import PeerUdpConfig, UdpPeerNode
from .sitl_swarm import (
    evaluate_px4_swarm_trial,
    px4_swarm_obstacles,
    px4_swarm_rally_targets,
    px4_swarm_specs,
)


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


def _px4_execution_planner_config() -> LocalPlannerConfig:
    """Add clearance for PX4 response lag beyond the geometric hard limits."""
    return LocalPlannerConfig(
        static_margin_m=0.33,
        peer_minimum_m=1.25,
        horizon_s=1.6,
        integration_step_s=0.20,
    )


def build_distributed_agent_commands(
    *,
    python_executable: str,
    agent_script: str | Path,
    output_dir: str | Path,
    model_path: str | Path,
    vehicle_count: int = 5,
    peer_base_port: int = 16770,
    mission_timeout_s: float = 70.0,
) -> list[list[str]]:
    if vehicle_count != 5:
        raise ValueError("the distributed PX4 trial currently requires five workers")
    return [
        [
            str(python_executable),
            str(agent_script),
            "--vehicle-id", str(vehicle_id),
            "--output", str(output_dir),
            "--model", str(model_path),
            "--mission-timeout", str(mission_timeout_s),
            "--peer-base-port", str(peer_base_port),
        ]
        for vehicle_id in range(vehicle_count)
    ]


def align_distributed_traces(
    traces: dict[int, list[dict]],
    *,
    sample_hz: float = 10.0,
) -> list[dict]:
    """Resample independent wall-clock logs solely for offline scoring."""
    if not traces or any(not rows for rows in traces.values()):
        return []
    ordered = {vehicle_id: sorted(rows, key=lambda row: float(row["wall_time_s"])) for vehicle_id, rows in traces.items()}
    times = {
        vehicle_id: [float(row["wall_time_s"]) for row in rows]
        for vehicle_id, rows in ordered.items()
    }
    start = min(values[0] for values in times.values())
    end = max(values[-1] for values in times.values())
    period = 1.0 / max(1.0, float(sample_hz))
    sample_count = max(1, math.ceil((end - start) / period) + 1)
    aligned: list[dict] = []
    for step in range(sample_count):
        target_time = min(end, start + step * period)
        for vehicle_id in sorted(ordered):
            vehicle_times = times[vehicle_id]
            index = bisect.bisect_left(vehicle_times, target_time)
            candidates = [max(0, index - 1), min(len(vehicle_times) - 1, index)]
            chosen = min(candidates, key=lambda candidate: abs(vehicle_times[candidate] - target_time))
            row = dict(ordered[vehicle_id][chosen])
            row["step"] = step
            row["t_s"] = round(target_time - start, 4)
            aligned.append(row)
    return aligned


def _read_agent_trace(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    integer_fields = {
        "step",
        "vehicle_id",
        "system_id",
        "local_peer_tracks",
        "controller_process_id",
        "planner_generated_candidates",
        "planner_rejected_unknown",
        "planner_rejected_static",
        "planner_rejected_peer",
    }
    float_fields = {
        "monotonic_s", "wall_time_s", "mission_elapsed_s", "x_m", "y_m", "alt_m", "yaw_deg",
        "battery_pct", "depth_nearest_m", "policy_action_speed", "policy_action_yaw",
        "predicted_static_clearance_m", "predicted_peer_separation_m", "planner_time_ms",
    }
    for row in rows:
        for key in integer_fields:
            if row.get(key) not in {None, ""}:
                row[key] = int(float(row[key]))
        for key in float_fields:
            if row.get(key) not in {None, ""}:
                row[key] = float(row[key])
        if row.get("safety_override"):
            row["safety_override"] = row["safety_override"].lower() == "true"
    return rows


def aggregate_distributed_artifacts(
    output_dir: str | Path,
    *,
    vehicle_count: int = 5,
    lane_spacing_m: float = 2.0,
) -> tuple[list[dict], dict]:
    """Aggregate worker-owned files after all control processes have exited."""
    output = Path(output_dir)
    traces = {
        vehicle_id: _read_agent_trace(output / f"agent-{vehicle_id}.csv")
        for vehicle_id in range(vehicle_count)
    }
    results = [
        json.loads((output / f"agent-{vehicle_id}.json").read_text(encoding="utf-8"))
        for vehicle_id in range(vehicle_count)
    ]
    aligned = align_distributed_traces(traces)
    summary = evaluate_px4_swarm_trial(
        aligned,
        px4_swarm_rally_targets(lane_spacing_m=lane_spacing_m),
        px4_swarm_obstacles(lane_spacing_m=lane_spacing_m),
    )
    process_ids = sorted({int(result["metrics"]["controller_process_id"]) for result in results})
    all_rows = [row for rows in traces.values() for row in rows]
    worker_metrics = [result["metrics"] for result in results]
    summary["checks"].update({
        "all_worker_results_accepted": all(result["accepted"] for result in results),
        "five_distinct_controller_processes": len(process_ids) == vehicle_count,
        "one_process_owned_each_vehicle": all(
            row.get("controller_scope") == "one-process-one-vehicle" for row in all_rows
        ),
        "neighbor_data_came_only_from_udp_cache": all(
            row.get("neighbor_source") == "udp-peer-cache" for row in all_rows
        ),
        "zero_direct_global_neighbor_reads": sum(
            int(metrics.get("direct_global_neighbor_reads", 0)) for metrics in worker_metrics
        ) == 0,
        "real_udp_peer_transport_exercised": (
            sum(int(metrics.get("udp_sent_packets", 0)) for metrics in worker_metrics) > 0
            and sum(int(metrics.get("udp_received_packets", 0)) for metrics in worker_metrics) > 0
        ),
        "udp_blackout_exercised": sum(
            int(metrics.get("udp_blackout_dropped_packets", 0)) for metrics in worker_metrics
        ) > 0,
        "zero_central_control_commands": sum(
            int(metrics.get("central_control_commands", 0)) for metrics in worker_metrics
        ) == 0,
    })
    summary["metrics"].update({
        "controller_process_ids": process_ids,
        "direct_global_neighbor_reads": sum(
            int(metrics.get("direct_global_neighbor_reads", 0)) for metrics in worker_metrics
        ),
        "udp_sent_packets": sum(int(metrics.get("udp_sent_packets", 0)) for metrics in worker_metrics),
        "udp_received_packets": sum(int(metrics.get("udp_received_packets", 0)) for metrics in worker_metrics),
        "udp_random_dropped_packets": sum(
            int(metrics.get("udp_random_dropped_packets", 0)) for metrics in worker_metrics
        ),
        "udp_blackout_dropped_packets": sum(
            int(metrics.get("udp_blackout_dropped_packets", 0)) for metrics in worker_metrics
        ),
        "worker_policy_calls": sum(int(metrics.get("policy_calls", 0)) for metrics in worker_metrics),
        "worker_depth_decode_errors": sum(
            int(metrics.get("depth_decode_errors", 0)) for metrics in worker_metrics
        ),
        "planner_calls": sum(int(metrics.get("planner_calls", 0)) for metrics in worker_metrics),
        "planner_p95_ms": max(
            (float(metrics.get("planner_p95_ms", 0.0)) for metrics in worker_metrics),
            default=0.0,
        ),
        "central_control_commands": sum(
            int(metrics.get("central_control_commands", 0)) for metrics in worker_metrics
        ),
    })
    summary["accepted"] = all(summary["checks"].values())
    if aligned:
        fields = list(aligned[0])
        with (output / "flight.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(aligned)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = f"""# 五进程 PX4/UDP 去中心化试验

{'**通过。**' if summary['accepted'] else '**未通过。**'} 五个控制器运行在五个独立操作系统进程中。

- 控制进程：{process_ids}
- 抵达：{summary['metrics'].get('rallied')}/5；落地：{summary['metrics'].get('landed')}/5
- 树干接触：{summary['metrics'].get('forest_contacts')}
- 最小树干净空：{summary['metrics'].get('minimum_forest_clearance_m')} m
- 最小机间距：{summary['metrics'].get('minimum_intervehicle_distance_m')} m
- UDP 发送/接收：{summary['metrics']['udp_sent_packets']}/{summary['metrics']['udp_received_packets']}
- 随机丢包/断联丢包：{summary['metrics']['udp_random_dropped_packets']}/{summary['metrics']['udp_blackout_dropped_packets']}
- 直接读取全局邻机位置：{summary['metrics']['direct_global_neighbor_reads']}

父进程只启动工作者并在退出后读取日志；飞行动作由各工作者独立生成。
"""
    (output / "五进程去中心化报告.md").write_text(report, encoding="utf-8")
    return aligned, summary


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
    agent=None,
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
    if agent is None and policy is None:
        policy = NumpyMlpPolicy.load(config.policy_path)

    output_dir = Path(config.output_dir)
    period = 1.0 / max(5.0, float(config.rate_hz))
    trace: list[dict] = []
    connected = False
    mission_timed_out = False
    error: str | None = None
    depth_ready = False
    if agent is None:
        agent = HybridPlannerAgent(
            vehicle_id=config.vehicle_id,
            rally_target=target,
            policy=policy,
            config=_px4_execution_planner_config(),
            target_altitude_m=config.target_altitude_m,
            corridor_center_y=spec.home_xy[1],
        )
    mission_start = 0.0
    previous_position: tuple[float, float, float] | None = None
    previous_time: float | None = None
    step = 0
    planner_times_ms: list[float] = []
    planner_calls = 0
    fail_closed_land = False

    def sample(phase: str, position: tuple[float, float, float], telemetry, observation, peer_count: int) -> None:
        nonlocal step
        decision = getattr(agent, "last_decision", None)
        rejections = getattr(decision, "rejection_counts", {}) if decision is not None else {}
        previous_action = getattr(agent, "previous_action", (0.0, 0.0))
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
            "policy_action_speed": round(float(previous_action[0]), 5),
            "policy_action_yaw": round(float(previous_action[1]), 5),
            "safety_override": bool(decision and str(decision.mode).startswith("hold")),
            "planner_mode": decision.mode if decision is not None else None,
            "planner_candidate_id": decision.candidate_id if decision is not None else None,
            "planner_generated_candidates": decision.generated_candidates if decision is not None else 0,
            "planner_rejected_unknown": int(rejections.get("unknown", 0)),
            "planner_rejected_static": int(rejections.get("static", 0)),
            "planner_rejected_peer": int(rejections.get("peer", 0)),
            "predicted_static_clearance_m": (
                round(decision.minimum_static_clearance_m, 5)
                if decision is not None and decision.minimum_static_clearance_m is not None
                else None
            ),
            "predicted_peer_separation_m": (
                round(decision.minimum_peer_separation_m, 5)
                if decision is not None and decision.minimum_peer_separation_m is not None
                else None
            ),
            "planner_time_ms": round(decision.planning_time_ms, 5) if decision is not None else None,
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
        try:
            drone.takeoff()
        except TimeoutError as exc:
            if "did not arm" not in str(exc).lower():
                raise
            # Five SITL instances occasionally contend during simultaneous
            # startup. Re-prime OFFBOARD and retry this local vehicle once.
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
            planner_peers = tuple(
                PlannerPeer(
                    sender_id=track.sender_id,
                    position=track.position,
                    velocity=track.velocity,
                    age_s=max(0.0, timestamp - track.received_at),
                )
                for track in tracks
            )
            command = agent.command(
                now=timestamp,
                global_position=position,
                velocity=velocity,
                yaw_rad=math.radians(float(telemetry.yaw_deg or 0.0)),
                peers=planner_peers,
                depth_observation=observation,
            )
            if not all(
                math.isfinite(float(value))
                for value in (command.throttle, command.yaw, command.forward, command.lateral)
            ):
                raise ValueError("non-finite planner command")
            decision = getattr(agent, "last_decision", None)
            if decision is not None:
                planner_calls += 1
                planner_times_ms.append(float(decision.planning_time_ms))
            sample(agent.phase, position, telemetry, observation, len(tracks))
            if bool(getattr(agent, "should_land", False)):
                fail_closed_land = True
                break
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
            try:
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
            except Exception as exc:
                if error is None:
                    error = f"landing telemetry failed: {exc}"
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
        "zero_central_control_commands": True,
    }
    ordered_planner_times = sorted(planner_times_ms)
    planner_p95_ms = (
        ordered_planner_times[max(0, math.ceil(0.95 * len(ordered_planner_times)) - 1)]
        if ordered_planner_times
        else 0.0
    )
    metrics = {
        "vehicle_id": config.vehicle_id,
        "controller_process_id": os.getpid(),
        "samples": len(trace),
        "policy_calls": agent.policy_calls,
        "depth_safety_overrides": int(getattr(agent, "neural_triggers", 0)),
        "missing_depth_holds": int(getattr(agent, "sensor_holds", 0)),
        "local_corridor_overrides": int(getattr(agent, "corridor_overrides", 0)),
        "emergency_latch_overrides": int(getattr(agent, "emergency_latch_overrides", 0)),
        "planner_calls": planner_calls,
        "planner_p95_ms": round(planner_p95_ms, 5),
        "fail_closed_land": fail_closed_land,
        "central_control_commands": 0,
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
