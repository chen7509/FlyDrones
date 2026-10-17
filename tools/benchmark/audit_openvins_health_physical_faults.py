"""Audit predeclared unarmed OpenVINS source-loss and restart evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record

EXPECTED = {
    "source_loss": {
        "run_id": "source-loss-retry-seed-27311",
        "seed": 27311,
        "profile": "imu-source-loss-after-8s-immediate-v2",
    },
    "native_restart": {
        "run_id": "native-restart-retry-seed-27312",
        "seed": 27312,
        "profile": "native-restart-after-8s-failclosed-v2",
    },
}


def load(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def json_lines(path):
    result = []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                result.append(json.loads(line))
    return result


def require(condition, message, failures):
    if not condition:
        failures.append(message)


def _common(root, plan, failures):
    study = root / plan["run_id"]
    manifest_path = study / "study-manifest.json"
    manifest = load(manifest_path)
    completion = load(study / "physical-completion.json")
    capture = study / "capture-v1"
    result = load(capture / "result.json")
    fault = load(capture / "shadow/health-fault-result.json")
    health = load(capture / "shadow/health-result.json")
    supervisor = load(capture / "supervisor.json")
    events = json_lines(capture / "events.jsonl")
    heartbeats = [row for row in events if row.get("kind") == "heartbeat"]
    require(manifest.get("schema") == "openvins-health-physical-fault-preflight-v1", "manifest schema", failures)
    require(manifest.get("run_id") == plan["run_id"], "run identity", failures)
    require(manifest.get("seed") == plan["seed"], "seed identity", failures)
    require(manifest.get("health_fault_profile") == plan["profile"], "fault profile", failures)
    require(manifest.get("fault_result_viewed") is False, "fault viewed before declaration", failures)
    require(manifest.get("test_set_tuning_allowed") is False, "test tuning allowed", failures)
    require(manifest.get("truth_used_online") is False, "truth used online", failures)
    require(manifest.get("odometry_published") is False, "odometry published", failures)
    require(manifest.get("armed") is False, "arming declared", failures)
    require(manifest.get("fusion_eligible") is False, "manifest fusion", failures)
    require(completion.get("capture_status") == "capture_failed", "capture did not fail closed", failures)
    require(completion.get("command_returncode") == 2, "capture return code", failures)
    require(completion.get("outcome_matches_expectation") is True, "outcome expectation mismatch", failures)
    require(completion.get("resources_after") == [], "resources retained", failures)
    require(completion.get("fusion_eligible") is False, "completion fusion", failures)
    require(result.get("status") == "capture_failed", "result status", failures)
    require(result.get("simulation_seed", {}).get("seed") == plan["seed"], "runtime seed", failures)
    require(result.get("simulation_seed", {}).get("applied_before_test_fixture") is True, "seed ordering", failures)
    require(result.get("health_fault_profile") == plan["profile"], "runtime fault profile", failures)
    require(result.get("eligible_for_px4_fusion") is False, "capture fusion", failures)
    require(result.get("px4_exit_code") == 0, "PX4 exit", failures)
    runtime = result.get("runtime_binding", {})
    require(runtime.get("declared_files_stable") is True, "runtime files drifted", failures)
    require(runtime.get("runtime_mapping_coverage_verified") is True, "runtime mapping incomplete", failures)
    require(runtime.get("errors") == [], "runtime binding errors", failures)
    require(runtime.get("runtime_closure_qualified") is False, "whole runtime overclaim", failures)
    writer = result.get("writer", {}).get("written", {})
    require(writer.get("imu", 0) > 0 and writer.get("rgb", 0) > 0 and writer.get("info", 0) > 0,
            "raw evidence missing", failures)
    ulogs = result.get("px4_ulogs", [])
    require(bool(ulogs) and all(row.get("valid_header") is True and row.get("bytes", 0) > 0 for row in ulogs),
            "ULog evidence missing", failures)
    require(bool(heartbeats) and all(type(row.get("base_mode")) is int and not row["base_mode"] & 128 for row in heartbeats),
            "armed or missing heartbeat", failures)
    cleanup = supervisor.get("cleanup", {})
    require(supervisor.get("worker_exit") == 2 and supervisor.get("capture_status") == "capture_failed",
            "supervisor outcome", failures)
    require(cleanup.get("group_absent") is True and cleanup.get("no_executing_members") is True,
            "owned group retained", failures)
    require(cleanup.get("errors") == [], "supervisor cleanup errors", failures)
    require(fault.get("fusion_eligible") is False and health.get("fusion_eligible") is False,
            "fault health fusion", failures)
    return study, result, fault, health


def audit(root):
    root = Path(root).resolve(strict=True)
    cohort_path = root / "fault-cohort-manifest.json"
    cohort = load(cohort_path)
    failures = []
    require(cohort.get("schema") == "openvins-health-physical-fault-cohort-preflight-v1", "cohort schema", failures)
    require(cohort.get("created_before_any_fault_result") is True, "cohort was not predeclared", failures)
    require(cohort.get("fault_result_viewed") is False, "cohort result viewed", failures)
    require(cohort.get("test_set_tuning_allowed") is False, "cohort tuning allowed", failures)
    require(cohort.get("truth_used_online") is False, "cohort truth used", failures)
    require(cohort.get("odometry_published") is False, "cohort odometry", failures)
    require(cohort.get("fusion_eligible") is False, "cohort fusion", failures)
    rows = cohort.get("runs")
    require(type(rows) is list and len(rows) == 2, "cohort runs", failures)
    indexed = {row.get("role"): row for row in rows} if type(rows) is list else {}
    require(set(indexed) == set(EXPECTED), "cohort roles", failures)
    for role, plan in EXPECTED.items():
        if role not in indexed:
            continue
        stored = indexed[role]
        manifest_path = root / plan["run_id"] / "study-manifest.json"
        require(stored.get("run_id") == plan["run_id"] and stored.get("seed") == plan["seed"],
                role + " cohort identity", failures)
        current = file_record(manifest_path)
        require(stored.get("manifest", {}).get("sha256") == current.get("sha256")
                and stored.get("manifest", {}).get("bytes") == current.get("bytes"),
                role + " preflight manifest drift", failures)
    _, source_result, source, source_health = _common(root, EXPECTED["source_loss"], failures)
    _, restart_result, restart, restart_health = _common(root, EXPECTED["native_restart"], failures)
    source_events = json_lines(root / EXPECTED["source_loss"]["run_id"] / "capture-v1/shadow/health-fault-events.jsonl")
    require([row.get("event") for row in source_events] == ["source_loss_started", "source_loss_detected"],
            "source loss event sequence", failures)
    require(source.get("failure") == "source_loss:imu" and source.get("dropped_source_records", 0) >= 1,
            "source loss disposition", failures)
    require(source.get("restart_count") == 0 and len(source.get("sessions", [])) == 1,
            "source loss sessions", failures)
    require(source.get("health_last", {}).get("quality") == -1
            and source.get("health_last", {}).get("reasons") == ["source_failure"],
            "source loss health", failures)
    require(source_health.get("last_quality") == -1
            and source_health.get("last_health", {}).get("reasons") == ["source_failure"],
            "source loss terminal health", failures)
    require(any("source_loss:imu" in error for error in source_result.get("errors", [])),
            "source loss capture reason", failures)
    source_sessions = source.get("sessions", [])
    require(bool(source_sessions) and source_sessions[0].get("native", {}).get("exit") == 0
            and source_sessions[0].get("native", {}).get("accepted", 0) > 0
            and source_sessions[0].get("shadow", {}).get("failure") is None,
            "source loss native evidence", failures)
    restart_events = json_lines(root / EXPECTED["native_restart"]["run_id"] / "capture-v1/shadow/health-fault-events.jsonl")
    require([row.get("event") for row in restart_events] == ["native_session_replaced"],
            "restart event sequence", failures)
    sessions = restart.get("sessions", [])
    require(restart.get("failure") is None and restart.get("restart_count") == 1 and len(sessions) == 2,
            "restart disposition", failures)
    require([row.get("session_id") for row in sessions] == ["fault-session-0", "fault-session-1"],
            "restart session identities", failures)
    require(all(row.get("native", {}).get("exit") == 0 and row.get("native", {}).get("accepted", 0) > 0
                and row.get("shadow", {}).get("failure") is None for row in sessions),
            "restart native sessions", failures)
    require(restart.get("health_last", {}).get("quality") == 0
            and restart.get("health_last", {}).get("reset_total") == 1,
            "restart transition health", failures)
    require(restart_health.get("session_count") == 2 and restart_health.get("reset_total") == 1
            and restart_health.get("reset_counter") == 1 and restart_health.get("last_quality") == -1,
            "restart terminal health", failures)
    readiness = restart_result.get("readiness", {})
    require(readiness.get("session_id") == "fault-session-1" and readiness.get("reset_total") == 1
            and readiness.get("session_replacements") == 1 and readiness.get("fusion_eligible") is False,
            "restart readiness transition", failures)
    require(any("readiness lost after anchor" in error for error in restart_result.get("errors", [])),
            "restart fail-closed reason", failures)
    owned = restart_result.get("runtime_binding", {}).get("owned_phases", {})
    require(owned.get("openvins-restart") == ["ready", "prestop"], "restart runtime mapping", failures)
    if failures:
        raise ValueError("invalid physical fault evidence: " + "; ".join(failures))
    return {
        "schema": "openvins-health-physical-fault-audit-v1",
        "root": str(root),
        "cohort_manifest": file_record(cohort_path),
        "source_loss_qualified": True,
        "native_restart_reset_qualified": True,
        "qualified": True,
        "truth_used_online": False,
        "odometry_published": False,
        "armed": False,
        "fusion_eligible": False,
        "hardware_covariance_calibrated": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.root)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
