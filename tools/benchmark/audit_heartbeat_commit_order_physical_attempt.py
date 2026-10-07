"""Audit the immutable study-v21 physical run and its failed VIO result."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.trajectory_gauge_contract import audit_trajectory, trajectory_contract

EXPECTED = {
    "capture_status": "capture_completed",
    "errors": [],
    "end_sim_ns": 25_000_000_000,
    "px4_exit_code": 0,
    "native_exit_code": 0,
    "writer_counts": {"imu": 6251, "info": 251, "depth": 251, "rgb": 251, "heartbeat": 24},
    "fanout_committed": 7028,
    "fanout_failure": None,
    "fanout_refusals": [],
    "heartbeat_observed": 24,
    "heartbeat_reconciled": 24,
    "heartbeat_pending": [],
    "heartbeat_failure": None,
    "native_reference_pre": 25000,
    "native_reference_post": 25000,
    "motion_support_steps": 22380,
    "motion_active_steps": 1600,
    "motion_commands": 22380,
    "motion_absolute_impulse_ns": 41.6,
    "motion_signed_impulse_ns": 0.0,
    "motion_anchor_ns": 2_621_000_000,
    "physics_records": 50000,
    "runtime_mapping": True,
    "runtime_closure": False,
    "eligible_for_vio_input": False,
    "eligible_for_px4_fusion": False,
    "completion_command_returncode": 0,
    "completion_launcher_returncode": 0,
    "completion_destination_exists": True,
    "completion_resources_after": [],
    "supervisor_capture_status": "capture_completed",
    "supervisor_worker_exit": 0,
    "supervisor_no_executing": True,
    "supervisor_group_absent": True,
    "supervisor_sigkill": False,
    "supervisor_descendants_qualified": False,
    "ulog_count": 1,
    "ulog_identity_verified": True,
    "trajectory_reference": "native-reference-canary-overwritten-v1",
    "trajectory_reference_count": 25000,
}


def _require_equal(summary, expected, failures, prefix=""):
    for key, value in expected.items():
        actual = summary.get(key)
        label = f"{prefix}{key}"
        if isinstance(value, dict):
            if not isinstance(actual, dict):
                failures.append(label)
            else:
                _require_equal(actual, value, failures, label + ".")
        elif actual != value:
            failures.append(label)


def classify_summary(summary):
    if not isinstance(summary, dict):
        raise ValueError("invalid summary")
    failures = []
    _require_equal(summary, EXPECTED, failures)
    trajectory = summary.get("trajectory")
    if not isinstance(trajectory, dict):
        failures.append("trajectory")
        trajectory = {}
    required_trajectory = {
        "capture_complete": True,
        "public_coverage_qualified": True,
        "diagnostic_available": True,
        "diagnostic_screens_pass": False,
        "estimator_health_qualified": False,
        "trajectory_qualified": False,
    }
    _require_equal(trajectory, required_trajectory, failures, "trajectory.")
    reasons = trajectory.get("reasons")
    required_reasons = {"reset_unknown", "quality_unknown", "covariance_uncalibrated", "accuracy_screen_failed"}
    if not isinstance(reasons, list) or not required_reasons.issubset(reasons):
        failures.append("trajectory.reasons")
    metrics = trajectory.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("max_position_error_m"), (int, float)):
        failures.append("trajectory.metrics")
    elif metrics["max_position_error_m"] <= 0.25 or metrics.get("max_velocity_error_m_s", 0) <= 0.25:
        failures.append("trajectory.failed screens")
    qualified = not failures
    return {
        "schema": "heartbeat-commit-order-physical-attempt-audit-v1",
        "failures": failures,
        "attempt_evidence_qualified": qualified,
        "classification": "completed-physical-run-vio-accuracy-and-health-failure",
        "physical_execution_qualified": qualified,
        "heartbeat_commit_order_physically_verified": qualified,
        "runtime_mapping_coverage_verified": qualified,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "ekf2_injection_qualified": False,
        "flight_ready": False,
        "fruit_fly_policy_failure": False,
        "scope": "completed disarmed fixture and failed VIO; fruit-fly policy did not run",
    }


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _count(path):
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def _finite_vector(value, size, name):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"invalid {name}")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError(f"invalid {name}")
        result.append(float(item))
    return result


def native_reference_truth(rows):
    """Convert the per-step canary-overwritten native reference for offline scoring."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing native reference")
    result = []
    previous = None
    for row in rows:
        if not isinstance(row, dict) or row.get("truth_for_abort_audit_only") is not True:
            raise ValueError("invalid native reference scope")
        stamp = row.get("post_ns")
        if type(stamp) is not int or stamp <= 0 or row.get("pre_ns") != stamp:
            raise ValueError("invalid native reference time")
        if previous is not None and stamp <= previous:
            raise ValueError("native reference time regressed")
        previous = stamp
        if row.get("canary_overwritten") is not True:
            raise ValueError("native reference canary not overwritten")
        orientation = _finite_vector(row.get("quaternion_xyzw"), 4, "native reference orientation")
        norm = math.sqrt(sum(item * item for item in orientation))
        if abs(norm - 1.0) > 0.01:
            raise ValueError("invalid native reference orientation")
        result.append(
            {
                "sim_ns": stamp,
                "position": _finite_vector(row.get("position"), 3, "native reference position"),
                "velocity_world": _finite_vector(row.get("velocity_world"), 3, "native reference velocity"),
                "accel_world": _finite_vector(row.get("accel_world"), 3, "native reference acceleration"),
                "angular_world": _finite_vector(row.get("angular_world"), 3, "native reference angular velocity"),
                "quaternion_xyzw": orientation,
                "truth_for_fixture_audit_only": True,
                "source": "native-reference-canary-overwritten-v1",
            }
        )
    return result


