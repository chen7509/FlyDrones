"""Summarize preserved PX4/Gazebo VIO stress trials from original artifacts."""

from __future__ import annotations

import bisect
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

from flydrones.vio_stress_evidence import match_relay_to_visual_odometry, summarize_post_gnss_evidence

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


def _relay_metrics(path: Path, fleet_size: int) -> tuple[dict, dict[str, list[tuple[float, list[float]]]], list[dict]]:
    ingress = {}
    raw: dict[str, list[tuple[float, list[float]]]] = {}
    publishes = []
    drop_reasons: dict[str, int] = {}
    simulation_clock: list[tuple[float, int]] = []
    last_event = None
    malformed_lines = 0
    if not path.exists():
        return {"error": "relay log missing"}, raw, publishes
    for line in path.open(encoding="utf-8"):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            last_event = None
            continue
        last_event = event.get("event")
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
        "closed_cleanly": last_event == "stop",
        "malformed_log_lines": malformed_lines,
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
    }, raw, publishes


def _ulog_metrics(path: Path, publishes: list[dict]) -> tuple[dict, dict]:
    from pyulog import ULog

    if not path.exists():
        return {"accepted": False, "error": "ULog missing"}, {"matched_active_samples": 0}
    ulog = ULog(str(path))
    datasets = {dataset.name: dataset.data for dataset in ulog.data_list if dataset.multi_id == 0}
    disable = next((float(timestamp) / 1_000_000 for timestamp, name, value in ulog.changed_parameters
                    if name == "EKF2_GPS_CTRL" and int(value) == 0), None)
    result = summarize_post_gnss_evidence(datasets, gps_disable_s=disable)
    result["source"] = {"ulog_sha256": _sha256(path), "ulog_bytes": path.stat().st_size}
    return result, match_relay_to_visual_odometry(publishes, datasets.get("vehicle_visual_odometry", {}))


def classify_trial(trial: dict, profile: dict) -> dict:
    """Keep mission, fail-closed response and limited geometry checks distinct."""
    workers = trial["workers"]
    relay = trial["relay"]
    correspondence = trial["relay_to_px4"]
    active = relay.get("fault_vehicle_active_published", 0) > 0
    fault_effect = active
    if profile.get("delay_ms", 0):
        fault_effect = fault_effect and (relay.get("actual_delay_median_ms") or 0) >= 0.8 * profile["delay_ms"]
    if profile.get("dropout_duration_s", 0) or profile.get("drop_probability", 0):
        fault_effect = fault_effect and sum(relay.get("drop_reasons", {}).get(key, 0)
                                              for key in ("scheduled-dropout", "random-dropout")) > 0
    has_offset = any(abs(value) > 0 for field in ("drift_mps", "false_pose_offset_m")
                     for value in profile.get(field, (0, 0, 0)))
    if has_offset:
        fault_effect = fault_effect and relay.get("nonzero_offset_published_samples", 0) > 0
    px4_effect = fault_effect and correspondence.get("matched_active_samples", 0) >= 10
    if profile.get("delay_ms", 0):
        px4_effect = px4_effect and (
            correspondence.get("median_ulog_minus_source_stamp_ms") or 0
        ) >= 0.75 * profile["delay_ms"]
    if has_offset:
        px4_effect = px4_effect and correspondence.get("matched_offset_samples", 0) >= 3
    if profile.get("dropout_duration_s", 0):
        px4_effect = px4_effect and (
            trial["visual_after_gnss_disable"].get("metrics", {}).get("visual_stream_max_gap_ms") or 0
        ) >= 0.75 * profile["dropout_duration_s"] * 1000
    peer = relay.get("minimum_intervehicle_center_distance_m")
    forest = relay.get("minimum_center_to_trunk_surface_m")
    peer_geometry = trial["fleet_size"] == 1 or peer is not None and peer >= 0.72
    # Existing simulated envelope: 0.25 m vehicle radius plus 0.10 m margin.
    forest_geometry = forest is not None and forest >= 0.35
    geometry = peer_geometry and forest_geometry
    all_landed = len(workers) == trial["fleet_size"] and all(worker.get("landed") for worker in workers)
    all_mission = len(workers) == trial["fleet_size"] and all(worker.get("mission_accepted") for worker in workers)
    fault_worker = workers[0] if workers else {}
    ready = (trial["launch_exit_code"] == 0 and relay.get("closed_cleanly", False)
             and fault_worker.get("gnss_disable_injected") and px4_effect)
    continuity = (ready and trial["worker_exit_code"] == 0 and all_mission and all_landed
                  and trial["visual_after_gnss_disable"].get("accepted", False) and geometry)
    cleanup = trial.get("stop_exit_code") == 0 and trial.get("shared_px4_files_restored") is True
    return {
        "fault_effect_observed_at_relay": bool(fault_effect),
        "fault_effect_proven_at_px4": bool(px4_effect),
        "geometry_separation_check_pass": bool(peer_geometry),
        "geometry_forest_clearance_check_pass": bool(forest_geometry),
        "all_landed": bool(all_landed),
        "mission_visual_geometry_pass": bool(continuity),
        "trial_cleanup_verified": bool(cleanup),
        "fault_vehicle_fail_closed_landing_observed": bool(
            fault_worker.get("fail_closed_land") and fault_worker.get("landed") and geometry
        ),
        "fault_vehicle_verified_fail_closed_response": False,
        "fail_closed_verification_limit": (
            "Worker landing alone does not prove command silence during invalid EKF state; "
            "ULog-to-command timeline correlation is required."
        ),
        "operational_continuity_pass": bool(continuity and cleanup),
        "safety_limit": "Geometry is a center-distance proxy; physical contact is not proven absent.",
    }


