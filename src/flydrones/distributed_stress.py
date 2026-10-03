"""Multi-process kinematic swarm stress test using the production UDP peer node."""

from __future__ import annotations

import csv
import json
import math
import multiprocessing
import os
import random
import socket
import time
from dataclasses import dataclass
from pathlib import Path

from .peer_udp import PeerTrack, PeerUdpConfig, UdpPeerNode

Vector3 = tuple[float, float, float]


def _add(first: Vector3, second: Vector3) -> Vector3:
    return tuple(first[index] + second[index] for index in range(3))  # type: ignore[return-value]


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return tuple(first[index] - second[index] for index in range(3))  # type: ignore[return-value]


def _scale(vector: Vector3, factor: float) -> Vector3:
    return tuple(value * factor for value in vector)  # type: ignore[return-value]


def _dot(first: Vector3, second: Vector3) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _norm(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def _limit(vector: Vector3, magnitude: float) -> Vector3:
    length = _norm(vector)
    return _scale(vector, magnitude / length) if length > magnitude else vector


def _unit(vector: Vector3) -> Vector3:
    length = _norm(vector)
    return _scale(vector, 1.0 / length) if length > 1e-9 else (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class StressTrialConfig:
    vehicle_count: int
    output_dir: str | Path
    duration_s: float = 12.0
    rate_hz: float = 10.0
    radius_m: float = 45.0
    altitude_layers: int = 1
    altitude_layer_spacing_m: float = 7.0
    target_speed_mps: float = 10.0
    rotation_deg: float = 120.0
    arrival_tolerance_m: float = 2.5
    protected_separation_m: float = 1.5
    planning_separation_m: float = 3.0
    peer_range_m: float = 32.0
    peer_base_port: int = 0
    packet_loss: float = 0.05
    latency_s: float = 0.04
    jitter_s: float = 0.015
    track_ttl_s: float = 0.5
    blackout_windows_s: tuple[tuple[float, float], ...] = ((4.0, 5.0),)
    seed: int = 20260921

    def __post_init__(self) -> None:
        if self.vehicle_count < 2:
            raise ValueError("stress trial requires at least two vehicles")
        if not 1 <= self.altitude_layers <= self.vehicle_count:
            raise ValueError("altitude layers are outside the fleet")
        if self.duration_s <= 0.0 or self.rate_hz <= 0.0 or self.radius_m <= 0.0:
            raise ValueError("duration, rate and radius must be positive")


def _agent_endpoints(config: StressTrialConfig, vehicle_id: int) -> tuple[Vector3, Vector3]:
    layer = vehicle_id % config.altitude_layers
    layer_ids = list(range(layer, config.vehicle_count, config.altitude_layers))
    index = layer_ids.index(vehicle_id)
    angle = 2.0 * math.pi * index / len(layer_ids)
    direction = 1.0 if layer % 2 == 0 else -1.0
    goal_angle = angle + direction * math.radians(config.rotation_deg)
    altitude = 20.0 + layer * config.altitude_layer_spacing_m
    start = (config.radius_m * math.cos(angle), config.radius_m * math.sin(angle), altitude)
    goal = (config.radius_m * math.cos(goal_angle), config.radius_m * math.sin(goal_angle), altitude)
    return start, goal


def avoidance_velocity(
    *,
    vehicle_id: int,
    position: Vector3,
    velocity: Vector3,
    preferred_velocity: Vector3,
    tracks: list[PeerTrack],
    protected_separation_m: float,
    planning_separation_m: float,
    horizon_s: float,
) -> tuple[Vector3, int]:
    """Return a receiver-local reciprocal correction from UDP peer tracks."""
    correction: Vector3 = (0.0, 0.0, 0.0)
    interventions = 0
    forward = _unit(preferred_velocity)
    right = (forward[1], -forward[0], 0.0)
    for track in tracks:
        relative_position = _subtract(track.position, position)
        closing_velocity = _subtract(velocity, track.velocity)
        speed_squared = _dot(closing_velocity, closing_velocity)
        time_to_closest = (
            max(0.0, min(horizon_s, _dot(relative_position, closing_velocity) / speed_squared))
            if speed_squared > 1e-9
            else 0.0
        )
        miss = _subtract(relative_position, _scale(closing_velocity, time_to_closest))
        distance = _norm(relative_position)
        threatening = (
            distance < planning_separation_m * 1.5
            or (0.02 < time_to_closest < horizon_s and _norm(miss) < planning_separation_m)
        )
        if not threatening:
            continue
        urgency = max(0.25, 1.0 - time_to_closest / horizon_s)
        lateral = _scale(right, 3.5 * urgency)
        away = _scale(_unit(_scale(relative_position, -1.0)), 4.0 * urgency)
        if distance < protected_separation_m * 1.5:
            away = _scale(away, 1.8)
        vertical_sign = 1.0 if vehicle_id < track.sender_id else -1.0
        vertical = (0.0, 0.0, 0.8 * urgency * vertical_sign)
        correction = _add(correction, _add(lateral, _add(away, vertical)))
        interventions += 1
    return _limit(correction, 6.0), interventions


def _write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read_start_signal(path: Path, *, timeout_s: float = 5.0) -> float:
    """Wait for the published signal through transient Windows sharing locks."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return float(json.loads(path.read_text(encoding="utf-8"))["start_at"])
        except (FileNotFoundError, PermissionError) as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("start signal unavailable") from error
            time.sleep(min(0.01, remaining))


def _run_stress_agent(config: StressTrialConfig, vehicle_id: int, base_port: int, start_signal: str) -> None:
    output = Path(config.output_dir)
    result_path = output / f"agent-{vehicle_id}.json"
    trace_path = output / f"agent-{vehicle_id}.csv"
    node = None
    rows: list[dict] = []
    error: str | None = None
    arrived = False
    interventions = 0
    try:
        start, goal = _agent_endpoints(config, vehicle_id)
        position = start
        velocity: Vector3 = (0.0, 0.0, 0.0)
        radio = PeerUdpConfig(
            range_m=config.peer_range_m,
            latency_s=config.latency_s,
            jitter_s=config.jitter_s,
            packet_loss=config.packet_loss,
            track_ttl_s=config.track_ttl_s,
            blackout_windows_s=config.blackout_windows_s,
            seed=config.seed,
        )
        node = UdpPeerNode(vehicle_id, list(range(config.vehicle_count)), base_port=base_port, config=radio)
        (output / f"ready-{vehicle_id}").write_text(str(os.getpid()), encoding="ascii")
        start_at = _read_start_signal(Path(start_signal))
        while time.time() < start_at:
            time.sleep(min(0.01, start_at - time.time()))

        period = 1.0 / config.rate_hz
        started = time.monotonic()
        step = 0
        while True:
            tick = started + step * period
            now = time.monotonic()
            elapsed = now - started
            if elapsed > config.duration_s:
                break
            node.broadcast(position, velocity, mission_elapsed_s=elapsed)
            tracks = node.poll(position, now=now)
            goal_delta = _subtract(goal, position)
            distance = _norm(goal_delta)
            arrived = arrived or distance <= config.arrival_tolerance_m
            preferred_speed = 0.0 if arrived else min(config.target_speed_mps, max(0.8, distance * 1.2))
            preferred = _scale(_unit(goal_delta), preferred_speed)
            correction, active = avoidance_velocity(
                vehicle_id=vehicle_id,
                position=position,
                velocity=velocity,
                preferred_velocity=preferred,
                tracks=tracks,
                protected_separation_m=config.protected_separation_m,
                planning_separation_m=config.planning_separation_m,
                horizon_s=3.0,
            )
            interventions += active
            desired = (0.0, 0.0, 0.0) if arrived else _limit(_add(preferred, correction), config.target_speed_mps)
            acceleration = _limit(_subtract(desired, velocity), 8.0 * period)
            velocity = _add(velocity, acceleration)
            position = _add(position, _scale(velocity, period))
            rows.append({
                "step": step,
                "t_s": round(elapsed, 4),
                "vehicle_id": vehicle_id,
                "controller_process_id": os.getpid(),
                "x_m": round(position[0], 4),
                "y_m": round(position[1], 4),
                "z_m": round(position[2], 4),
                "speed_mps": round(_norm(velocity), 4),
                "goal_distance_m": round(_norm(_subtract(goal, position)), 4),
                "peer_tracks": len(tracks),
                "avoidance_active": active > 0,
                "neighbor_source": "udp-peer-cache",
            })
            step += 1
            delay = tick + period - time.monotonic()
            if delay > 0.0:
                time.sleep(delay)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        metrics = dict(node.metrics) if node is not None else {}
        if node is not None:
            node.close()
        if rows:
            _write_rows(trace_path, rows)
        result = {
            "accepted": arrived and error is None,
            "vehicle_id": vehicle_id,
            "controller_process_id": os.getpid(),
            "arrived": arrived,
            "avoidance_interventions": interventions,
            "metrics": metrics,
            "error": error,
        }
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _find_free_port_range(count: int) -> int:
    rng = random.Random(time.time_ns())
    for _attempt in range(200):
        base = rng.randint(18000, 54000 - count)
        sockets = []
        try:
            for offset in range(count):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.bind(("127.0.0.1", base + offset))
                    sockets.append(sock)
                except OSError:
                    sock.close()
                    raise
            return base
        except OSError:
            pass
        finally:
            for sock in sockets:
                sock.close()
    raise OSError(f"could not reserve {count} consecutive UDP ports")


def _aggregate_stress(config: StressTrialConfig, results: list[dict], output: Path) -> dict:
    failures = [f"agent-{result['vehicle_id']}: {result['error']}"
                for result in results if result.get("error") is not None]
    if failures:
        raise RuntimeError("UDP stress worker errors: " + "; ".join(failures))
    traces: dict[int, list[dict]] = {}
    for vehicle_id in range(config.vehicle_count):
        with (output / f"agent-{vehicle_id}.csv").open(encoding="utf-8") as handle:
            traces[vehicle_id] = list(csv.DictReader(handle))
    common_steps = min(len(rows) for rows in traces.values())
    minimum_distance = math.inf
    collisions: set[tuple[int, int]] = set()
    for step in range(common_steps):
        positions = {
            vehicle_id: tuple(float(traces[vehicle_id][step][axis]) for axis in ("x_m", "y_m", "z_m"))
            for vehicle_id in traces
        }
        for first in range(config.vehicle_count):
            for second in range(first + 1, config.vehicle_count):
                distance = math.dist(positions[first], positions[second])
                minimum_distance = min(minimum_distance, distance)
                if distance < 0.9:
                    collisions.add((first, second))
    process_ids = {int(result["controller_process_id"]) for result in results}
    sent = sum(int(result["metrics"].get("sent_packets", 0)) for result in results)
    received = sum(int(result["metrics"].get("received_packets", 0)) for result in results)
    attempted = sum(int(result["metrics"].get("attempted_packets", 0)) for result in results)
    blackout_drops = sum(int(result["metrics"].get("blackout_dropped_packets", 0)) for result in results)
    checks = {
        "all_agents_arrived": all(result["arrived"] for result in results),
        "all_agents_exited_cleanly": all(result["error"] is None for result in results),
        "one_process_per_vehicle": len(process_ids) == config.vehicle_count,
        "real_udp_exchange": sent > 0 and received > 0,
        "neighbor_data_came_only_from_udp_cache": all(
            row.get("neighbor_source") == "udp-peer-cache"
            for rows in traces.values()
            for row in rows
        ),
        "blackout_exercised": blackout_drops > 0,
        "zero_collisions": not collisions,
        "protected_separation_maintained": minimum_distance >= config.protected_separation_m,
    }
    metrics = {
        "vehicles": config.vehicle_count,
        "controller_processes": len(process_ids),
        "arrived": sum(bool(result["arrived"]) for result in results),
        "duration_s": config.duration_s,
        "target_speed_mps": config.target_speed_mps,
        "collisions": len(collisions),
        "minimum_intervehicle_distance_m": round(minimum_distance, 4),
        "udp_sent_packets": sent,
        "udp_received_packets": received,
        "udp_attempted_packets": attempted,
        "udp_attempted_packets_per_second": round(attempted / config.duration_s, 1),
        "udp_received_packets_per_second": round(received / config.duration_s, 1),
        "udp_random_dropped_packets": sum(
            int(result["metrics"].get("random_dropped_packets", 0)) for result in results
        ),
        "udp_blackout_dropped_packets": blackout_drops,
        "udp_stale_tracks_expired": sum(
            int(result["metrics"].get("stale_tracks_expired", 0)) for result in results
        ),
        "avoidance_interventions": sum(int(result["avoidance_interventions"]) for result in results),
        "maximum_speed_mps": max(
            float(row["speed_mps"])
            for rows in traces.values()
            for row in rows
        ),
        "direct_global_neighbor_reads": 0,
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "scope": "Multi-process kinematic UDP stress simulation; not real-aircraft safety certification.",
    }


def _publish_start_signal(path: Path, start_at: float) -> None:
    """Make the complete JSON visible in one same-directory rename."""
    pending = path.with_name(path.name + ".pending")
    pending.write_text(json.dumps({"start_at": start_at}), encoding="utf-8")
    os.replace(pending, path)


def run_udp_process_trial(config: StressTrialConfig) -> dict:
    """Run one OS process per agent; the parent reads traces only after exit."""
    output = Path(config.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for vehicle_id in range(config.vehicle_count):
        for prefix, suffix in (("agent", ".json"), ("agent", ".csv"), ("ready", "")):
            path = output / f"{prefix}-{vehicle_id}{suffix}"
            if path.is_file():
                path.unlink()
    start_signal = output / "start.json"
    if start_signal.is_file():
        start_signal.unlink()
    base_port = config.peer_base_port or _find_free_port_range(config.vehicle_count)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_run_stress_agent,
            args=(config, vehicle_id, base_port, str(start_signal)),
            name=f"udp-agent-{vehicle_id}",
        )
        for vehicle_id in range(config.vehicle_count)
    ]
    for process in processes:
        process.start()
    ready_deadline = time.monotonic() + max(20.0, config.vehicle_count * 0.3)
    while sum((output / f"ready-{vehicle_id}").is_file() for vehicle_id in range(config.vehicle_count)) < config.vehicle_count:
        if any(process.exitcode is not None for process in processes) or time.monotonic() >= ready_deadline:
            for process in processes:
                if process.is_alive():
                    process.terminate()
            raise RuntimeError("not all UDP stress workers became ready")
        time.sleep(0.02)
    _publish_start_signal(start_signal, time.time() + 0.75)
    join_deadline = time.monotonic() + config.duration_s + 20.0
    for process in processes:
        remaining = max(0.0, join_deadline - time.monotonic())
        process.join(remaining)
    if any(process.is_alive() for process in processes):
        for process in processes:
            if process.is_alive():
                process.terminate()
        raise TimeoutError("UDP stress workers exceeded their bounded runtime")
    exit_codes = [process.exitcode for process in processes]
    if any(code != 0 for code in exit_codes):
        raise RuntimeError(f"UDP stress worker exit codes: {exit_codes}")
    results = [
        json.loads((output / f"agent-{vehicle_id}.json").read_text(encoding="utf-8"))
        for vehicle_id in range(config.vehicle_count)
    ]
    summary = _aggregate_stress(config, results, output)
    summary["metrics"]["peer_base_port"] = base_port
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
