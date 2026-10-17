import json
import shutil
from pathlib import Path

import pytest

from tools.benchmark.audit_causal_pair_sim_time_retry_preflight import (
    claims_closed,
    future_destination_available,
)
from tools.benchmark.causal_pair_sim_time_retry_preflight import (
    prepare,
    validate_correction,
    validate_source,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v16"
AUDIT = ROOT / "results/causal-pair-sim-time-dev-1701/study-v16-audit.json"
COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v8-completion.json"
ARCHIVE = ROOT / "evidence/causal-pair-sim-time-dev-1701.zip"
IMPLEMENTATION = ROOT / "tools/benchmark/openvins_causal_input.py"
STUDY = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v18"
STUDY_AUDIT = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-audit-v1.json"


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_frozen_source_and_correction_match_current_bytes():
    source, manifest, audit = validate_source(SOURCE, AUDIT, COMPLETION)
    correction = validate_correction(AUDIT, ARCHIVE, IMPLEMENTATION)
    assert source == SOURCE.resolve()
    assert manifest["schema"] == "heartbeat-simulation-time-physical-retry-preflight-v1"
    assert audit["classification"] == "camera-pair-wall-age-slow-simulation-refusal"
    assert correction["fixed_replay_camera_released"] is True
    assert correction["simulation_silence_refused"] is True


@pytest.mark.parametrize("fault", ["archive", "audit", "implementation"])
def test_correction_drift_refuses(tmp_path, fault):
    audit = tmp_path / "audit.json"
    archive = tmp_path / ARCHIVE.name
    implementation = tmp_path / "openvins_causal_input.py"
    shutil.copy2(AUDIT, audit)
    shutil.copy2(ARCHIVE, archive)
    shutil.copy2(IMPLEMENTATION, implementation)
    if fault == "archive":
        archive.write_bytes(archive.read_bytes() + b"drift")
    elif fault == "audit":
        value = json.loads(audit.read_text(encoding="utf-8"))
        value["fixed_replay_camera_released"] = False
        write_json(audit, value)
    else:
        implementation.write_text(implementation.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    with pytest.raises(ValueError, match="correction"):
        validate_correction(audit, archive, implementation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", "wrong"),
        ("pair_wall_age_ns", 355_099_343),
        ("idle_wall_age_ns", 294_079_877),
        ("pair_sim_age_ns", 1),
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
        validate_source(SOURCE, path, COMPLETION)


def test_prepare_refuses_resources_and_existing_output(tmp_path):
    common = dict(
        output=tmp_path / "study-v17",
        source=SOURCE,
        source_audit=AUDIT,
        completion=COMPLETION,
        correction_audit=AUDIT,
        correction_archive=ARCHIVE,
        capture_script=ROOT / "tools/benchmark/capture_disarmed_sensors.py",
        python=Path("/usr/bin/python3"),
    )
    with pytest.raises(ValueError, match="competing resources"):
        prepare(**common, resources=[{"pid": 1}])
    common["output"].mkdir()
    with pytest.raises(FileExistsError):
        prepare(**common, resources=[])


def test_generated_study_passes_independent_audit():
    result = json.loads(STUDY_AUDIT.read_text(encoding="utf-8"))
    assert result["failures"] == []
    assert result["prepare_qualified"] is True


def test_overclaim_and_existing_destination_are_explicitly_rejected(tmp_path):
    manifest = {key: False for key in (
        "physical_execution_qualified",
        "runtime_mapping_coverage_verified",
        "runtime_closure_qualified",
        "vio_accuracy_qualified",
        "estimator_health_qualified",
        "fusion_eligible",
        "flight_ready",
    )}
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
