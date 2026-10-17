"""Audit the immutable physical refusal at OpenVINS synchronous initializer handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest

CLASSIFICATION = "openvins-synchronous-initializer-handoff-contract-refusal"
CAUSE = "ValueError(\"ValueError('uninitialized acknowledgement has state')\")"
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


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(capture, completion):
    capture = Path(capture).resolve(strict=True)
    completion = Path(completion).resolve(strict=True)
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    pending = {}
    try:
        result = _read(capture / "result.json")
        manifest = _read(capture / "px4-ulog-manifest.json")
        supervisor = _read(capture / "supervisor.json")
        completed = _read(completion)
        events = _jsonl(capture / "events.jsonl")
        fanout = _jsonl(capture / "source-fanout.jsonl")
        native = _jsonl(capture / "shadow" / "native-acks.jsonl")

        require(result.get("status") == "capture_failed", "capture status")
        require(result.get("end_sim_ns") == 2_320_000_000, "failure simulation time")
        require(result.get("estimator_run") is True, "estimator started")
        require(result.get("source_fanout", {}).get("failure") == CAUSE, "fanout cause")
        last = result.get("source_fanout", {}).get("last_disposition", {})
        require(last.get("source_sequence") == 649 and last.get("failure") == CAUSE,
                "failure source identity")
        require(last.get("dispositions") == {"shadow": "attempted", "readiness": "not_attempted"},
                "partial fanout disposition")
        delivery = [row for row in fanout if row.get("event") == "source_delivery" and row.get("source_sequence") == 649]
        require(len(delivery) == 1 and delivery[0].get("failure") == CAUSE, "fanout journal evidence")
        source = [row for row in events if row.get("source_sequence") == 649]
        require(len(source) == 1 and source[0].get("kind") == "rgb" and source[0].get("sample_ns") == 2_300_000_000,
                "source event evidence")

        heartbeat = result.get("source_fanout", {}).get("heartbeat", {})
        require(heartbeat.get("observed") == heartbeat.get("reconciled") == 1,
                "heartbeat correction evidence")
        require(heartbeat.get("pending") == [] and heartbeat.get("failure") is None,
                "heartbeat health")

        pending = result.get("shadow", {}).get("last_delivery_acks", [{}])[-1]
        expected_pending = {
            "sequence": 600,
            "kind": "C",
            "sample_ns": 2_300_000_000,
            "internal_initialized": False,
            "public_initialized": False,
            "initializer_time_s": 1.304,
            "state_time_s": 1.304,
            "last_regular_update_s": -1,
            "zupt_flag_latched": False,
            "has_moved_since_zupt": False,
            "imu_state": None,
            "fusion_eligible": False,
            "quality": None,
            "reset_counter": None,
        }
        require(all(pending.get(key) == value for key, value in expected_pending.items()),
                "pending handoff acknowledgement")
        require(bool(native) and native[-1] == pending, "native acknowledgement identity")
        readiness = result.get("readiness", {})
        require(readiness.get("first_internal") is None and readiness.get("latest_internal") is None,
                "pending handoff did not grant readiness")
        require((capture / "estimator-readiness.jsonl").stat().st_size == 0,
                "readiness journal remained empty")

        motion = result.get("motion", {})
        require(motion.get("active_steps") == motion.get("support_steps") == motion.get("recorded_commands") == 0,
                "motion remained zero")
        require(motion.get("absolute_impulse_ns") == 0.0 and motion.get("anchor_ns") is None,
                "force remained zero")
        require((capture / "motion-force.jsonl").stat().st_size == 0, "force log empty")
        require(result.get("eligible_for_vio_input") is False and result.get("eligible_for_px4_fusion") is False,
                "downstream gates closed")
        require(result.get("native", {}).get("exit") == 0 and result.get("native", {}).get("failure") is None,
                "native exit")
        require(result.get("px4_exit_code") == 0, "PX4 exit")

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
                require(len(data) == log.get("bytes") and hashlib.sha256(data).hexdigest() == log.get("sha256"),
                        "ULog content identity")

        binding = result.get("runtime_binding", {})
        require(binding.get("runtime_mapping_coverage_verified") is True, "runtime mapping coverage")
        require(binding.get("runtime_closure_qualified") is False, "runtime closure remains false")
        cleanup = supervisor.get("cleanup", {})
        require(supervisor.get("capture_status") == "capture_failed" and supervisor.get("worker_exit") == 2,
                "supervisor failure retained")
        require(cleanup.get("no_executing_members") is True and cleanup.get("group_absent") is True,
                "owned group drained")
        require(cleanup.get("sigkill_dispatched") is False and cleanup.get("final_snapshot", {}).get("members") == [],
                "owned group signal evidence")
        require(cleanup.get("all_descendant_cleanup_qualified") is False,
                "descendant scope not overclaimed")
        require(completed.get("returncode") == 2 and completed.get("destination_exists") is True
                and completed.get("physical_run") is True, "dispatch completion")
        require(completed.get("resources_after") == [], "post-run resources empty")
    except Exception as exc:
        failures.append("audit:" + repr(exc))

    return {
        "schema": "estimator-handoff-physical-attempt-audit-v1",
        "failures": failures,
        "failure_evidence_qualified": not failures,
        "classification": CLASSIFICATION,
        "scope": "pre-motion harness contract refusal; not VIO accuracy, training, flight or swarm behavior",
        "heartbeat_correction_physically_verified": not failures,
        "pending_handoff": {key: pending.get(key) for key in (
            "sequence", "sample_ns", "initializer_time_s", "state_time_s", "internal_initialized",
            "public_initialized", "last_regular_update_s", "imu_state")},
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
