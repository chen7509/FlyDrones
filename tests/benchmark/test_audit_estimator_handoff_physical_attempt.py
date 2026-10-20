import hashlib
import json

import pytest


def dump(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def fixture(tmp_path):
    capture = tmp_path / "capture-v1"
    shadow = capture / "shadow"
    shadow.mkdir(parents=True)
    cause = "ValueError(\"ValueError('uninitialized acknowledgement has state')\")"
    pending = {
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
    result = {
        "status": "capture_failed",
        "end_sim_ns": 2_320_000_000,
        "estimator_run": True,
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "px4_exit_code": 0,
        "native": {"exit": 0, "failure": None, "fusion_eligible": False},
        "motion": {"active_steps": 0, "support_steps": 0, "absolute_impulse_ns": 0.0,
                   "anchor_ns": None, "recorded_commands": 0},
        "source_fanout": {
            "committed": 649,
            "failure": cause,
            "last_disposition": {"source_sequence": 649, "dispositions": {
                "shadow": "attempted", "readiness": "not_attempted"}, "failure": cause},
            "heartbeat": {"observed": 1, "reconciled": 1, "pending": [], "failure": None},
            "fusion_eligible": False,
        },
        "readiness": {"first_internal": None, "latest_internal": None, "failure":
                      "ValueError('uninitialized acknowledgement has state')", "fusion_eligible": False},
        "shadow": {"failure": None, "last_delivery_acks": [pending], "fusion_eligible": False},
        "runtime_binding": {"runtime_mapping_coverage_verified": True,
                            "runtime_closure_qualified": False},
        "px4_ulogs": [],
    }
    ulog = capture / "flight.ulg"
    ulog.write_bytes(b"ULog-test")
    item = {"path": "flight.ulg", "bytes": ulog.stat().st_size,
            "sha256": hashlib.sha256(ulog.read_bytes()).hexdigest(), "valid_header": True}
    result["px4_ulogs"] = [item]
    dump(capture / "result.json", result)
    dump(capture / "px4-ulog-manifest.json", {"schema": "flydrones-px4-ulog-capture-v1", "logs": [item]})
    dump(capture / "supervisor.json", {
        "capture_status": "capture_failed", "worker_exit": 2,
        "cleanup": {"no_executing_members": True, "group_absent": True,
                    "sigkill_dispatched": False, "all_descendant_cleanup_qualified": False,
                    "final_snapshot": {"members": []}},
    })
    (capture / "motion-force.jsonl").write_bytes(b"")
    (capture / "estimator-readiness.jsonl").write_bytes(b"")
    (shadow / "native-acks.jsonl").write_text(json.dumps(pending) + "\n", encoding="utf-8")
    (capture / "events.jsonl").write_text(json.dumps({"source_sequence": 649, "kind": "rgb",
                                                       "sample_ns": 2_300_000_000}) + "\n", encoding="utf-8")
    (capture / "source-fanout.jsonl").write_text(json.dumps({
        "event": "source_delivery", "source_sequence": 649,
        "dispositions": {"shadow": "attempted", "readiness": "not_attempted"},
        "failure": cause,
    }) + "\n", encoding="utf-8")
    completion = tmp_path / "completion.json"
    dump(completion, {"returncode": 2, "destination_exists": True, "physical_run": True,
                      "resources_after": []})
    return capture, completion


def test_handoff_attempt_audit_classifies_closed_refusal(tmp_path):
    from tools.benchmark.audit_estimator_handoff_physical_attempt import FALSE_CLAIMS, audit

    capture, completion = fixture(tmp_path)
    result = audit(capture, completion)
    assert result["failure_evidence_qualified"] is True
    assert result["classification"] == "openvins-synchronous-initializer-handoff-contract-refusal"
    assert result["heartbeat_correction_physically_verified"] is True
    assert result["pending_handoff"]["initializer_time_s"] == 1.304
    assert all(result[key] is False for key in FALSE_CLAIMS)


@pytest.mark.parametrize("field", ["cause", "motion", "ack", "ulog", "cleanup", "resources"])
def test_handoff_attempt_audit_rejects_evidence_drift(tmp_path, field):
    from tools.benchmark.audit_estimator_handoff_physical_attempt import audit

    capture, completion = fixture(tmp_path)
    if field in {"cause", "motion", "ack"}:
        result = json.loads((capture / "result.json").read_text())
        if field == "cause":
            result["source_fanout"]["failure"] = "other"
        elif field == "motion":
            result["motion"]["active_steps"] = 1
        else:
            result["shadow"]["last_delivery_acks"][0]["state_time_s"] = 1.305
        dump(capture / "result.json", result)
    elif field == "ulog":
        (capture / "flight.ulg").write_bytes(b"changed")
    elif field == "cleanup":
        supervisor = json.loads((capture / "supervisor.json").read_text())
        supervisor["cleanup"]["group_absent"] = False
        dump(capture / "supervisor.json", supervisor)
    else:
        dump(completion, {"returncode": 2, "destination_exists": True,
                          "physical_run": True, "resources_after": ["px4"]})
    assert audit(capture, completion)["failure_evidence_qualified"] is False
