import json
import shutil
from pathlib import Path

import pytest

from tools.benchmark.audit_source_watchdog_retry_preflight import (
    claims_closed,
    future_destination_available,
)
from tools.benchmark.source_watchdog_retry_preflight import (
    prepare,
    validate_correction,
    validate_source,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v18"
AUDIT = ROOT / "results/causal-pair-sim-time-physical-boundary-dev-1701/startup-cohort-audit.json"
COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v9-completion.json"
BOUNDARY_AUDIT = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v9-boundary-audit.json"
ARCHIVE = ROOT / "evidence/source-watchdog-startup-cohort-dev-1701.zip"
IMPLEMENTATION = ROOT / "tools/benchmark/openvins_online_shadow.py"


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_frozen_failure_and_correction_match_current_bytes():
    source, manifest, audit = validate_source(SOURCE, AUDIT, COMPLETION, BOUNDARY_AUDIT)
    correction = validate_correction(AUDIT, ARCHIVE, IMPLEMENTATION)
    assert source == SOURCE.resolve()
    assert manifest["schema"] == "causal-pair-simulation-time-physical-retry-preflight-v1"
    assert audit["classification"] == "startup-readiness-before-fresh-source-cohort"
    assert correction["candidate_fresh_cohort_qualified"] is True


@pytest.mark.parametrize("fault", ["archive", "audit", "implementation"])
def test_correction_drift_refuses(tmp_path, fault):
    audit = tmp_path / "audit.json"
    archive = tmp_path / ARCHIVE.name
    implementation = tmp_path / "openvins_online_shadow.py"
    shutil.copy2(AUDIT, audit)
    shutil.copy2(ARCHIVE, archive)
    shutil.copy2(IMPLEMENTATION, implementation)
    if fault == "archive":
        archive.write_bytes(archive.read_bytes() + b"drift")
    elif fault == "audit":
        value = json.loads(audit.read_text(encoding="utf-8"))
        value["candidate_fresh_cohort_qualified"] = False
        write_json(audit, value)
    else:
        implementation.write_text(implementation.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    with pytest.raises(ValueError, match="correction"):
        validate_correction(audit, archive, implementation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", "wrong"),
        ("imu_age_at_failure_ns", 2_079_562_029),
        ("failure_after_ready_ns", 254_628),
        ("next_imu_after_failure_ns", 713_793),
        ("next_fresh_cohort_span_ns", 265_527_094),
        ("fruit_fly_policy_failure", True),
        ("fusion_eligible", True),
    ],
)
def test_source_audit_drift_refuses(tmp_path, field, value):
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    audit[field] = value
    path = tmp_path / "audit.json"
    write_json(path, audit)
    with pytest.raises(ValueError, match="source failure"):
        validate_source(SOURCE, path, COMPLETION, BOUNDARY_AUDIT)


def test_prepare_refuses_resources_and_existing_output(tmp_path):
    common = dict(
        output=tmp_path / "study-v19",
        source=SOURCE,
        source_audit=AUDIT,
        completion=COMPLETION,
        boundary_audit=BOUNDARY_AUDIT,
        correction_archive=ARCHIVE,
        capture_script=ROOT / "tools/benchmark/capture_disarmed_sensors.py",
        python=Path("/usr/bin/python3"),
    )
    with pytest.raises(ValueError, match="competing resources"):
        prepare(**common, resources=[{"pid": 1}])
    common["output"].mkdir()
    with pytest.raises(FileExistsError):
        prepare(**common, resources=[])


def test_overclaim_and_existing_destination_are_rejected(tmp_path):
    claim_names = (
        "physical_execution_qualified",
        "runtime_mapping_coverage_verified",
        "runtime_closure_qualified",
        "vio_accuracy_qualified",
        "estimator_health_qualified",
        "fusion_eligible",
        "flight_ready",
    )
    manifest = {key: False for key in claim_names}
    authorization = dict(manifest)
    assert claims_closed(manifest, authorization)
    manifest["fusion_eligible"] = True
    assert not claims_closed(manifest, authorization)

    root = tmp_path / "study"
    root.mkdir()
    destination = root / "capture-v1"
    candidate = {"future_destination": str(destination.resolve())}
    assert future_destination_available(root, candidate)
    destination.mkdir()
    assert not future_destination_available(root, candidate)
