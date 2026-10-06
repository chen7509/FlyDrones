import json
import shutil
from pathlib import Path

import pytest

from tools.benchmark.heartbeat_sim_time_retry_preflight import prepare, validate_correction

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "results/heartbeat-simulation-time-readiness-dev-1701/fixed-evidence-audit.json"
ARCHIVE = ROOT / "evidence/heartbeat-simulation-time-readiness-dev-1701.zip"
IMPLEMENTATION = ROOT / "tools/benchmark/readiness_anchor.py"


def test_frozen_correction_archive_matches_current_implementation():
    result = validate_correction(AUDIT, ARCHIVE, IMPLEMENTATION)
    assert result["fixed_evidence_ready"]
    assert result["simulation_silence_refused"]
    assert result["timeout_increased"] is False


@pytest.mark.parametrize("fault", ["archive", "audit", "implementation"])
def test_correction_drift_refuses(tmp_path, fault):
    audit = tmp_path / "audit.json"
    archive = tmp_path / ARCHIVE.name
    implementation = tmp_path / "readiness_anchor.py"
    shutil.copy2(AUDIT, audit)
    shutil.copy2(ARCHIVE, archive)
    shutil.copy2(IMPLEMENTATION, implementation)
    if fault == "archive":
        archive.write_bytes(archive.read_bytes() + b"drift")
    elif fault == "audit":
        value = json.loads(audit.read_text())
        value["simulation_silence_refused"] = False
        audit.write_text(json.dumps(value))
    else:
        implementation.write_text(implementation.read_text() + "\n# drift\n")
    with pytest.raises(ValueError):
        validate_correction(audit, archive, implementation)


def test_prepare_refuses_resources_and_existing_output(tmp_path):
    common = dict(
        output=tmp_path / "study",
        source=tmp_path / "source",
        source_audit=tmp_path / "source-audit.json",
        completion=tmp_path / "completion.json",
        correction_audit=AUDIT,
        correction_archive=ARCHIVE,
        capture_script=tmp_path / "capture.py",
        python=tmp_path / "python",
    )
    with pytest.raises(ValueError, match="competing resources"):
        prepare(**common, resources=[{"pid": 1}])
    common["output"].mkdir()
    with pytest.raises(FileExistsError):
        prepare(**common, resources=[])
