"""Independent-process mission stress trial and offline acceptance evaluator."""

from __future__ import annotations

import csv
import json
import math
import multiprocessing as mp
import os
import socket
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flydrones.mission_agent import AgentState, Detection, MissionAgent
from flydrones.mission_contract import MissionContract, WorkUnit
from flydrones.peer_udp import PeerUdpConfig, UdpPeerNode
from flydrones.task_udp import MissionTaskStation, TaskUdpConfig, TaskUdpNode, task_overlay_peers


@dataclass(frozen=True)
class MissionStressConfig:
    vehicle_count: int = 100
    output_dir: str | Path = "results/mission-swarm-100"
    duration_s: float = 60.0
    rate_hz: float = 10.0
    search_columns: int = 10
    search_rows: int = 10
    failed_vehicle_ids: tuple[int, ...] = (8, 17, 29, 41, 52, 63, 74, 85, 91, 97)
    failure_at_s: float = 8.0
    partition_window_s: tuple[float, float] = (12.0, 17.0)
    low_battery_vehicle_id: int = 4
    depth_freeze_vehicle_id: int = 11
    sensor_fault_at_s: float = 6.0
    task_udp_base_port: int = 0
    motion_udp_base_port: int = 0
    seed: int = 20260921

    def __post_init__(self) -> None:
        if self.vehicle_count < 2 or self.vehicle_count > 100:
            raise ValueError("vehicle_count must be between two and 100")
        if self.duration_s <= 0 or self.rate_hz <= 0:
            raise ValueError("duration and rate must be positive")
        if self.search_columns <= 0 or self.search_rows <= 0:
            raise ValueError("search grid dimensions must be positive")
        if any(not 0 <= item < self.vehicle_count for item in self.failed_vehicle_ids):
            raise ValueError("failed vehicle ID is outside the fleet")


def _contract_for(config: MissionStressConfig) -> MissionContract:
    width = config.search_columns * 20
    height = config.search_rows * 20
    return MissionContract.from_dict(
        {
            "schema_version": 1,
            "mission_id": f"forest-autonomy-{config.vehicle_count}-{config.seed}",
            "mission_type": "search_confirm_rally",
            "area_polygon_m": [[0, 0], [width, 0], [width, height], [0, height]],
            "search_cell_size_m": 20,
            "target_classes": ["person"],
            "confirmation_quorum": 2,
            "rally_position_m": [width + 30, height / 2, 20],
            "deadline_s": config.duration_s,
            "safety": {
                "maximum_speed_mps": 8,
                "minimum_separation_m": 3,
                "geofence_margin_m": 35,
                "minimum_battery_return_pct": 30,
            },
        }
    )


def _free_base_port(count: int, start: int) -> int:
    step = count + 2
    for base in range(start, 64000 - step, step):
        sockets: list[socket.socket] = []
        try:
            for offset in range(count + 1):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("127.0.0.1", base + offset))
                sockets.append(sock)
            return base
        except OSError:
            pass
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("no contiguous UDP port range is available")


def overlay_survivors_converge(member_count: int, removed_ids: tuple[int, ...]) -> dict[str, object]:
    members = tuple(range(member_count))
    survivors = set(members) - set(removed_ids)
    graph = {
        member: set(task_overlay_peers(member, members)) & survivors
        for member in survivors
    }
    reached: set[int] = set()
    frontier = [min(survivors)] if survivors else []
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        frontier.extend(graph[current] - reached)
        frontier.extend(node for node, peers in graph.items() if current in peers and node not in reached)
    connected = reached == survivors
    return {
        "connected": connected,
        "survivor_count": len(survivors),
        "all_records_delivered": connected,
    }


def motion_peer_ids(_vehicle_id: int, vehicle_count: int) -> tuple[int, ...]:
    """Safety telemetry is local-by-range but addressable to every physical peer."""
    return tuple(range(vehicle_count))