def _ulog_verified(capture, result, manifest):
    logs = manifest.get("logs") if isinstance(manifest, dict) else None
    if manifest.get("schema") != "flydrones-px4-ulog-capture-v1" or not isinstance(logs, list):
        return False
    if result.get("px4_ulogs") != logs or len(logs) != 1:
        return False
    item = logs[0]
    path = capture / item.get("path", "")
    if not path.is_file() or item.get("valid_header") is not True:
        return False
    data = path.read_bytes()
    return len(data) == item.get("bytes") and hashlib.sha256(data).hexdigest() == item.get("sha256")


def audit(capture, completion):
    capture = Path(capture).resolve(strict=True)
    completion = Path(completion).resolve(strict=True)
    result = _read(capture / "result.json")
    completed = _read(completion)
    supervisor = _read(capture / "supervisor.json")
    manifest = _read(capture / "px4-ulog-manifest.json")
    anchor = _read(capture / "readiness-anchor.json")
    states = _jsonl(capture / "shadow" / "states.jsonl")
    native_reference_rows = _jsonl(capture / "native-reference.jsonl")
    truth = native_reference_truth(native_reference_rows)
    session_path = capture / "shadow" / "native-session.json"
    session_raw = session_path.read_bytes()
    session_value = json.loads(session_raw)
    session = {
        "session_id": hashlib.sha256(session_raw).hexdigest(),
        "reset_counter": session_value.get("reset_counter"),
        "quality": session_value.get("quality"),
        "reset_observed": False,
        "covariance_calibrated": False,
    }
    contract = trajectory_contract(
        anchor_ns=anchor.get("anchor_ns"),
        total_duration_ns=anchor.get("profile", {}).get("total_duration_ns"),
        lateral_start_offset_ns=anchor.get("profile", {}).get("lateral_start_after_anchor_ns"),
    )
    trajectory = audit_trajectory(states, truth, session, result, contract)
    motion = result.get("motion", {})
    fanout = result.get("source_fanout", {})
    heartbeat = fanout.get("heartbeat", {})
    native_reference = result.get("native_reference", {})
    runtime = result.get("runtime_binding", {})
    cleanup = supervisor.get("cleanup", {})
    summary = {
        "capture_status": result.get("status"),
        "errors": result.get("errors"),
        "end_sim_ns": result.get("end_sim_ns"),
        "px4_exit_code": result.get("px4_exit_code"),
        "native_exit_code": result.get("native", {}).get("exit"),
        "writer_counts": result.get("writer", {}).get("written"),
        "fanout_committed": fanout.get("committed"),
        "fanout_failure": fanout.get("failure"),
        "fanout_refusals": fanout.get("refusals"),
        "heartbeat_observed": heartbeat.get("observed"),
        "heartbeat_reconciled": heartbeat.get("reconciled"),
        "heartbeat_pending": heartbeat.get("pending"),
        "heartbeat_failure": heartbeat.get("failure"),
        "native_reference_pre": native_reference.get("pre_count"),
        "native_reference_post": native_reference.get("post_count"),
        "motion_support_steps": motion.get("support_steps"),
        "motion_active_steps": motion.get("active_steps"),
        "motion_commands": motion.get("recorded_commands"),
        "motion_absolute_impulse_ns": motion.get("absolute_impulse_ns"),
        "motion_signed_impulse_ns": motion.get("signed_impulse_ns"),
        "motion_anchor_ns": motion.get("anchor_ns"),
        "physics_records": result.get("physics_trace", {}).get("records"),
        "runtime_mapping": runtime.get("runtime_mapping_coverage_verified"),
        "runtime_closure": runtime.get("runtime_closure_qualified"),
        "eligible_for_vio_input": result.get("eligible_for_vio_input"),
        "eligible_for_px4_fusion": result.get("eligible_for_px4_fusion"),
        "completion_command_returncode": completed.get("command_returncode"),
        "completion_launcher_returncode": completed.get("launcher_returncode"),
        "completion_destination_exists": completed.get("destination_exists"),
        "completion_resources_after": completed.get("resources_after"),
        "supervisor_capture_status": supervisor.get("capture_status"),
        "supervisor_worker_exit": supervisor.get("worker_exit"),
        "supervisor_no_executing": cleanup.get("no_executing_members"),
        "supervisor_group_absent": cleanup.get("group_absent"),
        "supervisor_sigkill": cleanup.get("sigkill_dispatched"),
        "supervisor_descendants_qualified": cleanup.get("all_descendant_cleanup_qualified"),
        "ulog_count": len(manifest.get("logs", [])),
        "ulog_identity_verified": _ulog_verified(capture, result, manifest),
        "trajectory_reference": "native-reference-canary-overwritten-v1",
        "trajectory_reference_count": len(truth),
        "trajectory": trajectory,
    }
    classified = classify_summary(summary)
    line_counts = {
        "source_events": _count(capture / "events.jsonl"),
        "source_fanout": _count(capture / "source-fanout.jsonl"),
        "heartbeat_observations": _count(capture / "heartbeat-observations.jsonl"),
        "native_requests": _count(capture / "shadow" / "native-requests.jsonl"),
        "native_acks": _count(capture / "shadow" / "native-acks.jsonl"),
        "states": len(states),
        "readiness": _count(capture / "estimator-readiness.jsonl"),
        "native_reference": len(native_reference_rows),
        "physics_substeps": _count(capture / "physics-substeps.jsonl"),
        "motion_commands": _count(capture / "motion-force.jsonl"),
        "motion_truth": _count(capture / "motion-ground-truth.jsonl"),
    }
    expected_lines = {
        "source_events": 7028,
        "source_fanout": 14056,
        "heartbeat_observations": 48,
        "native_requests": 6501,
        "native_acks": 6501,
        "states": 250,
        "readiness": 226,
        "native_reference": 25000,
        "physics_substeps": 50000,
        "motion_commands": 22380,
        "motion_truth": 6250,
    }
    for key, expected in expected_lines.items():
        if line_counts.get(key) != expected:
            classified["failures"].append(f"line_counts.{key}")
    if classified["failures"]:
        classified["attempt_evidence_qualified"] = False
        classified["physical_execution_qualified"] = False
        classified["heartbeat_commit_order_physically_verified"] = False
        classified["runtime_mapping_coverage_verified"] = False
    classified.update(
        summary=summary,
        line_counts=line_counts,
        input_identities={
            name: {
                "bytes": (capture / name).stat().st_size,
                "sha256": hashlib.sha256((capture / name).read_bytes()).hexdigest(),
            }
            for name in (
                "result.json",
                "shadow/states.jsonl",
                "shadow/native.log",
                "motion-ground-truth.jsonl",
                "events.jsonl",
                "source-fanout.jsonl",
                "native-reference.jsonl",
                "physics-substeps.jsonl",
            )
        },
    )
    return classified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.completion)
    write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["attempt_evidence_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
