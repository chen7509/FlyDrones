"""Summarize preserved PX4/Gazebo VIO stress trials from original artifacts."""

from __future__ import annotations

import bisect
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

from flydrones.runtime_timing import summarize_gap_series
from flydrones.vio_stress_evidence import (
    match_relay_to_visual_odometry,
    summarize_external_vision_health,
    summarize_post_gnss_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT / "results/vio-stress"
TREE_CENTERS = [(2.5, (index - 2) * 2.0 + 0.05) for index in range(5)]


def _manifest_frozen_hash(manifest: dict, name: str) -> str | None:
    frozen = manifest.get("frozen_hashes")
    if isinstance(frozen, dict) and frozen.get(name):
        return str(frozen[name])
    legacy = manifest.get(f"{name}_sha256")
    return str(legacy) if legacy else None


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _rtf(rows: list[dict[str, str]], epoch_start_s: float | None = None) -> float | None:
    selected = [
        row for row in rows
        if epoch_start_s is None or float(row["monotonic_s"]) >= epoch_start_s
    ]
    if len(selected) < 2:
        return None
    wall_delta = float(selected[-1]["monotonic_s"]) - float(selected[0]["monotonic_s"])
    sim_delta = (float(selected[-1]["sim_ns"]) - float(selected[0]["sim_ns"])) / 1_000_000_000
    return sim_delta / wall_delta if wall_delta > 0 else None


def summarize_runtime_evidence(
    directory: Path,
    *,
    raw: dict[str, list[tuple[float, list[float]]]],
    worker_rows: list[list[dict[str, str]]],
    fleet_size: int,
) -> dict[str, object]:
    errors = []
    healthy_starts = []
    if len(worker_rows) == fleet_size:
        for rows in worker_rows:
            first = next((
                float(row["monotonic_s"])
                for row in rows
                if row.get("state_healthy", "").lower() == "true"
                and row.get("phase") not in {"preflight", "fail_closed"}
            ), None)
            if first is None:
                break
            healthy_starts.append(first)
    epoch = max(healthy_starts) if len(healthy_starts) == fleet_size else None
    if epoch is None:
        errors.append("steady-state epoch unavailable")

    clock_rows = _csv_rows(directory / "clock-probe.csv")
    resource_rows = _csv_rows(directory / "resource-probe.csv")
    gpu_rows = _csv_rows(directory / "gpu-probe.csv")
    if not clock_rows:
        errors.append("clock-probe.csv missing")
    if not resource_rows:
        errors.append("resource-probe.csv missing")
    if not gpu_rows:
        errors.append("gpu-probe.csv missing")

    clock = summarize_gap_series(clock_rows, epoch_start_s=epoch) if clock_rows else {
        "full_run": None,
        "steady_state_valid": False,
        "steady_state": None,
        "steady_state_epoch_monotonic_s": epoch,
    }
    if clock_rows and not clock["steady_state_valid"]:
        errors.append("steady-state clock gaps missing")
    raw_by_vehicle = {}
    for vehicle_id in range(fleet_size):
        samples = raw.get(f"x500_depth_fly_{vehicle_id}", [])
        gap_rows = [
            {
                "monotonic_s": str(current[0]),
                "interval_start_s": str(previous[0]),
                "wall_gap_ms": str((current[0] - previous[0]) * 1000),
            }
            for previous, current in zip(samples, samples[1:])
        ]
        raw_by_vehicle[str(vehicle_id)] = summarize_gap_series(gap_rows, epoch_start_s=epoch)
        if not gap_rows:
            errors.append(f"raw VIO gaps missing for vehicle {vehicle_id}")
        elif not raw_by_vehicle[str(vehicle_id)]["steady_state_valid"]:
            errors.append(f"steady-state raw VIO gaps missing for vehicle {vehicle_id}")

    if epoch is not None and resource_rows and not any(
        float(row["monotonic_s"]) >= epoch for row in resource_rows
    ):
        errors.append("steady-state resource samples missing")
    if epoch is not None and gpu_rows and not any(
        float(row["monotonic_s"]) >= epoch for row in gpu_rows
    ):
        errors.append("steady-state GPU availability samples missing")

    gpu_available = any(
        row.get("gpu_utilization_percent") not in {None, "", "unavailable"}
        for row in gpu_rows
    )
    return {
        "accepted": not errors,
        "errors": errors,
        "steady_state_epoch_monotonic_s": epoch,
        "clock": clock,
        "raw_vio_by_vehicle": raw_by_vehicle,
        "rtf": {
            "full_run": _rtf(clock_rows),
            "steady_state": _rtf(clock_rows, epoch),
        },
        "resource_samples": len(resource_rows),
        "gpu_samples": len(gpu_rows),
        "gpu_metrics_available": gpu_available,
    }


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
    active_source_stamps = sorted(float(event["source_stamp_ns"]) / 1e6 for event in active)
    active_source_gaps = [right - left for left, right in
                          zip(active_source_stamps, active_source_stamps[1:])]
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
        "fault_vehicle_active_source_max_gap_ms": (
            round(max(active_source_gaps), 3) if active_source_gaps else None
        ),
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


def _ulog_post_gnss_evidence(path: Path) -> dict:
    from pyulog import ULog

    if not path.exists():
        return {"accepted": False, "checks": {}, "metrics": {}, "error": "ULog missing"}
    try:
        ulog = ULog(str(path))
        datasets = {dataset.name: dataset.data for dataset in ulog.data_list if dataset.multi_id == 0}
        disable = next((float(timestamp) / 1_000_000 for timestamp, name, value in ulog.changed_parameters
                        if name == "EKF2_GPS_CTRL" and int(value) == 0), None)
        result = summarize_post_gnss_evidence(datasets, gps_disable_s=disable)
    except Exception as exc:
        return {"accepted": False, "checks": {}, "metrics": {},
                "error": f"ULog could not be read: {exc}"}
    result["source"] = {"ulog_sha256": _sha256(path), "ulog_bytes": path.stat().st_size}
    return result


def _ulog_metrics(path: Path, publishes: list[dict]) -> tuple[dict, dict, dict]:
    from pyulog import ULog

    result = _ulog_post_gnss_evidence(path)
    if not path.exists():
        return result, {"matched_active_samples": 0}, {}
    ulog = ULog(str(path))
    datasets = {dataset.name: dataset.data for dataset in ulog.data_list if dataset.multi_id == 0}
    return (result, match_relay_to_visual_odometry(publishes, datasets.get("vehicle_visual_odometry", {})),
            datasets.get("vehicle_status", {}))


def _ulog_external_vision_health(path: Path) -> dict:
    from pyulog import ULog

    if not path.exists():
        return {"accepted": False, "checks": {}, "metrics": {}, "error": "ULog missing"}
    try:
        ulog = ULog(str(path))
        datasets = {dataset.name: dataset.data for dataset in ulog.data_list if dataset.multi_id == 0}
        disable = next((float(timestamp) / 1_000_000 for timestamp, name, value in ulog.changed_parameters
                        if name == "EKF2_GPS_CTRL" and int(value) == 0), None)
        result = summarize_external_vision_health(
            datasets,
            start_s=disable + 0.2 if disable is not None else None,
        )
    except Exception as exc:
        return {"accepted": False, "checks": {}, "metrics": {},
                "error": f"ULog could not be read: {exc}"}
    result["source"] = {"ulog_sha256": _sha256(path), "ulog_bytes": path.stat().st_size}
    return result


def _relay_sim_clock(path: Path) -> list[tuple[float, float]]:
    if not path.exists():
        return []
    points = []
    for line in path.open(encoding="utf-8"):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "ingress" and event.get("model") == "x500_depth_fly_0":
            points.append((float(event["received_at"]), float(event["source_stamp_ns"]) / 1e9))
    return points


def verify_px4_land_transition(trigger: float | None, relay_clock: list[tuple[float, float]],
                               status: dict) -> dict:
    """Map the host gate time to Gazebo sim time, then inspect PX4 nav state."""
    result = {"observed": False, "gate_sim_time_s": None,
              "clock_alignment_error_s": None, "transition_after_gate_s": None}
    if trigger is None or not relay_clock or "timestamp" not in status or "nav_state" not in status:
        return result
    host, sim = min(relay_clock, key=lambda pair: abs(pair[0] - float(trigger)))
    alignment_error = abs(host - float(trigger))
    result["clock_alignment_error_s"] = round(alignment_error, 6)
    if alignment_error > 0.05:
        return result
    estimated_gate_sim = sim + (float(trigger) - host)
    result["gate_sim_time_s"] = round(estimated_gate_sim, 6)
    prior_nav = None
    for stamp, nav in zip(status["timestamp"], status["nav_state"]):
        state = int(nav)
        timestamp = float(stamp) / 1e6
        if state == 18 and prior_nav is not None and prior_nav != 18:
            lag = timestamp - estimated_gate_sim
            if 0 <= lag <= 0.2:
                result["observed"] = True
                result["transition_after_gate_s"] = round(lag, 6)
                break
        prior_nav = state
    return result


def verify_command_gate(rows: list[dict], metrics: dict, publishes: list[dict]) -> dict:
    """Correlate the relay gap with worker command silence and landing request."""
    trigger = metrics.get("fail_closed_triggered_at_s")
    last_command = metrics.get("last_command_sent_at_s")
    land_command = metrics.get("land_command_at_s")
    result = {
        "verified": False,
        "reason": metrics.get("last_state_health_reason"),
        "trigger_monotonic_s": trigger,
        "last_command_monotonic_s": last_command,
        "land_command_monotonic_s": land_command,
        "relay_gap_covering_trigger_s": None,
        "relay_sample_age_at_trigger_s": None,
        "no_autonomous_setpoint_after_trigger": False,
        "all_sent_setpoints_fresh": False,
        "max_relay_age_at_send_s": None,
        "land_request_sent": bool(metrics.get("land_request_sent")),
        "land_request_latency_s": None,
    }
    if trigger is None or last_command is None or land_command is None:
        return result
    trigger = float(trigger)
    relevant = sorted(
        (event for event in publishes if event.get("model") == "x500_depth_fly_0"
         and "published_at" in event and "received_at" in event),
        key=lambda event: float(event["published_at"]),
    )
    before = [event for event in relevant if float(event["published_at"]) <= trigger]
    after = [event for event in relevant if float(event["published_at"]) > trigger]
    if not before or not after:
        return result
    prior, following = before[-1], after[0]
    gap = float(following["published_at"]) - float(prior["published_at"])
    age = trigger - float(prior["received_at"])
    limit = float(metrics.get("vio_max_age_s") or 0.25)
    sent_rows = [row for row in rows if str(row.get("command_sent", "")).lower() == "true"]
    later_commands = False
    fresh_sent = bool(sent_rows)
    relay_ages = []
    publish_times = [float(event["published_at"]) for event in relevant]
    for row in sent_rows:
        try:
            sent_at = float(row["command_sent_at_s"])
            measured_age = float(row["vision_age_at_send_s"])
        except (KeyError, TypeError, ValueError):
            fresh_sent = False
            continue
        later_commands |= sent_at >= trigger - 0.000001
        prior_index = bisect.bisect_right(publish_times, sent_at) - 1
        if prior_index < 0:
            fresh_sent = False
            continue
        relay_age = sent_at - float(relevant[prior_index]["received_at"])
        relay_ages.append(relay_age)
        fresh_sent &= (math.isfinite(measured_age) and math.isfinite(relay_age)
                       and 0 <= measured_age <= limit and 0 <= relay_age <= limit)
    latency = float(land_command) - trigger
    result.update({
        "relay_gap_covering_trigger_s": round(gap, 6),
        "relay_sample_age_at_trigger_s": round(age, 6),
        "no_autonomous_setpoint_after_trigger": not later_commands,
        "all_sent_setpoints_fresh": fresh_sent,
        "max_relay_age_at_send_s": round(max(relay_ages), 6) if relay_ages else None,
        "land_request_latency_s": round(latency, 6),
        "verified": bool(
            metrics.get("last_state_health_reason") == "stale-vio-frame"
            and gap > limit and age >= limit
            and float(last_command) <= trigger
            and not later_commands and fresh_sent and metrics.get("land_request_sent")
            and 0.0 <= latency <= 0.2
        ),
    })
    return result


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
        source_gap_ms = relay.get("fault_vehicle_active_source_max_gap_ms") or 0
        px4_effect = px4_effect and (
            trial["visual_after_gnss_disable"].get("metrics", {}).get("visual_stream_max_gap_ms") or 0
        ) >= 0.75 * source_gap_ms and source_gap_ms >= 60
    peer = relay.get("minimum_intervehicle_center_distance_m")
    forest = relay.get("minimum_center_to_trunk_surface_m")
    peer_geometry = trial["fleet_size"] == 1 or peer is not None and peer >= 0.72
    # Existing simulated envelope: 0.25 m vehicle radius plus 0.10 m margin.
    forest_geometry = forest is not None and forest >= 0.35
    geometry = peer_geometry and forest_geometry
    all_landed = len(workers) == trial["fleet_size"] and all(worker.get("landed") for worker in workers)
    all_mission = len(workers) == trial["fleet_size"] and all(worker.get("mission_accepted") for worker in workers)
    fault_worker = workers[0] if workers else {}
    runtime = trial.get("runtime")
    runtime_ready = runtime is None or bool(
        runtime.get("accepted") and runtime.get("startup_reliability_pass")
    )
    post_gnss = trial.get("post_gnss_evidence_by_vehicle", {})
    all_post_gnss = len(post_gnss) == trial["fleet_size"] and all(
        post_gnss.get(str(vehicle_id), {}).get("accepted") is True
        for vehicle_id in range(trial["fleet_size"])
    )
    all_gnss_disabled = len(workers) == trial["fleet_size"] and all(
        worker.get("gnss_disable_injected") is True for worker in workers
    )
    ready = (trial["launch_exit_code"] == 0 and relay.get("closed_cleanly", False)
             and runtime_ready
             and all_gnss_disabled and all_post_gnss and px4_effect)
    continuity = (ready and trial["worker_exit_code"] == 0 and all_mission and all_landed
                  and trial["visual_after_gnss_disable"].get("accepted", False) and geometry)
    cleanup = trial.get("stop_exit_code") == 0 and trial.get("shared_px4_files_restored") is True
    gate_land_sequence = bool(
        fault_worker.get("command_gate", {}).get("verified")
        and fault_worker.get("px4_land_transition", {}).get("observed")
        and fault_worker.get("landed") and geometry and px4_effect and cleanup
    )
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
        "fault_vehicle_command_gate_verified": bool(
            fault_worker.get("command_gate", {}).get("verified")
        ),
        "fault_vehicle_gate_land_sequence_observed": gate_land_sequence,
        "fault_vehicle_verified_fail_closed_response": False,
        "fail_closed_verification_limit": (
            "The worker attempted a MAVLink land request and a subsequent PX4 AUTO_LAND "
            "transition can be correlated in sim time, but no COMMAND_ACK was captured; "
            "request causality and physical safety are not proven."
        ),
        "operational_continuity_pass": bool(continuity and cleanup),
        "safety_limit": "Geometry is a center-distance proxy; physical contact is not proven absent.",
    }


