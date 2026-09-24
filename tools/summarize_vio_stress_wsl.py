"""Summarize preserved PX4/Gazebo VIO stress trials from original artifacts."""

from __future__ import annotations

import bisect
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

from flydrones.vio_stress_evidence import summarize_post_gnss_evidence

ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT / "results/vio-stress"
TREE_CENTERS = [(2.5, (index - 2) * 2.0 + 0.05) for index in range(5)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nearest(samples: list[tuple[float, list[float]]], when: float) -> tuple[float, list[float]] | None:
    if not samples:
        return None
    times = [item[0] for item in samples]
    index = bisect.bisect_left(times, when)
    return min((samples[candidate] for candidate in (index - 1, index) if 0 <= candidate < len(samples)),
               key=lambda item: abs(item[0] - when))


def _relay_metrics(path: Path, fleet_size: int) -> tuple[dict, dict[str, list[tuple[float, list[float]]]]]:
    ingress = {}
    raw: dict[str, list[tuple[float, list[float]]]] = {}
    publishes = []
    drop_reasons: dict[str, int] = {}
    simulation_clock: list[tuple[float, int]] = []
    if not path.exists():
        return {"error": "relay log missing"}, raw
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        if event["event"] == "ingress":
            if event["reason"] != "queued":
                drop_reasons[event["reason"]] = drop_reasons.get(event["reason"], 0) + 1
            if "raw_position_m" in event:
                key = (event["model"], event["source_stamp_ns"])
                ingress[key] = event["raw_position_m"]
                raw.setdefault(event["model"], []).append((event["received_at"], event["raw_position_m"]))
                if event["model"] == "x500_depth_fly_0":
                    simulation_clock.append((event["received_at"], event["source_stamp_ns"]))
        elif event["event"] == "publish":
            publishes.append(event)
    for samples in raw.values():
        samples.sort()
    active = [event for event in publishes if event["model"] == "x500_depth_fly_0" and event["active"]]
    delays = sorted(event["actual_delay_ms"] for event in active)
    offsets = [math.dist(event["offset_m"], (0, 0, 0)) for event in active]
    errors = []
    transform_errors = []
    for event in active:
        if "published_position_m" not in event:
            continue
        source = ingress.get((event["model"], event["source_stamp_ns"]))
        if source is not None:
            transform_errors.append(math.dist(
                event["published_position_m"],
                [source[index] + event["offset_m"][index] for index in range(3)],
            ))
        current = _nearest(raw.get(event["model"], []), event["published_at"])
        if current is not None and abs(current[0] - event["published_at"]) <= 0.1:
            errors.append(math.dist(event["published_position_m"], current[1]))
    tree_clearance = min((math.hypot(position[0] - x, position[1] - y) - 0.22
                          for samples in raw.values() for _time, position in samples
                          if 0.05 <= position[2] <= 3.0 for x, y in TREE_CENTERS), default=None)
    all_samples = sorted((timestamp, model, position) for model, samples in raw.items()
                         for timestamp, position in samples)
    recent: dict[str, tuple[float, list[float]]] = {}
    min_peer = None
    for timestamp, model, position in all_samples:
        recent[model] = (timestamp, position)
        if fleet_size == 5 and len(recent) == 5 and all(timestamp - item[0] <= 0.1 for item in recent.values()):
            current = min(math.dist(left[1], right[1]) for left, right in
                          itertools.combinations(recent.values(), 2))
            min_peer = current if min_peer is None else min(min_peer, current)
    return {
        "published_total": len(publishes),
        "fault_vehicle_active_published": len(active),
        "drop_reasons": drop_reasons,
        "actual_delay_median_ms": delays[len(delays) // 2] if delays else None,
        "actual_delay_p95_ms": delays[min(len(delays) - 1, int(len(delays) * 0.95))] if delays else None,
        "maximum_position_offset_m": round(max(offsets), 4) if offsets else None,
        "nonzero_offset_published_samples": sum(offset > 1e-9 for offset in offsets),
        "maximum_transformation_error_m": round(max(transform_errors), 7) if transform_errors else None,
        "position_error_vs_raw_truth_at_publish_p95_m": round(sorted(errors)[int(len(errors) * 0.95)], 4)
        if errors else None,
        "position_error_vs_raw_truth_at_publish_max_m": round(max(errors), 4) if errors else None,
        "minimum_center_to_trunk_surface_m": round(tree_clearance, 4) if tree_clearance is not None else None,
        "minimum_intervehicle_center_distance_m": round(min_peer, 4) if min_peer is not None else None,
        "simulated_seconds_per_wall_second": round(
            (simulation_clock[-1][1] - simulation_clock[0][1]) / 1_000_000_000
            / (simulation_clock[-1][0] - simulation_clock[0][0]), 4
        ) if len(simulation_clock) >= 2 and simulation_clock[-1][0] > simulation_clock[0][0] else None,
    }, raw


def _ulog_metrics(path: Path) -> dict:
    from pyulog import ULog

    if not path.exists():
        return {"accepted": False, "error": "ULog missing"}
    ulog = ULog(str(path))
    datasets = {dataset.name: dataset.data for dataset in ulog.data_list if dataset.multi_id == 0}
    disable = next((float(timestamp) / 1_000_000 for timestamp, name, value in ulog.changed_parameters
                    if name == "EKF2_GPS_CTRL" and int(value) == 0), None)
    result = summarize_post_gnss_evidence(datasets, gps_disable_s=disable)
    result["source"] = {"ulog_sha256": _sha256(path), "ulog_bytes": path.stat().st_size}
    return result


def summarize_trial(directory: Path) -> dict:
    manifest = json.loads((directory / "trial-manifest.json").read_text(encoding="utf-8"))
    count = manifest["fleet_size"]
    relay, raw = _relay_metrics(directory / "vio-relay.jsonl", count)
    workers = []
    for vehicle_id in range(count):
        result_path = directory / f"agent-{vehicle_id}.json"
        csv_path = directory / f"agent-{vehicle_id}.csv"
        if not result_path.exists() or not csv_path.exists():
            workers.append({"vehicle_id": vehicle_id, "error": "worker artifacts missing"})
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        model = f"x500_depth_fly_{vehicle_id}"
        initial_error = None
        if rows and raw.get(model):
            nearest = _nearest(raw[model], float(rows[0]["monotonic_s"]))
            if nearest is not None and abs(nearest[0] - float(rows[0]["monotonic_s"])) <= 0.2:
                initial_error = math.hypot(float(rows[0]["x_m"]) - nearest[1][0],
                                           float(rows[0]["y_m"]) - nearest[1][1])
        workers.append({
            "vehicle_id": vehicle_id,
            "mission_accepted": bool(result["accepted"]),
            "landed": bool(result["checks"]["landed"]),
            "fail_closed_land": bool(result["metrics"]["fail_closed_land"]),
            "gnss_disable_injected": bool(result["metrics"]["gps_failure_injected"]),
            "state_health_failures": result["metrics"]["state_health_failures"],
            "planner_p95_ms": result["metrics"]["planner_p95_ms"],
            "initial_estimated_vs_truth_horizontal_error_m": round(initial_error, 4)
            if initial_error is not None else None,
            "initial_estimated_vs_expected_home_error_m": round(math.hypot(
                float(rows[0]["x_m"]), float(rows[0]["y_m"]) - ((vehicle_id - 2) * 2.0)
            ), 4) if rows else None,
            "minimum_depth_range_m": round(min(float(row["depth_nearest_m"]) for row in rows
                                               if row["depth_nearest_m"]), 4) if rows else None,
        })
    visual = _ulog_metrics(directory / "px4-ulogs/agent-0.ulg")
    combined = {
        "schema": "flydrones-vio-stress-summary-v1",
        "name": manifest["name"],
        "fleet_size": count,
        "profile_sha256": manifest["profile_sha256"],
        "policy_sha256": manifest["policy_sha256"],
        "launch_exit_code": manifest["launch_exit_code"],
        "worker_exit_code": manifest["worker_exit_code"],
        "relay": relay,
        "visual_after_gnss_disable": visual,
        "workers": workers,
        "mission_and_visual_continuity_pass": (
            all(worker.get("mission_accepted", False) for worker in workers) and visual["accepted"]
        ),
    }
    (directory / "stress-summary.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return combined


def main() -> int:
    results = []
    for directory in sorted(TRIALS.iterdir()):
        if (directory / "trial-manifest.json").exists():
            results.append(summarize_trial(directory))
    (TRIALS / "all-trials.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    for item in results:
        print(item["name"], "mission+EV", item["mission_and_visual_continuity_pass"],
              "handoff", item["visual_after_gnss_disable"]["checks"].get("gnss_to_visual_handoff_proven"),
              "worker", [worker.get("mission_accepted") for worker in item["workers"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
