import json

import pytest


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def correction(tmp_path):
    audit = tmp_path / "correction-audit.json"
    archive = tmp_path / "correction.zip"
    write(
        audit,
        {
            "schema": "causal-wall-deadline-audit-v3",
            "failures": [],
            "fixed_input_qualified": True,
            "limits_changed": False,
            "physical_run_performed": False,
            "physical_execution_qualified": False,
            "runtime_mapping_coverage_verified": False,
            "runtime_closure_qualified": False,
            "vio_accuracy_qualified": False,
            "estimator_health_qualified": False,
            "fusion_eligible": False,
            "flight_ready": False,
        },
    )
    archive.write_bytes(b"sealed")
    return audit, archive


def failed_attempt(tmp_path):
    capture = tmp_path / "capture"
    capture.mkdir()
    write(
        capture / "result.json",
        {
            "status": "capture_failed",
            "end_sim_ns": 10_000_000,
            "source_fanout": {"failure": "pending input exceeded wall wait"},
            "motion": {"active_steps": 0, "support_steps": 0, "absolute_impulse_ns": 0.0},
            "eligible_for_vio_input": False,
            "eligible_for_px4_fusion": False,
            "px4_ulogs": [],
        },
    )
    audit = tmp_path / "attempt-audit.json"
    write(
        audit,
        {
            "failures": [],
            "failure_evidence_qualified": True,
            "classification": "causal-input-wall-deadline-platform-scheduling-refusal",
            "fruit_fly_policy_failure": False,
        },
    )
    completion = tmp_path / "completion.json"
    write(completion, {"returncode": 2, "resources_after": []})
    return capture, audit, completion


@pytest.mark.parametrize("field", ["schema", "failure", "qualified", "limit", "physical", "claim", "archive"])
def test_correction_validation_rejects_drift(tmp_path, field):
    from tools.benchmark.causal_deadline_retry_preflight import validate_correction

    audit, archive = correction(tmp_path)
    value = json.loads(audit.read_text())
    if field == "schema":
        value["schema"] = "wrong"
    elif field == "failure":
        value["failures"] = ["bad"]
    elif field == "qualified":
        value["fixed_input_qualified"] = False
    elif field == "limit":
        value["limits_changed"] = True
    elif field == "physical":
        value["physical_run_performed"] = True
    elif field == "claim":
        value["fusion_eligible"] = True
    else:
        archive.write_bytes(b"")
    write(audit, value)
    with pytest.raises(ValueError, match="not qualified"):
        validate_correction(audit, archive)


@pytest.mark.parametrize("field", ["status", "time", "cause", "motion", "fusion", "audit", "class", "resources"])
def test_failed_attempt_validation_rejects_drift(tmp_path, field):
    from tools.benchmark.causal_deadline_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    if field in {"status", "time", "cause", "motion", "fusion"}:
        value = json.loads((capture / "result.json").read_text())
        if field == "status":
            value["status"] = "completed"
        elif field == "time":
            value["end_sim_ns"] = 11_000_000
        elif field == "cause":
            value["source_fanout"]["failure"] = "other"
        elif field == "motion":
            value["motion"]["active_steps"] = 1
        else:
            value["eligible_for_px4_fusion"] = True
        write(capture / "result.json", value)
    elif field in {"audit", "class"}:
        value = json.loads(audit.read_text())
        if field == "audit":
            value["failures"] = ["bad"]
        else:
            value["classification"] = "other"
        write(audit, value)
    else:
        write(completion, {"returncode": 2, "resources_after": ["px4"]})
    with pytest.raises(ValueError, match="not qualified"):
        validate_failed_attempt(capture, audit, completion)


def test_current_evidence_shapes_are_accepted(tmp_path):
    from tools.benchmark.causal_deadline_retry_preflight import validate_correction, validate_failed_attempt

    correction_audit, archive = correction(tmp_path)
    capture, attempt_audit, completion = failed_attempt(tmp_path)
    assert validate_correction(correction_audit, archive)[0]["fixed_input_qualified"] is True
    assert validate_failed_attempt(capture, attempt_audit, completion)[0]["status"] == "capture_failed"
