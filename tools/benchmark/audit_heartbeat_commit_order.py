"""Audit the immutable study-v19 heartbeat / source commit ordering failure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_ULOG_SHA256 = "5b39597ebbbbe8a6458ae1ac1df059ae950285d80913309dfe4284e1b010c70f"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(capture: Path, completion: Path):
    capture = Path(capture)
    completion = Path(completion)
    result = _load(capture / "result.json")
    completed = _load(completion)
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    errors = "\n".join(result.get("errors", []))
    readiness = result.get("readiness", {})
    source = readiness.get("source", {})
    records = source.get("records", {})
    current_imu = records.get("imu", {}).get("observed_sim_ns")
    latest_heartbeat = records.get("heartbeat", {}).get("observed_sim_ns")

    events = [json.loads(line) for line in (capture / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    heartbeats = [row for row in events if row.get("kind") == "heartbeat"]
    check(len(heartbeats) == 2, "expected exactly two committed heartbeat events")
    previous_heartbeat = heartbeats[0].get("observed_sim_ns") if heartbeats else None
    latest_arrival = heartbeats[-1].get("arrival_monotonic_ns") if heartbeats else None
    pre_arrived = [
        row
        for row in events
        if row.get("kind") == "imu"
        and row.get("arrival_monotonic_ns", 2**63) < (latest_arrival or 0)
        and row.get("observed_sim_ns", 0) > (current_imu or 0)
        and row.get("recorded_monotonic_ns", 0) > records.get("heartbeat", {}).get("recorded_monotonic_ns", 0)
    ]

    check(result.get("status") == "capture_failed", "capture status was not capture_failed")
    check(result.get("end_sim_ns") == 2_620_000_000, "unexpected immutable end simulation time")
    check("future heartbeat simulation clock" in errors, "missing future-heartbeat failure")
    check(source.get("failure") == "future heartbeat simulation clock", "readiness failure mismatch")
    check(current_imu == 2_604_000_000, "committed IMU reference mismatch")
    check(latest_heartbeat == 2_614_000_000, "latest heartbeat reference mismatch")
    check(previous_heartbeat == 1_616_000_000, "previous heartbeat reference mismatch")
    check([row.get("observed_sim_ns") for row in pre_arrived] == [2_608_000_000, 2_612_000_000], "pre-arrived IMU evidence mismatch")
    check(completed.get("physical_run") is True, "completion did not record physical run")
    check(completed.get("command_returncode") == 2 and completed.get("launcher_returncode") == 2, "completion return code mismatch")
    check(completed.get("destination_exists") is True, "capture destination missing")
    check(completed.get("resources_after") == [], "owned resources remained")

    motion = result.get("motion", {})
    check(motion.get("anchor_ns") == 2_619_000_000, "anchor evidence mismatch")
    check(motion.get("support_steps") == 0 and motion.get("active_steps") == 0, "force steps were applied")
    check(motion.get("recorded_commands") == 0, "force commands were recorded")
    check(motion.get("signed_impulse_ns") == 0 and motion.get("absolute_impulse_ns") == 0, "nonzero impulse recorded")
    first_internal = readiness.get("first_internal", {})
    check(first_internal.get("internal_initialized") is True, "internal initialization missing")
    check(first_internal.get("public_initialized") is False, "public initialization unexpectedly true")
    check(result.get("px4_exit_code") == 0, "PX4 exit was not clean")
    check(result.get("runtime_binding", {}).get("runtime_mapping_coverage_verified") is True, "runtime mapping coverage missing")
    check(result.get("runtime_binding", {}).get("runtime_closure_qualified") is False, "runtime closure unexpectedly qualified")

    ulogs_value = result.get("px4_ulogs", [])
    ulogs = ulogs_value.get("logs", []) if isinstance(ulogs_value, dict) else ulogs_value
    check(len(ulogs) == 1, "expected exactly one ULog")
    if ulogs:
        ulog = ulogs[0]
        path = capture / ulog.get("path", "")
        check(ulog.get("valid_header") is True, "ULog header invalid")
        check(ulog.get("sha256") == EXPECTED_ULOG_SHA256, "ULog manifest hash mismatch")
        check(path.is_file() and _sha256(path) == EXPECTED_ULOG_SHA256, "ULog file hash mismatch")

    return {
        "schema": "heartbeat-commit-order-audit-v1",
        "failures": failures,
        "classification": "heartbeat-observation-ahead-of-committed-imu" if not failures else "unqualified",
        "heartbeat_lead_ns": latest_heartbeat - current_imu if isinstance(latest_heartbeat, int) and isinstance(current_imu, int) else None,
        "previous_heartbeat_age_ns": current_imu - previous_heartbeat if isinstance(previous_heartbeat, int) and isinstance(current_imu, int) else None,
        "pre_arrived_imu_times_ns": [row["observed_sim_ns"] for row in pre_arrived],
        "pre_arrived_imu_source_sequences": [row["source_sequence"] for row in pre_arrived],
        "fruit_fly_policy_failure": False,
        "fusion_qualified": False,
        "physical_rerun_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--completion", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.capture, args.completion)
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    raise SystemExit(0 if not result["failures"] else 2)


if __name__ == "__main__":
    main()