def summarize_trial(directory: Path) -> dict:
    manifest = json.loads((directory / "trial-manifest.json").read_text(encoding="utf-8"))
    count = manifest["fleet_size"]
    relay, raw, publishes = _relay_metrics(directory / "vio-relay.jsonl", count)
    workers = []
    worker_rows = []
    for vehicle_id in range(count):
        result_path = directory / f"agent-{vehicle_id}.json"
        csv_path = directory / f"agent-{vehicle_id}.csv"
        if not result_path.exists() or not csv_path.exists():
            workers.append({"vehicle_id": vehicle_id, "error": "worker artifacts missing"})
            worker_rows.append([])
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        worker_rows.append(rows)
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
            "command_gate": verify_command_gate(rows, result["metrics"], publishes)
            if vehicle_id == 0 else None,
            "planner_p95_ms": result["metrics"]["planner_p95_ms"],
            "initial_estimated_vs_truth_horizontal_error_m": round(initial_error, 4)
            if initial_error is not None else None,
            "initial_estimated_vs_expected_home_error_m": round(math.hypot(
                float(rows[0]["x_m"]), float(rows[0]["y_m"]) - ((vehicle_id - 2) * 2.0)
            ), 4) if rows else None,
            "minimum_depth_range_m": round(min(float(row["depth_nearest_m"]) for row in rows
                                               if row["depth_nearest_m"]), 4) if rows else None,
        })
    visual, correspondence, px4_status = _ulog_metrics(directory / "px4-ulogs/agent-0.ulg", publishes)
    external_vision_by_vehicle = {
        str(vehicle_id): _ulog_external_vision_health(
            directory / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
        )
        for vehicle_id in range(count)
    }
    post_gnss_by_vehicle = {
        str(vehicle_id): _ulog_post_gnss_evidence(
            directory / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
        )
        for vehicle_id in range(count)
    }
    if workers:
        workers[0]["px4_land_transition"] = verify_px4_land_transition(
            workers[0].get("command_gate", {}).get("trigger_monotonic_s"),
            _relay_sim_clock(directory / "vio-relay.jsonl"),
            px4_status,
        )
    profile = json.loads((directory / "fault-profile.json").read_text(encoding="utf-8"))
    runtime = summarize_runtime_evidence(
        directory,
        raw=raw,
        worker_rows=worker_rows,
        fleet_size=count,
    )
    renderer = manifest.get("renderer", {})
    runtime["startup_reliability_pass"] = bool(
        manifest.get("launch_exit_code") == 0
        and renderer.get("attestation", {}).get("accepted") is True
        and runtime["accepted"]
        and len(workers) == count
        and all("error" not in worker for worker in workers)
    )
    combined = {
        "schema": "flydrones-vio-stress-summary-v5",
        "name": manifest["name"],
        "fleet_size": count,
        "profile_sha256": _manifest_frozen_hash(manifest, "profile"),
        "policy_sha256": _manifest_frozen_hash(manifest, "policy"),
        "launch_exit_code": manifest["launch_exit_code"],
        "worker_exit_code": manifest["worker_exit_code"],
        "stop_exit_code": manifest.get("stop_exit_code"),
        "shared_px4_files_restored": manifest.get("shared_px4_files_restored"),
        "renderer": renderer,
        "runtime": runtime,
        "relay": relay,
        "relay_to_px4": correspondence,
        "visual_after_gnss_disable": visual,
        "external_vision_health_by_vehicle": external_vision_by_vehicle,
        "post_gnss_evidence_by_vehicle": post_gnss_by_vehicle,
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
