import hashlib
import json
import warnings
import zipfile

import pytest

PREFIX = "estimator-heartbeat-routing-dev-1701/"
AUDIT_MEMBER = "results/estimator-heartbeat-routing-dev-1701/study-v11-audit.json"


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf8")


def correction_audit():
    return {
        "schema": "estimator-heartbeat-routing-audit-v1",
        "classification": "estimator-ack-routing-heartbeat-without-sample-refusal",
        "failure_classification_qualified": True,
        "failures": [],
        "claims": {
            "fruit_fly_learning_failure": False,
            "training_failure": False,
            "vio_accuracy_evaluated": False,
            "physical_retry_performed": False,
            "fusion_eligible": False,
        },
    }


def correction(tmp_path, *, archived=None, bad_hash=False, duplicate=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    audit = tmp_path / "study-v11-audit.json"
    archive = tmp_path / "estimator-heartbeat-routing-dev-1701.zip"
    current = correction_audit()
    write(audit, current)
    payload = json.dumps(current if archived is None else archived).encode()
    member = {
        "path": AUDIT_MEMBER,
        "bytes": len(payload),
        "sha256": "0" * 64 if bad_hash else hashlib.sha256(payload).hexdigest(),
    }
    manifest = {
        "schema": "flydrones-evidence-manifest-v1",
        "stage": "estimator-heartbeat-routing-dev-1701",
        "member_count": 1,
        "members": [member],
    }
    with zipfile.ZipFile(archive, "x") as package:
        package.writestr(PREFIX + AUDIT_MEMBER, payload)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                package.writestr(PREFIX + AUDIT_MEMBER, payload)
        package.writestr(PREFIX + "manifest.json", json.dumps(manifest))
    return audit, archive


def failed_attempt(tmp_path):
    capture = tmp_path / "capture-v1"
    capture.mkdir()
    result = {
        "status": "capture_failed",
        "end_sim_ns": 1_520_000_000,
        "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
        "source_fanout": {
            "failure": "ValueError('invalid source sample')",
            "last_disposition": {
                "source_sequence": 426,
                "dispositions": {"shadow": "attempted", "readiness": "not_attempted"},
            },
            "heartbeat": {"observed": 1, "reconciled": 0},
        },
        "motion": {"anchor_ns": None, "active_steps": 0, "support_steps": 0, "recorded_commands": 0},
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "px4_exit_code": 0,
        "px4_ulogs": [{"valid_header": True, "bytes": 10}],
    }
    write(capture / "result.json", result)
    audit = tmp_path / "attempt-audit.json"
    write(audit, correction_audit())
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


def test_current_heartbeat_correction_shape_is_accepted(tmp_path):
    from tools.benchmark.estimator_heartbeat_retry_preflight import validate_correction

    audit, archive = correction(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checked, actual = validate_correction(audit, archive, expected_archive_sha256=digest)
    assert checked["failure_classification_qualified"] is True
    assert actual == digest


@pytest.mark.parametrize(
    "mutation",
    ["name", "digest", "audit", "member", "duplicate", "claim", "classification"],
)
def test_heartbeat_correction_drift_is_rejected(tmp_path, mutation):
    from tools.benchmark.estimator_heartbeat_retry_preflight import validate_correction

    audit, archive = correction(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if mutation == "name":
        changed = archive.with_name("other.zip")
        archive.rename(changed)
        archive = changed
    elif mutation == "digest":
        digest = "0" * 64
    elif mutation == "audit":
        audit, archive = correction(tmp_path / "changed", archived={**correction_audit(), "failures": ["bad"]})
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif mutation == "member":
        audit, archive = correction(tmp_path / "changed", bad_hash=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif mutation == "duplicate":
        audit, archive = correction(tmp_path / "changed", duplicate=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    else:
        value = json.loads(audit.read_text())
        if mutation == "claim":
            value["claims"]["fusion_eligible"] = True
        else:
            value["classification"] = "other"
        write(audit, value)
    with pytest.raises(ValueError, match="heartbeat correction not qualified"):
        validate_correction(audit, archive, expected_archive_sha256=digest)


@pytest.mark.parametrize(
    "mutation",
    ["status", "time", "cause", "route", "heartbeat", "motion", "fusion", "ulog", "audit", "destination", "resources"],
)
def test_failed_heartbeat_attempt_drift_is_rejected(tmp_path, mutation):
    from tools.benchmark.estimator_heartbeat_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    if mutation in {"status", "time", "cause", "route", "heartbeat", "motion", "fusion", "ulog"}:
        value = json.loads((capture / "result.json").read_text())
        if mutation == "status":
            value["status"] = "completed"
        elif mutation == "time":
            value["end_sim_ns"] += 1
        elif mutation == "cause":
            value["source_fanout"]["failure"] = "other"
        elif mutation == "route":
            value["source_fanout"]["last_disposition"]["dispositions"]["readiness"] = "attempted"
        elif mutation == "heartbeat":
            value["source_fanout"]["heartbeat"]["reconciled"] = 1
        elif mutation == "motion":
            value["motion"]["active_steps"] = 1
        elif mutation == "fusion":
            value["eligible_for_px4_fusion"] = True
        else:
            value["px4_ulogs"] = []
        write(capture / "result.json", value)
    elif mutation == "audit":
        value = json.loads(audit.read_text())
        value["classification"] = "other"
        write(audit, value)
    else:
        value = json.loads(completion.read_text())
        if mutation == "destination":
            value["destination"] = str(tmp_path / "other")
        else:
            value["resources_after"] = ["px4"]
        write(completion, value)
    with pytest.raises(ValueError, match="failed heartbeat attempt not qualified"):
        validate_failed_attempt(capture, audit, completion)


def test_current_failed_heartbeat_attempt_shape_is_accepted(tmp_path):
    from tools.benchmark.estimator_heartbeat_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    result, checked = validate_failed_attempt(capture, audit, completion)
    assert result["end_sim_ns"] == 1_520_000_000
    assert checked["classification"] == "estimator-ack-routing-heartbeat-without-sample-refusal"


def test_wsl_and_windows_destination_spellings_match(tmp_path):
    from tools.benchmark.estimator_heartbeat_retry_preflight import _same_destination

    capture = tmp_path / "capture-v1"
    windows = str(capture.resolve()).replace("\\", "/")
    drive, rest = windows.split(":", 1)
    assert _same_destination(f"/mnt/{drive.lower()}{rest}", capture)
    assert not _same_destination(f"/mnt/{drive.lower()}{rest}-other", capture)


def test_prepare_refuses_competing_resources_before_inputs(tmp_path):
    from tools.benchmark.estimator_heartbeat_retry_preflight import prepare

    with pytest.raises(ValueError, match="competing resources"):
        prepare(
            tmp_path / "output",
            source=tmp_path / "missing-source",
            source_audit=tmp_path / "missing-source-audit",
            failed_capture=tmp_path / "missing-capture",
            attempt_audit=tmp_path / "missing-attempt-audit",
            completion=tmp_path / "missing-completion",
            correction_audit=tmp_path / "missing-correction-audit",
            correction_archive=tmp_path / "missing-correction-archive",
            capture_script=tmp_path / "missing-script",
            python=tmp_path / "missing-python",
            resources=[{"pid": 7, "kind": "px4"}],
        )


def test_member_gate_accepts_only_complete_known_startup_set():
    from tools.benchmark.audit_estimator_heartbeat_retry_preflight import member_set_accepted
    from tools.benchmark.estimator_heartbeat_retry_preflight import OUTPUT_NAMES

    base = set(OUTPUT_NAMES)
    startup = {
        "startup-preflight-v1",
        "startup-preflight-v1.supervisor-environment.json",
        "startup-preflight-v1.supervisor-events.jsonl",
    }
    assert member_set_accepted(base, after_startup_preflight=False)
    assert member_set_accepted(base | startup, after_startup_preflight=True)
    assert not member_set_accepted(base | {"capture-v1"}, after_startup_preflight=False)
    assert not member_set_accepted(base | {"startup-preflight-v1"}, after_startup_preflight=True)
