"""Audit the immutable study-v15 heartbeat wall-age physical refusal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest

CLASSIFICATION = "journaled-heartbeat-wall-age-slow-simulation-refusal"
MOTION_FAILURE = "ValueError('readiness lost after anchor')"
FALSE_CLAIMS = (
    "complete_physical_execution_qualified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "ekf2_injection_qualified",
    "flight_ready",
    "fruit_fly_policy_failure",
)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"object required: {path}")
    return value


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(capture, completion):
    capture = Path(capture).resolve(strict=True)
    completion = Path(completion).resolve(strict=True)
    failures: list[str] = []

    def require(value, label):
        if not value:
            failures.append(label)

    wall_age = wall_excess = sim_age = None
    first_public = None
    ulog_sha256 = None
    try:
        result = _read(capture / "result.json")
        anchor = _read(capture / "readiness-anchor.json")
        manifest = _read(capture / "px4-ulog-manifest.json")
        supervisor = _read(capture / "supervisor.json")
        completed = _read(completion)
        heartbeats = _jsonl(capture / "heartbeat-observations.jsonl")
        readiness = _jsonl(capture / "estimator-readiness.jsonl")
        events = _jsonl(capture / "events.jsonl")
        journal = _jsonl(capture.parent / "capture-v1.supervisor-events.jsonl")

        require(result.get("status") == "capture_failed", "capture status")
        require(result.get("end_sim_ns") == 4_650_000_000, "failure simulation time")
        require(result.get("estimator_run") is True, "estimator started")
        require(result.get("px4_exit_code") == 0, "PX4 exit")
        require(result.get("native", {}).get("exit") == 0, "native exit")
        require(result.get("native", {}).get("failure") is None, "native failure absent")
        require(result.get("shadow", {}).get("failure") is None, "shadow failure absent")
        require(result.get("eligible_for_vio_input") is False, "VIO gate closed")
        require(result.get("eligible_for_px4_fusion") is False, "fusion gate closed")

        motion = result.get("motion", {})
        require(motion.get("failure") == MOTION_FAILURE, "motion refusal")
        require(motion.get("last_ns") == 4_647_000_000, "last motion step")
        require(motion.get("anchor_ns") == 2_620_000_000, "motion anchor")
        require(motion.get("support_steps") == motion.get("recorded_commands") == 2027,
                "support command count")
        require(motion.get("active_steps") == 0, "lateral force not reached")
        require(motion.get("full_profile_requested") is False, "incomplete profile retained")
        require(motion.get("eligible_for_px4_fusion") is False, "motion fusion closed")
        require(anchor.get("selected_sim_ns") == 2_420_000_000, "anchor selection")
        require(anchor.get("anchor_ns") == motion.get("anchor_ns"), "anchor identity")
        limit = anchor.get("profile", {}).get("heartbeat_max_age_ns")
        require(limit == 2_000_000_000, "heartbeat wall-age limit")

        observed = [row for row in heartbeats if row.get("event") == "heartbeat_observed"]
        reconciled = [row for row in heartbeats if row.get("event") == "heartbeat_reconciled"]
        require(len(observed) == len(reconciled) == 3, "heartbeat journal counts")
        require([row.get("observation_sequence") for row in observed] == [0, 1, 2],
                "heartbeat observation order")
        require([row.get("observation_sequence") for row in reconciled] == [0, 1, 2],
                "heartbeat reconciliation order")
        last = observed[-1].get("original", {}) if observed else {}
        require(last.get("system_id") == 9 and last.get("base_mode") == 29,
                "unarmed heartbeat identity")
        require(last.get("observed_sim_ns") == 3_679_000_000, "last heartbeat simulation time")
        require(last.get("arrival_monotonic_ns") == 254_526_101_224, "last heartbeat wall time")
        source = result.get("readiness", {}).get("source", {})
        high_water = source.get("clock_high_water_ns")
        if type(high_water) is int and type(last.get("arrival_monotonic_ns")) is int:
            wall_age = high_water - last["arrival_monotonic_ns"]
            wall_excess = wall_age - limit if type(limit) is int else None
        if type(motion.get("last_ns")) is int and type(last.get("observed_sim_ns")) is int:
            sim_age = motion["last_ns"] - last["observed_sim_ns"]
        require(wall_age == 2_000_774_305, "heartbeat wall age")
        require(wall_excess == 774_305, "heartbeat wall excess")
        require(sim_age == 968_000_000, "heartbeat simulation age")
        require(source.get("failure") is None, "source did not latch an intrinsic failure")
        heartbeat = result.get("source_fanout", {}).get("heartbeat", {})
        require(heartbeat.get("observed") == heartbeat.get("reconciled") == 3,
                "heartbeat fanout counts")
        require(heartbeat.get("pending") == [] and heartbeat.get("failure") is None,
                "heartbeat lane otherwise healthy")
        require("pre-step source failure" in str(result.get("source_fanout", {}).get("failure")),
                "fanout stopped from motion refusal")
        require(bool(events) and events[-1].get("kind") == "imu"
                and events[-1].get("source_sequence") == 1306
                and events[-1].get("sample_ns") == 4_648_000_000,
                "no later heartbeat was emitted")

        require(bool(readiness), "estimator readiness records")
        require(all(row.get("event") == "estimator_internal_ready" for row in readiness),
                "readiness record schema")
        require(all(row.get("internal_initialized") is True for row in readiness),
                "internal initialization persisted")
        require(all(row.get("truth_used") is False and row.get("fusion_eligible") is False
                    for row in readiness), "truth and fusion remained closed")
        public = [row for row in readiness if row.get("public_initialized") is True]
        first_public = public[0] if public else None
        require(readiness[0].get("sample_ns") == 2_400_000_000
                and readiness[0].get("public_initialized") is False,
                "first internal handoff")
        require(first_public is not None and first_public.get("sample_ns") == 3_300_000_000,
                "first public initialization")
        require(readiness[-1].get("sample_ns") == 4_600_000_000
                and readiness[-1].get("public_initialized") is True,
                "fresh public state before refusal")
        result_readiness = result.get("readiness", {})
        require(result_readiness.get("failure") is None and result_readiness.get("truth_used") is False,
                "estimator readiness had no intrinsic failure")

        logs = manifest.get("logs", [])
        require(manifest.get("schema") == "flydrones-px4-ulog-capture-v1" and len(logs) == 1,
                "single retained ULog")
        require(result.get("px4_ulogs") == logs, "ULog manifest identity")
        if len(logs) == 1:
            log = logs[0]
            path = capture / log.get("path", "")
            require(path.is_file() and log.get("valid_header") is True, "valid ULog path")
            if path.is_file():
                data = path.read_bytes()
                ulog_sha256 = hashlib.sha256(data).hexdigest()
                require(len(data) == log.get("bytes") and ulog_sha256 == log.get("sha256"),
                        "ULog content identity")

        binding = result.get("runtime_binding", {})
        require(binding.get("runtime_mapping_coverage_verified") is True, "runtime mapping coverage")
        require(binding.get("runtime_closure_qualified") is False, "runtime closure remains false")
        cleanup = supervisor.get("cleanup", {})
        require(supervisor.get("capture_status") == "capture_failed" and supervisor.get("worker_exit") == 2,
                "supervisor failure retained")
        require(cleanup.get("events") == journal, "supervisor journal identity")
        require(cleanup.get("no_executing_members") is True and cleanup.get("group_absent") is True,
                "owned group drained")
        require(cleanup.get("sigkill_dispatched") is False
                and cleanup.get("final_snapshot", {}).get("members") == [],
                "owned group signal evidence")
        require(cleanup.get("all_descendant_cleanup_qualified") is False,
                "descendant scope not overclaimed")
        require(completed.get("returncode") == 2 and completed.get("destination_exists") is True
                and completed.get("physical_run") is True, "dispatch completion")
        require(completed.get("resources_after") == [], "post-run resources empty")
    except Exception as exc:
        failures.append("audit:" + repr(exc))

    return {
        "schema": "openvins-handoff-physical-attempt-audit-v1",
        "failures": failures,
        "failure_evidence_qualified": not failures,
        "classification": CLASSIFICATION,
        "scope": "wall-clock heartbeat freshness refusal during slow physical simulation; not VIO accuracy, training, flight or swarm behavior",
        "heartbeat_wall_age_ns": wall_age,
        "heartbeat_wall_excess_ns": wall_excess,
        "heartbeat_sim_age_ns": sim_age,
        "public_initialization_physically_observed": not failures and first_public is not None,
        "public_initialization_sample_ns": None if first_public is None else first_public.get("sample_ns"),
        "ulog_sha256": ulog_sha256,
        "runtime_mapping_coverage_verified": not failures,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.completion)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["failure_evidence_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
