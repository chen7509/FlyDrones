"""Audit study-v18's source-watchdog transition before a fresh startup cohort."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest

CLASSIFICATION = "startup-readiness-before-fresh-source-cohort"


def _read(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("object required")
    return value


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def audit(capture, dispatch, completion):
    capture = Path(capture).resolve(strict=True)
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    imu_age_at_failure = failure_after_ready = next_imu_after_failure = cohort_span = None
    candidate = False
    try:
        result = _read(capture / "result.json")
        supervisor = _read(capture / "supervisor.json")
        dispatched = _read(dispatch)
        completed = _read(completion)
        events = _rows(capture / "events.jsonl")
        fanout = _rows(capture / "source-fanout.jsonl")
        health = result["source_health"]
        require(
            result.get("status") == "capture_failed"
            and result.get("end_sim_ns") == 10_000_000
            and result.get("source_fanout", {}).get("failure") == "TimeoutError('source silence: imu')",
            "terminal source refusal",
        )
        require(
            [row.get("kind") for row in events] == ["imu", "info", "depth", "rgb", "imu", "imu"],
            "source prefix",
        )
        first_imu, info, _depth, rgb, next_imu, _last_imu = events
        refusal = next(row for row in fanout if row.get("event") == "source_refusal")
        latched = refusal["failure_latched_ns"]
        require(refusal.get("failure") == "TimeoutError('source silence: imu')", "fanout refusal")
        require(
            health.get("startup_timeout_ns") == 10_000_000_000
            and health.get("operational_timeout_ns") == 2_000_000_000
            and health.get("ready_ns") == rgb["arrival_monotonic_ns"],
            "watchdog limits and ready",
        )
        imu_age_at_failure = latched - first_imu["arrival_monotonic_ns"]
        failure_after_ready = latched - health["ready_ns"]
        next_imu_after_failure = next_imu["arrival_monotonic_ns"] - latched
        cohort_values = [info["arrival_monotonic_ns"], rgb["arrival_monotonic_ns"], next_imu["arrival_monotonic_ns"]]
        cohort_span = max(cohort_values) - min(cohort_values)
        candidate = (
            imu_age_at_failure == 2_079_562_030
            and failure_after_ready == 254_629
            and next_imu_after_failure == 713_794
            and cohort_span == 265_527_095
            and next_imu["arrival_monotonic_ns"] - health["started_ns"] < health["startup_timeout_ns"]
            and cohort_span < health["operational_timeout_ns"]
        )
        require(candidate, "fresh startup cohort counterfactual")
        require(
            result.get("motion", {}).get("recorded_commands") == 0
            and result.get("motion", {}).get("support_steps") == 0
            and result.get("motion", {}).get("anchor_ns") is None,
            "motion not started",
        )
        require(
            result.get("readiness", {}).get("first_internal") is None
            and result.get("px4_ulogs") == []
            and result.get("eligible_for_vio_input") is False
            and result.get("eligible_for_px4_fusion") is False,
            "downstream gates closed",
        )
        cleanup = supervisor.get("cleanup", {})
        require(
            result.get("px4_exit_code") == -9
            and cleanup.get("sigkill_dispatched") is False
            and cleanup.get("group_absent") is True
            and cleanup.get("no_executing_members") is True,
            "cleanup distinction",
        )
        require(
            dispatched.get("schema") == "causal-pair-sim-time-physical-dispatch-v1"
            and dispatched.get("single_actual_attempt") is True
            and dispatched.get("boundary_audit", {}).get("boundary_qualified") is True,
            "dispatch boundary",
        )
        require(
            completed.get("command_returncode") == 2
            and completed.get("launcher_error") is None
            and completed.get("destination_exists") is True
            and completed.get("resources_after") == [],
            "completion resources",
        )
    except Exception as exc:
        failures.append("audit:" + repr(exc))
    return {
        "schema": "source-watchdog-startup-cohort-audit-v1",
        "failures": failures,
        "failure_evidence_qualified": not failures,
        "classification": CLASSIFICATION,
        "imu_age_at_failure_ns": imu_age_at_failure,
        "failure_after_ready_ns": failure_after_ready,
        "next_imu_after_failure_ns": next_imu_after_failure,
        "next_fresh_cohort_span_ns": cohort_span,
        "candidate_fresh_cohort_qualified": candidate,
        "physical_retry_performed": True,
        "complete_physical_execution_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "fruit_fly_policy_failure": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--dispatch", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.dispatch, args.completion)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["failure_evidence_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
