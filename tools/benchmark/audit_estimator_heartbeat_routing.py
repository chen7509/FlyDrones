"""Audit the immutable study-v11 heartbeat-routing refusal without replaying physics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CLASSIFICATION = "estimator-ack-routing-heartbeat-without-sample-refusal"
EXPECTED_ERROR = "invalid source sample"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf8"))


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line]


def audit(capture: Path) -> dict:
    capture = capture.resolve()
    result = _read_json(capture / "result.json")
    events = _read_jsonl(capture / "events.jsonl")
    fanout_rows = _read_jsonl(capture / "source-fanout.jsonl")
    supervisor = _read_json(capture / "supervisor.json")
    ulogs = _read_json(capture / "px4-ulog-manifest.json")
    failures = []

    source = next((row for row in events if row.get("source_sequence") == 426), None)
    refusal = next(
        (
            row
            for row in fanout_rows
            if row.get("source_sequence") == 426 and row.get("event") == "source_delivery"
        ),
        None,
    )
    checks = {
        "capture_failed": result.get("status") == "capture_failed",
        "profile_exact": result.get("source_fanout_profile") == "ready-shadow-heartbeat-estimator-v1",
        "source_426_is_unsampled_heartbeat": isinstance(source, dict)
        and source.get("kind") == "heartbeat"
        and "sample_ns" not in source,
        "source_426_identity": isinstance(source, dict)
        and source.get("system_id") == 9
        and source.get("base_mode") == 29,
        "refusal_after_shadow_before_readiness": isinstance(refusal, dict)
        and refusal.get("dispositions") == {"shadow": "attempted", "readiness": "not_attempted"}
        and EXPECTED_ERROR in str(refusal.get("failure")),
        "result_matches_refusal": EXPECTED_ERROR in str(result.get("source_fanout", {}).get("failure"))
        and result.get("source_fanout", {}).get("last_disposition", {}).get("source_sequence") == 426,
        "heartbeat_observed_not_reconciled": result.get("source_fanout", {}).get("heartbeat", {}).get("observed") == 1
        and result.get("source_fanout", {}).get("heartbeat", {}).get("reconciled") == 0,
        "no_motion_or_force": result.get("motion", {}).get("anchor_ns") is None
        and result.get("motion", {}).get("active_steps") == 0
        and result.get("motion", {}).get("support_steps") == 0
        and result.get("motion", {}).get("recorded_commands") == 0,
        "fusion_remained_blocked": result.get("eligible_for_px4_fusion") is False,
        "px4_exited_without_sigkill": result.get("px4_exit_code") == 0
        and supervisor.get("cleanup", {}).get("sigkill_dispatched") is False,
        "owned_group_reaped": supervisor.get("cleanup", {}).get("no_executing_members") is True
        and supervisor.get("cleanup", {}).get("group_absent") is True,
        "descendant_scope_not_overclaimed": supervisor.get("cleanup", {}).get("all_descendant_cleanup_qualified") is False,
        "ulog_retained": len(ulogs.get("logs", [])) == 1
        and ulogs["logs"][0].get("valid_header") is True
        and ulogs["logs"][0].get("bytes", 0) > 0,
    }
    if source is not None and refusal is not None:
        expected_hash = hashlib.sha256(json.dumps(source, sort_keys=True, allow_nan=False).encode()).hexdigest()
        checks["source_hash_matches"] = refusal.get("source_sha256") == expected_hash
    else:
        checks["source_hash_matches"] = False
    failures.extend(name for name, passed in checks.items() if not passed)
    return {
        "schema": "estimator-heartbeat-routing-audit-v1",
        "capture": str(capture),
        "classification": CLASSIFICATION if not failures else None,
        "failure_classification_qualified": not failures,
        "checks": checks,
        "failures": failures,
        "claims": {
            "fruit_fly_learning_failure": False,
            "training_failure": False,
            "vio_accuracy_evaluated": False,
            "physical_retry_performed": False,
            "fusion_eligible": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.capture)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf8")
    print(encoded, end="")
    raise SystemExit(0 if not result["failures"] else 2)


if __name__ == "__main__":
    main()
