import hashlib
import json
import warnings
import zipfile

import pytest

PAIR_AUDIT_MEMBER = "results/causal-pair-stage-dev-1701/fixed-replay-audit-v2.json"


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def pair_audit():
    return {
        "schema": "causal-pair-stage-fixed-replay-audit-v1",
        "failures": [],
        "fixed_replay_qualified": True,
        "physical_execution_qualified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def pair_correction(tmp_path, *, archived_audit=None, bad_member_hash=False, duplicate=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    audit = tmp_path / "fixed-replay-audit-v2.json"
    archive = tmp_path / "causal-pair-stage-dev-1701.zip"
    value = pair_audit()
    write(audit, value)
    archived = value if archived_audit is None else archived_audit
    payload = json.dumps(archived).encode()
    member = {
        "path": PAIR_AUDIT_MEMBER,
        "bytes": len(payload),
        "sha256": "0" * 64 if bad_member_hash else hashlib.sha256(payload).hexdigest(),
    }
    manifest = {
        "schema": "causal-pair-stage-evidence-v1",
        "member_count_without_manifest": 1,
        "members": [member],
        "qualifications": {
            "fixed_input_pair_stage": True,
            "physical_execution": False,
            "runtime_closure": False,
            "vio_accuracy": False,
            "estimator_health": False,
            "fusion_eligible": False,
            "flight_ready": False,
        },
    }
    with zipfile.ZipFile(archive, "x") as package:
        package.writestr(PAIR_AUDIT_MEMBER, payload)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                package.writestr(PAIR_AUDIT_MEMBER, payload)
        package.writestr("manifest.json", json.dumps(manifest))
    return audit, archive


def failed_attempt(tmp_path):
    capture = tmp_path / "capture-v1"
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
            "schema": "causal-deadline-physical-attempt-audit-v2",
            "failures": [],
            "failure_classification_qualified": True,
            "classification": "causal-input-same-stamp-pair-source-arrival-deadline-refusal",
            "fruit_fly_policy_evaluated": False,
            "timing_ns": {
                "limit": 250_000_000,
                "same_sample_pair_gap": 258_765_752,
                "excess": 8_765_752,
            },
            "physical_execution_qualified": False,
            "runtime_mapping_coverage_verified": False,
            "runtime_closure_qualified": False,
            "vio_accuracy_qualified": False,
            "estimator_health_qualified": False,
            "fusion_eligible": False,
            "flight_ready": False,
        },
    )
    completion = tmp_path / "completion.json"
    write(
        completion,
        {
            "destination": str(capture.resolve()),
            "physical_run": True,
            "returncode": 2,
            "resources_after": [],
        },
    )
    return capture, audit, completion


def test_current_pair_correction_shape_is_accepted(tmp_path):
    from tools.benchmark.causal_pair_retry_preflight import validate_pair_correction

    audit, archive = pair_correction(tmp_path)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    result, digest = validate_pair_correction(audit, archive, expected_archive_sha256=expected)
    assert result["fixed_replay_qualified"] is True
    assert digest == expected


@pytest.mark.parametrize(
    "field",
    ["schema", "failure", "qualified", "claim", "archive-name", "archive-hash", "archive-audit", "archive-manifest", "duplicate"],
)
def test_pair_correction_rejects_drift(tmp_path, field):
    from tools.benchmark.causal_pair_retry_preflight import validate_pair_correction

    audit, archive = pair_correction(tmp_path)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    value = json.loads(audit.read_text())
    if field == "schema":
        value["schema"] = "wrong"
    elif field == "failure":
        value["failures"] = ["bad"]
    elif field == "qualified":
        value["fixed_replay_qualified"] = False
    elif field == "claim":
        value["fusion_eligible"] = True
    elif field == "archive-name":
        renamed = archive.with_name("other.zip")
        archive.rename(renamed)
        archive = renamed
    elif field == "archive-hash":
        expected = "0" * 64
    elif field == "archive-audit":
        audit, archive = pair_correction(tmp_path / "changed", archived_audit={**pair_audit(), "fixed_replay_qualified": False})
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif field == "archive-manifest":
        audit, archive = pair_correction(tmp_path / "changed", bad_member_hash=True)
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    else:
        audit, archive = pair_correction(tmp_path / "changed", duplicate=True)
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    write(audit, value)
    with pytest.raises(ValueError, match="pair correction not qualified"):
        validate_pair_correction(audit, archive, expected_archive_sha256=expected)


@pytest.mark.parametrize("field", ["status", "time", "cause", "motion", "fusion", "schema", "class", "timing", "claim", "destination", "resources"])
def test_failed_pair_attempt_rejects_drift(tmp_path, field):
    from tools.benchmark.causal_pair_retry_preflight import validate_failed_attempt

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
    elif field in {"schema", "class", "timing", "claim"}:
        value = json.loads(audit.read_text())
        if field == "schema":
            value["schema"] = "wrong"
        elif field == "class":
            value["classification"] = "other"
        elif field == "timing":
            value["timing_ns"]["excess"] += 1
        else:
            value["vio_accuracy_qualified"] = True
        write(audit, value)
    else:
        value = json.loads(completion.read_text())
        if field == "destination":
            value["destination"] = str(tmp_path / "other")
        else:
            value["resources_after"] = ["px4"]
        write(completion, value)
    with pytest.raises(ValueError, match="failed attempt evidence not qualified"):
        validate_failed_attempt(capture, audit, completion)


def test_current_failed_pair_attempt_shape_is_accepted(tmp_path):
    from tools.benchmark.causal_pair_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    result, check = validate_failed_attempt(capture, audit, completion)
    assert result["status"] == "capture_failed"
    assert check["classification"] == "causal-input-same-stamp-pair-source-arrival-deadline-refusal"


def test_prepare_refuses_competing_resources_before_reading_inputs(tmp_path):
    from tools.benchmark.causal_pair_retry_preflight import prepare

    with pytest.raises(ValueError, match="competing resources"):
        prepare(
            tmp_path / "output",
            source=tmp_path / "missing-source",
            source_audit=tmp_path / "missing-audit",
            failed_capture=tmp_path / "missing-capture",
            attempt_audit=tmp_path / "missing-attempt",
            completion=tmp_path / "missing-completion",
            pair_audit=tmp_path / "missing-pair-audit",
            pair_archive=tmp_path / "missing-pair-archive",
            capture_script=tmp_path / "missing-capture-script",
            python=tmp_path / "missing-python",
            resources=[{"pid": 7, "kind": "px4"}],
        )