def _read_start_time(
    path: Path,
    deadline: float,
    *,
    sleep=time.sleep,
) -> float:
    while time.monotonic() < deadline:
        try:
            if path.exists():
                return float(json.loads(path.read_text(encoding="utf-8"))["start_at"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
        sleep(0.005)
    raise RuntimeError("mission start marker was not readable before its deadline")


def _worker_main(
    vehicle_id: int,
    config_data: dict[str, Any],
    mission_id: str,
    mission_digest: str,
    task_port: int,
    motion_port: int,
) -> None:
    config = MissionStressConfig(**config_data)
    output = Path(config.output_dir)
    members = tuple(range(config.vehicle_count))
    start_at = [math.inf]

    def partition_filter(source: int, target: int) -> bool:
        elapsed = time.monotonic() - start_at[0]
        begin, end = config.partition_window_s
        if not begin <= elapsed <= end:
            return True
        midpoint = config.vehicle_count // 2
        return (source < midpoint) == (target < midpoint)

    task_node = TaskUdpNode(
        vehicle_id,
        members,
        mission_id,
        mission_digest,
        config=TaskUdpConfig(base_port=task_port),
        partition_filter=partition_filter,
    )
    motion_members = motion_peer_ids(vehicle_id, config.vehicle_count)
    motion_node = UdpPeerNode(
        vehicle_id,
        motion_members,
        base_port=motion_port,
        config=PeerUdpConfig(
            range_m=55,
            latency_s=0,
            jitter_s=0,
            packet_loss=0,
            track_ttl_s=0.7,
            seed=config.seed,
        ),
    )
    (output / f"ready-{vehicle_id}").write_text(str(os.getpid()), encoding="utf-8")
    contract: MissionContract | None = None
    accepted = False
    handshake_deadline = time.monotonic() + 12
    while time.monotonic() < handshake_deadline and contract is None:
        for message in task_node.poll():
            if message.kind != "mission_offer":
                continue
            candidate = MissionContract.from_dict(message.payload["contract"])  # type: ignore[arg-type]
            if candidate.digest != mission_digest:
                continue
            contract = candidate
            if not accepted:
                task_node.send_to_station(
                    "mission_accept",
                    {"mission_digest": mission_digest},
                    now=time.monotonic(),
                )
                accepted = True
        time.sleep(0.005)
    if contract is None:
        task_node.close()
        motion_node.close()
        return

    start_at[0] = _read_start_time(output / "start.json", handshake_deadline + 5)
    while time.monotonic() < start_at[0]:
        time.sleep(0.001)

    agent = MissionAgent.for_contract(vehicle_id, config.vehicle_count, contract)
    search_units = [unit for unit in contract.expand_work_units() if unit.kind == "search_cell"]
    home = search_units[vehicle_id % len(search_units)].center_m
    position = [home[0], home[1], home[2] + 25.0 + 4.0 * (vehicle_id % 3)]
    velocity = [0.0, 0.0, 0.0]
    trace: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    previous_snapshot: dict[str, tuple[object, ...]] = {}
    forwarded: set[str] = set()
    detected_targets: set[int] = set()
    target_indices = {0, len(search_units) // 2, len(search_units) - 1}
    contract_task_ids = {unit.task_id for unit in contract.expand_work_units()}
    status = "completed"
    step = 0
    grace_step = 0
    convergence_grace_s = 15.0
    grace_queue: deque[tuple[str, dict[str, object]]] = deque()
    grace_forwarded: set[str] = set()
    dt = 1.0 / config.rate_hz
    next_tick = start_at[0]
    while True:
        now_wall = time.monotonic()
        elapsed = now_wall - start_at[0]
        if elapsed >= config.duration_s + convergence_grace_s:
            break
        incoming = task_node.poll()
        if elapsed >= config.duration_s:
            before = {
                item.task_id: (item.status, item.winner_id, item.allocation_round, item.confirmers)
                for item in agent.ledger.snapshot()
            }
            agent.ingest_messages(incoming, now=elapsed)
            for message in incoming:
                if message.kind == "award" and "work_unit" in message.payload:
                    signature = json.dumps(message.payload, sort_keys=True)
                    if signature not in grace_forwarded:
                        grace_forwarded.add(signature)
                        grace_queue.append(("award", message.payload))
            for assignment in agent.ledger.snapshot():
                value = (
                    assignment.status,
                    assignment.winner_id,
                    assignment.allocation_round,
                    assignment.confirmers,
                )
                if assignment.status != "completed" or before.get(assignment.task_id) == value:
                    continue
                payload = {"assignment": asdict(assignment)}
                signature = json.dumps(payload, sort_keys=True)
                if signature not in grace_forwarded:
                    grace_forwarded.add(signature)
                    grace_queue.append(("award", payload))
            snapshot = agent.ledger.snapshot()
            dynamic = [item for item in snapshot if item.task_id not in contract_task_ids]
            if grace_queue:
                kind, payload = grace_queue.popleft()
                task_node.send(kind, payload, now=elapsed)  # type: ignore[arg-type]
            elif dynamic and grace_step % 10 == 0:
                assignment = dynamic[(grace_step // 10 + vehicle_id) % len(dynamic)]
                task_node.send(
                    "award",
                    {
                        "task_id": assignment.task_id,
                        "work_unit": _unit_payload(agent.work_unit(assignment.task_id)),
                    },
                    now=elapsed,
                )
            elif snapshot:
                assignment = snapshot[(grace_step + vehicle_id) % len(snapshot)]
                task_node.send("award", {"assignment": asdict(assignment)}, now=elapsed)
            trace.append(
                {
                    "step": step,
                    "t_s": round(elapsed, 3),
                    "x_m": round(position[0], 4),
                    "y_m": round(position[1], 4),
                    "z_m": round(position[2], 4),
                    "phase": "converge",
                    "safety_phase": "nominal",
                    "central_control_commands": 0,
                }
            )
            grace_step += 1
            step += 1
            next_tick += dt
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            continue
        for message in incoming:
            if message.kind not in {"bid", "award", "evidence"}:
                continue
            signature = f"{message.kind}:{json.dumps(message.payload, sort_keys=True)}"
            if signature not in forwarded:
                forwarded.add(signature)
                task_node.send(message.kind, message.payload, now=elapsed)  # type: ignore[arg-type]
        tracks = motion_node.poll(tuple(position), now=now_wall)
        battery = 90.0
        if vehicle_id == config.low_battery_vehicle_id and elapsed >= config.sensor_fault_at_s:
            battery = contract.safety.minimum_battery_return_pct - 1.0
        depth_age = 0.0
        if vehicle_id == config.depth_freeze_vehicle_id and elapsed >= config.sensor_fault_at_s:
            depth_age = elapsed - config.sensor_fault_at_s + 0.51
        detections: list[Detection] = []
        for index in target_indices - detected_targets:
            if math.dist(position, search_units[index].center_m) <= 3.0:
                evidence = hashlib_sha(f"target-{index}")
                detections.append(Detection("person", search_units[index].center_m, 0.95, evidence))
                detected_targets.add(index)
        decision = agent.step(
            elapsed,
            AgentState(tuple(position), tuple(velocity), battery, depth_age, True),
            tracks,
            incoming,
            detections,
        )
        for kind, payload in decision.outbound_messages:
            task_node.send(kind, payload, now=elapsed)  # type: ignore[arg-type]
        if step % max(1, int(config.rate_hz / 2)) == vehicle_id % max(1, int(config.rate_hz / 2)):
            snapshot = agent.ledger.snapshot()
            if snapshot:
                assignment = snapshot[(step // max(1, int(config.rate_hz / 2)) + vehicle_id) % len(snapshot)]
                task_node.send("award", {"assignment": asdict(assignment)}, now=elapsed)

        desired = list(decision.intent.velocity_mps)
        maximum_delta = 5.0 * dt
        for axis in range(3):
            delta = max(-maximum_delta, min(maximum_delta, desired[axis] - velocity[axis]))
            velocity[axis] += delta
            position[axis] += velocity[axis] * dt
        if step % 2 == 0:
            motion_node.broadcast(tuple(position), tuple(velocity), mission_elapsed_s=elapsed)
        snapshot_map: dict[str, tuple[object, ...]] = {}
        for assignment in agent.ledger.snapshot():
            value = (assignment.status, assignment.winner_id, assignment.allocation_round)
            snapshot_map[assignment.task_id] = value
            if previous_snapshot.get(assignment.task_id) != value:
                changes.append({"t_s": round(elapsed, 3), **asdict(assignment)})
        previous_snapshot = snapshot_map
        trace.append(
            {
                "step": step,
                "t_s": round(elapsed, 3),
                "x_m": round(position[0], 4),
                "y_m": round(position[1], 4),
                "z_m": round(position[2], 4),
                "phase": decision.phase,
                "safety_phase": decision.safety_phase,
                "central_control_commands": decision.central_control_commands,
            }
        )
        if vehicle_id in config.failed_vehicle_ids and elapsed >= config.failure_at_s:
            status = "injected_failure"
            break
        step += 1
        next_tick += dt
        delay = next_tick - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    artifact = {
        "vehicle_id": vehicle_id,
        "pid": os.getpid(),
        "status": status,
        "contract_digest": contract.digest,
        "final_assignments": [asdict(item) for item in agent.ledger.snapshot()],
        "assignment_changes": changes,
        "trace": trace,
        "task_udp_metrics": task_node.metrics,
        "motion_udp_metrics": motion_node.metrics,
    }
    temporary = output / f"agent-{vehicle_id}.json.tmp"
    temporary.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output / f"agent-{vehicle_id}.json")
    with (output / f"agent-{vehicle_id}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trace[0]) if trace else ["step", "t_s"])
        writer.writeheader()
        writer.writerows(trace)
    task_node.close()
    motion_node.close()


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _unit_payload(work_unit: WorkUnit) -> dict[str, object]:
    return {
        "task_id": work_unit.task_id,
        "kind": work_unit.kind,
        "center_m": list(work_unit.center_m),
        "payload": [list(item) for item in work_unit.payload],
    }


def _write_plots(output: Path, artifacts: list[dict[str, Any]]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axis = plt.subplots(figsize=(8, 6))
        for artifact in artifacts:
            trace = artifact["trace"]
            if trace:
                axis.plot([row["x_m"] for row in trace], [row["y_m"] for row in trace], linewidth=0.8)
        axis.set(title="Autonomous swarm trajectories", xlabel="x (m)", ylabel="y (m)")
        axis.set_aspect("equal", adjustable="box")
        figure.tight_layout()
        figure.savefig(output / "trajectories.png", dpi=140)
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(9, 4))
        for artifact in artifacts:
            changes = artifact["assignment_changes"]
            axis.scatter(
                [item["t_s"] for item in changes],
                [artifact["vehicle_id"]] * len(changes),
                s=3,
            )
        axis.set(title="Distributed task state changes", xlabel="time (s)", ylabel="vehicle")
        figure.tight_layout()
        figure.savefig(output / "task-timeline.png", dpi=140)
        plt.close(figure)
    except (ImportError, OSError, ValueError):
        pass


def _evaluate(
    config: MissionStressConfig,
    contract: MissionContract,
    artifacts: list[dict[str, Any]],
    station_closed_at: float,
    start_at: float,
) -> dict[str, Any]:
    survivors = [item for item in artifacts if item["status"] != "injected_failure"]
    failed = [item for item in artifacts if item["status"] == "injected_failure"]
    pids = sorted({int(item["pid"]) for item in artifacts})
    search_ids = {unit.task_id for unit in contract.expand_work_units() if unit.kind == "search_cell"}
    completed_search: set[str] = set()
    per_agent_completed: list[int] = []
    confirmer_sets: dict[str, set[int]] = {}
    completed_confirmation_ids: set[str] = set()
    final_views: list[dict[str, tuple[object, object, object]]] = []
    for artifact in survivors:
        view: dict[str, tuple[object, object, object]] = {}
        agent_completed = 0
        for assignment in artifact["final_assignments"]:
            view[assignment["task_id"]] = (
                assignment["status"],
                assignment["winner_id"],
                assignment["allocation_round"],
            )
            if assignment["task_id"] in search_ids and assignment["status"] == "completed":
                completed_search.add(assignment["task_id"])
                agent_completed += 1
            if assignment["task_id"].startswith("confirm-"):
                confirmer_sets.setdefault(assignment["task_id"], set()).update(assignment["confirmers"])
                if assignment["status"] == "completed":
                    completed_confirmation_ids.add(assignment["task_id"])
        final_views.append(view)
        per_agent_completed.append(agent_completed)
    common_ids = set.intersection(*(set(view) for view in final_views)) if final_views else set()
    agreements = [
        all(view[task_id] == final_views[0][task_id] for view in final_views[1:])
        for task_id in common_ids
    ]
    agreement_ratio = sum(agreements) / len(agreements) if agreements else 0.0

    failed_ids = set(config.failed_vehicle_ids)
    reassigned = not failed_ids
    if failed_ids:
        reassigned = any(
            assignment["allocation_round"] > 0
            and assignment["winner_id"] is not None
            and assignment["winner_id"] not in failed_ids
            for artifact in survivors
            for assignment in artifact["final_assignments"]
        )

    collisions = 0
    minimum_separation = math.inf
    by_step: dict[int, list[tuple[int, tuple[float, float, float]]]] = {}
    for artifact in artifacts:
        for row in artifact["trace"]:
            by_step.setdefault(int(row["step"]), []).append(
                (artifact["vehicle_id"], (row["x_m"], row["y_m"], row["z_m"]))
            )
    for entries in by_step.values():
        for index, (_first_id, first) in enumerate(entries):
            for _second_id, second in entries[index + 1 :]:
                distance = math.dist(first, second)
                minimum_separation = min(minimum_separation, distance)
                if distance < 0.9:
                    collisions += 1

    all_safety = [row["safety_phase"] for artifact in survivors for row in artifact["trace"]]
    central_commands = sum(
        int(row["central_control_commands"])
        for artifact in artifacts
        for row in artifact["trace"]
    )
    overlay = overlay_survivors_converge(config.vehicle_count, config.failed_vehicle_ids)
    completion_ratio = len(completed_search) / max(1, len(search_ids))
    minimum_agent_completion = min(per_agent_completed, default=0) / max(1, len(search_ids))
    confirmed_targets = sum(
        task_id in completed_confirmation_ids and len(values) >= 2
        for task_id, values in confirmer_sets.items()
    )
    required_completion = 0.95 if config.vehicle_count >= 50 else 0.5
    checks = {
        "task_station_absent_during_control": station_closed_at < start_at,
        "one_process_per_vehicle": len(pids) == config.vehicle_count,
        "failed_tasks_reassigned": reassigned,
        "ledgers_converged_after_partition": bool(overlay["connected"]) and agreement_ratio >= 0.95,
        "search_completion_target": completion_ratio >= required_completion
        and minimum_agent_completion >= required_completion,
        "distinct_target_confirmers": confirmed_targets >= min(3, len(search_ids)),
        "zero_collisions": collisions == 0,
        "safe_minimum_separation": minimum_separation >= contract.safety.minimum_separation_m,
        "safety_faults_exercised": "return" in all_safety or "land" in all_safety,
        "zero_central_control_commands": central_commands == 0,
    }
    metrics = {
        "vehicles": config.vehicle_count,
        "survivors": len(survivors),
        "injected_failures": len(failed),
        "completed_search_cells": len(completed_search),
        "search_cells": len(search_ids),
        "search_completion_ratio": round(completion_ratio, 4),
        "confirmed_targets": confirmed_targets,
        "minimum_agent_search_completion_ratio": round(minimum_agent_completion, 4),
        "ledger_agreement_ratio": round(agreement_ratio, 4),
        "minimum_intervehicle_distance_m": None if math.isinf(minimum_separation) else round(minimum_separation, 4),
        "collisions": collisions,
        "central_control_commands": central_commands,
        "task_udp_sent_datagrams": sum(item["task_udp_metrics"]["sent_datagrams"] for item in artifacts),
        "task_udp_received_messages": sum(item["task_udp_metrics"]["received_messages"] for item in artifacts),
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "worker_pids": pids,
        "station_closed_at": station_closed_at,
        "start_at": start_at,
        "scope": "Kinematic multi-process UDP simulation; not a hardware flight-safety certification.",
    }


def run_mission_process_trial(config: MissionStressConfig) -> dict[str, Any]:
    output = Path(config.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for pattern in ("ready-*", "agent-*.json", "agent-*.json.tmp", "agent-*.csv", "start.json"):
        for path in output.glob(pattern):
            if path.is_file() and path.parent == output:
                path.unlink()
    contract = _contract_for(config)
    task_port = config.task_udp_base_port or _free_base_port(config.vehicle_count, 36000)
    motion_port = config.motion_udp_base_port or _free_base_port(config.vehicle_count, 50000)
    config_data = asdict(config)
    config_data["output_dir"] = str(output)
    context = mp.get_context("spawn")
    processes = [
        context.Process(
            target=_worker_main,
            args=(vehicle_id, config_data, contract.mission_id, contract.digest, task_port, motion_port),
            name=f"mission-agent-{vehicle_id}",
        )
        for vehicle_id in range(config.vehicle_count)
    ]
    for process in processes:
        process.start()
    ready_deadline = time.monotonic() + 20
    while time.monotonic() < ready_deadline:
        if len(list(output.glob("ready-*"))) == config.vehicle_count:
            break
        time.sleep(0.02)
    if len(list(output.glob("ready-*"))) != config.vehicle_count:
        for process in processes:
            process.terminate()
        raise RuntimeError("not every worker bound its UDP endpoints")

    task_config = TaskUdpConfig(base_port=task_port)
    station = MissionTaskStation(
        contract.mission_id,
        contract.digest,
        tuple(range(config.vehicle_count)),
        config=task_config,
    )
    accepted: set[int] = set()
    accept_deadline = time.monotonic() + 10
    while time.monotonic() < accept_deadline and len(accepted) < config.vehicle_count:
        station.offer(contract.to_dict(), now=time.monotonic())
        time.sleep(0.02)
        accepted |= station.poll_accepts()
    if len(accepted) != config.vehicle_count:
        station.close()
        for process in processes:
            process.terminate()
        raise RuntimeError(f"mission offer accepted by {len(accepted)}/{config.vehicle_count} workers")
    station.close()
    station_closed_at = time.monotonic()
    start_at = station_closed_at + 0.25
    temporary = output / "start.json.tmp"
    temporary.write_text(json.dumps({"start_at": start_at}), encoding="utf-8")
    temporary.replace(output / "start.json")
    join_deadline = time.monotonic() + config.duration_s + 20
    for process in processes:
        process.join(max(0.0, join_deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(2)
    artifacts = [
        json.loads((output / f"agent-{vehicle_id}.json").read_text(encoding="utf-8"))
        for vehicle_id in range(config.vehicle_count)
        if (output / f"agent-{vehicle_id}.json").exists()
    ]
    if len(artifacts) != config.vehicle_count:
        raise RuntimeError(f"only {len(artifacts)}/{config.vehicle_count} workers wrote artifacts")
    summary = _evaluate(config, contract, artifacts, station_closed_at, start_at)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report = [
        "# 100 机去中心化任务模拟报告",
        "",
        f"- 验收结果：{'通过' if summary['accepted'] else '未通过'}",
        f"- 独立进程：{len(summary['worker_pids'])}",
        f"- 搜索完成率：{summary['metrics']['search_completion_ratio']:.1%}",
        f"- 碰撞：{summary['metrics']['collisions']}",
        f"- 中央控制命令：{summary['metrics']['central_control_commands']}",
        "",
        "该结果是运动学与真实本机 UDP 多进程模拟，不是实机飞行安全认证。",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    _write_plots(output, artifacts)
    return summary