def summarize_trial(directory: Path) -> dict:
    manifest = json.loads((directory / "trial-manifest.json").read_text(encoding="utf-8"))
    count = manifest["fleet_size"]
    relay, raw, publishes = _relay_metrics(directory / "vio-relay.jsonl", count)
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
            "last_state_health_reason": result["metrics"].get("last_state_health_reason"),
            "planner_p95_ms": result["metrics"]["planner_p95_ms"],
            "initial_estimated_vs_truth_horizontal_error_m": round(initial_error, 4)
            if initial_error is not None else None,
            "initial_estimated_vs_expected_home_error_m": round(math.hypot(
                float(rows[0]["x_m"]), float(rows[0]["y_m"]) - ((vehicle_id - 2) * 2.0)
            ), 4) if rows else None,
            "minimum_depth_range_m": round(min(float(row["depth_nearest_m"]) for row in rows
                                               if row["depth_nearest_m"]), 4) if rows else None,
        })
    visual, correspondence = _ulog_metrics(directory / "px4-ulogs/agent-0.ulg", publishes)
    profile = json.loads((directory / "fault-profile.json").read_text(encoding="utf-8"))
    combined = {
        "schema": "flydrones-vio-stress-summary-v3",
        "name": manifest["name"],
        "fleet_size": count,
        "profile_sha256": manifest["profile_sha256"],
        "policy_sha256": manifest["policy_sha256"],
        "launch_exit_code": manifest["launch_exit_code"],
        "worker_exit_code": manifest["worker_exit_code"],
        "stop_exit_code": manifest.get("stop_exit_code"),
        "shared_px4_files_restored": manifest.get("shared_px4_files_restored"),
        "relay": relay,
        "relay_to_px4": correspondence,
        "visual_after_gnss_disable": visual,
        "workers": workers,
    }
    combined.update(classify_trial(combined, profile))
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
        print(item["name"], "operational", item["operational_continuity_pass"],
              "handoff", item["visual_after_gnss_disable"]["checks"].get("gnss_to_visual_handoff_proven"),
              "worker", [worker.get("mission_accepted") for worker in item["workers"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
