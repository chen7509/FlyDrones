import hashlib
import json
import warnings
import zipfile

import pytest

PREFIX = "openvins-initializer-handoff-contract-dev-1701/"
AUDIT_MEMBER = "results/openvins-initializer-handoff-contract-dev-1701/physical-attempt-audit.json"


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf8")


def attempt_audit():
    return {
        "schema": "estimator-handoff-physical-attempt-audit-v1",
        "failures": [],
        "failure_evidence_qualified": True,
        "classification": "openvins-synchronous-initializer-handoff-contract-refusal",
        "heartbeat_correction_physically_verified": True,
        "pending_handoff": {
            "sequence": 600,
            "sample_ns": 2_300_000_000,
            "initializer_time_s": 1.304,
            "state_time_s": 1.304,
            "internal_initialized": False,
            "public_initialized": False,
            "last_regular_update_s": -1,
            "imu_state": None,
        },
        "runtime_mapping_coverage_verified": True,
        "complete_physical_execution_qualified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "ekf2_injection_qualified": False,
        "flight_ready": False,
        "fruit_fly_policy_failure": False,
    }


def correction(tmp_path, *, archived=None, bad_hash=False, duplicate=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    audit = tmp_path / "physical-attempt-audit.json"
    archive = tmp_path / "openvins-initializer-handoff-contract-dev-1701.zip"
    current = attempt_audit()
    write(audit, current)
    payload = json.dumps(current if archived is None else archived).encode()
    member = {"path": AUDIT_MEMBER, "bytes": len(payload),
              "sha256": "0" * 64 if bad_hash else hashlib.sha256(payload).hexdigest()}
    manifest = {
        "schema": "openvins-initializer-handoff-contract-evidence-v1",
        "stage": "openvins-initializer-handoff-contract-dev-1701",
        "member_count": 1,
        "claims": {
            "physical_attempt_immutable": True,
            "physical_retry_during_correction": False,
            "failure_evidence_qualified": True,
            "heartbeat_correction_physically_verified": True,
            "complete_physical_execution_qualified": False,
            "vio_accuracy_qualified": False,
            "fusion_eligible": False,
            "flight_ready": False,
        },
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
    cause = "ValueError(\"ValueError('uninitialized acknowledgement has state')\")"
    pending = {
        "sequence": 600, "kind": "C", "sample_ns": 2_300_000_000,
        "internal_initialized": False, "public_initialized": False,
        "initializer_time_s": 1.304, "state_time_s": 1.304,
        "last_regular_update_s": -1, "zupt_flag_latched": False,
        "has_moved_since_zupt": False, "imu_state": None,
        "fusion_eligible": False, "quality": None, "reset_counter": None,
    }
    result = {
        "status": "capture_failed", "end_sim_ns": 2_320_000_000,
        "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
        "source_fanout": {
            "failure": cause,
            "last_disposition": {"source_sequence": 649, "dispositions": {
                "shadow": "attempted", "readiness": "not_attempted"}},
            "heartbeat": {"observed": 1, "reconciled": 1, "pending": [], "failure": None},
        },
        "shadow": {"last_delivery_acks": [pending]},
        "readiness": {"first_internal": None, "latest_internal": None},
        "motion": {"anchor_ns": None, "active_steps": 0, "support_steps": 0,
                   "recorded_commands": 0, "absolute_impulse_ns": 0.0},
        "eligible_for_vio_input": False, "eligible_for_px4_fusion": False,
        "px4_exit_code": 0, "native": {"exit": 0, "failure": None},
        "px4_ulogs": [{"valid_header": True, "bytes": 10}],
        "runtime_binding": {"runtime_mapping_coverage_verified": True,
                            "runtime_closure_qualified": False},
    }
    write(capture / "result.json", result)
    audit = tmp_path / "attempt-audit.json"
    write(audit, attempt_audit())
    completion = tmp_path / "completion.json"
    write(completion, {"destination": str(capture.resolve()), "physical_run": True,
                       "returncode": 2, "resources_after": []})
    return capture, audit, completion


def test_current_handoff_correction_shape_is_accepted(tmp_path):
    from tools.benchmark.openvins_handoff_retry_preflight import validate_correction

    audit, archive = correction(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checked, actual = validate_correction(audit, archive, expected_archive_sha256=digest)
    assert checked["failure_evidence_qualified"] is True
    assert actual == digest


@pytest.mark.parametrize("mutation", ["name", "digest", "audit", "member", "duplicate", "claim", "classification"])
def test_handoff_correction_drift_is_rejected(tmp_path, mutation):
    from tools.benchmark.openvins_handoff_retry_preflight import validate_correction

    audit, archive = correction(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if mutation == "name":
        changed = archive.with_name("other.zip")
        archive.rename(changed)
        archive = changed
    elif mutation == "digest":
        digest = "0" * 64
    elif mutation == "audit":
        audit, archive = correction(tmp_path / "changed", archived={**attempt_audit(), "failures": ["bad"]})
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
            value["fusion_eligible"] = True
        else:
            value["classification"] = "other"
        write(audit, value)
    with pytest.raises(ValueError, match="handoff correction not qualified"):
        validate_correction(audit, archive, expected_archive_sha256=digest)


@pytest.mark.parametrize("mutation", ["status", "time", "cause", "route", "heartbeat", "ack", "motion", "fusion", "ulog", "runtime", "audit", "destination", "resources"])
def test_failed_handoff_attempt_drift_is_rejected(tmp_path, mutation):
    from tools.benchmark.openvins_handoff_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    if mutation in {"status", "time", "cause", "route", "heartbeat", "ack", "motion", "fusion", "ulog", "runtime"}:
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
            value["source_fanout"]["heartbeat"]["reconciled"] = 0
        elif mutation == "ack":
            value["shadow"]["last_delivery_acks"][0]["state_time_s"] = 1.305
        elif mutation == "motion":
            value["motion"]["active_steps"] = 1
        elif mutation == "fusion":
            value["eligible_for_px4_fusion"] = True
        elif mutation == "ulog":
            value["px4_ulogs"] = []
        else:
            value["runtime_binding"]["runtime_mapping_coverage_verified"] = False
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
    with pytest.raises(ValueError, match="failed handoff attempt not qualified"):
        validate_failed_attempt(capture, audit, completion)


def test_current_failed_handoff_attempt_shape_is_accepted(tmp_path):
    from tools.benchmark.openvins_handoff_retry_preflight import validate_failed_attempt

    capture, audit, completion = failed_attempt(tmp_path)
    result, checked = validate_failed_attempt(capture, audit, completion)
    assert result["end_sim_ns"] == 2_320_000_000
    assert checked["classification"] == "openvins-synchronous-initializer-handoff-contract-refusal"


def test_prepare_refuses_competing_resources_before_inputs(tmp_path):
    from tools.benchmark.openvins_handoff_retry_preflight import prepare

    with pytest.raises(ValueError, match="competing resources"):
        prepare(output=tmp_path / "output", source=tmp_path / "missing", failed_capture=tmp_path / "capture",
                attempt_audit=tmp_path / "audit", completion=tmp_path / "completion",
                correction_archive=tmp_path / "archive", capture_script=tmp_path / "capture.py",
                python=tmp_path / "python", resources=[{"pid": 7, "kind": "px4"}])


def test_authorization_separates_source_mapping_evidence_from_new_claims():
    from tools.benchmark.openvins_handoff_retry_preflight import _authorization_claims

    claims = _authorization_claims(source_runtime_mapping_coverage_verified=True)
    assert claims["source_runtime_mapping_coverage_verified"] is True
    assert claims["runtime_mapping_coverage_verified"] is False


def test_member_gate_accepts_only_complete_known_startup_set():
    from tools.benchmark.audit_openvins_handoff_retry_preflight import member_set_accepted
    from tools.benchmark.openvins_handoff_retry_preflight import OUTPUT_NAMES

    base = set(OUTPUT_NAMES)
    startup = {"startup-preflight-v1", "startup-preflight-v1.supervisor-environment.json",
               "startup-preflight-v1.supervisor-events.jsonl"}
    assert member_set_accepted(base, after_startup_preflight=False)
    assert member_set_accepted(base | startup, after_startup_preflight=True)
    assert not member_set_accepted(base | {"capture-v1"}, after_startup_preflight=False)
    assert not member_set_accepted(base | {"startup-preflight-v1"}, after_startup_preflight=True)
