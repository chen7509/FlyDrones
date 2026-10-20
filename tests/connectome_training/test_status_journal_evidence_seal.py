"""Evidence sealer import and integrity checks without publishing an archive."""

import subprocess
import sys
from pathlib import Path

import pytest

from tools.connectome import seal_status_journal_evidence as subject


def test_direct_script_imports_without_project_pythonpath():
    root = Path(__file__).resolve().parents[2]
    script = root / "tools/connectome/seal_status_journal_evidence.py"
    command = [sys.executable, "-I", "-c",
               "import runpy; runpy.run_path(" + repr(str(script)) + ", run_name='import_only')"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


def test_raw_case_mismatch_blocks_seal(monkeypatch):
    cases = {name: {"journal_sha256": digest}
             for name, digest in subject.EXPECTED_JOURNAL_SHA.items()}
    monkeypatch.setattr(subject, "_audit_case", lambda name: {
        **cases[name], "journal_sha256": "0" * 64 if name == "normal" else cases[name]["journal_sha256"],
    })
    monkeypatch.setattr(subject, "_json", lambda _path: {"independent_cdr_parity": True,
                                                        "samples": 3,
                                                        "unavailable_ratios": ["vel_test_ratio"]})
    with pytest.raises(ValueError, match="raw synthetic case"):
        subject._check_synthetic_raw({"cases": cases,
                                      "cdr_parity": {"independent_cdr_parity": True,
                                                     "samples": 3,
                                                     "unavailable_ratios": ["vel_test_ratio"]}})


def test_output_parent_junction_refused_before_write(monkeypatch):
    output = subject.ROOT / "evidence" / "unused-status-test.zip"
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction",
                        lambda path: path == output.parent or original(path))
    with pytest.raises(ValueError, match="linked output directory"):
        subject._validate_output_parent(output)
