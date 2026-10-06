import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.benchmark.test_openvins_lazy_runtime_prepare import (
    PASS,
    fake_auditor,
    lazy_package,
    source_package,
    write_json,
)


def package(tmp_path, monkeypatch):
    from tools.benchmark import openvins_lazy_runtime_prepare as prepare

    source = source_package(tmp_path)
    lazy, audit_path, archive, _ = lazy_package(tmp_path)
    monkeypatch.setattr(prepare, "PACKAGE_ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    output = tmp_path / "prepared"
    prepare.prepare_study(
        output, source_study=source, lazy_study=lazy, lazy_audit=audit_path,
        package_archive=archive, capture_script=Path("/study/capture.py"),
        python=Path("/usr/bin/python3"), resources=[], closure_auditor=fake_auditor,
        policy_validator=lambda doc: doc,
    )
    return output, source, lazy, audit_path, archive


def run_audit(output):
    from tools.benchmark.audit_openvins_lazy_runtime_prepare import audit

    return audit(output, closure_auditor=fake_auditor, policy_validator=lambda doc: doc)


def test_audit_accepts_exact_prepare_only_package(tmp_path, monkeypatch):
    output, *_ = package(tmp_path, monkeypatch)
    result = run_audit(output)
    assert result["prepare_qualified"] is True
    assert result["physical_execution_qualified"] is False
    assert result["runtime_closure_qualified"] is False


@pytest.mark.parametrize("failure", [
    "extra", "manifest", "binding", "contract", "lazy-contract", "source", "capture",
])
def test_audit_rejects_output_source_or_claim_drift(tmp_path, monkeypatch, failure):
    output, source, lazy, _audit_path, _archive = package(tmp_path, monkeypatch)
    if failure == "extra":
        (output / "extra").write_text("x")
    elif failure == "capture":
        (output / "capture-v1").mkdir()
    elif failure == "source":
        (lazy / "probe" / "native.log").write_text("drift")
    else:
        names = {"manifest": "study-manifest.json", "binding": "runtime-binding-v3.json",
                 "contract": "execution-contract.json", "lazy-contract": "lazy-runtime-contract.json"}
        path = output / names[failure]
        row = json.loads(path.read_text())
        if failure == "manifest":
            row["fusion_eligible"] = True
        elif failure == "binding":
            row["inventory"].pop("runtime:openvins-lazy-contract")
        elif failure == "contract":
            row["wall_budget_s"] = 301
        else:
            row["trigger"] = "any"
        write_json(path, row)
    result = run_audit(output)
    assert result["prepare_qualified"] is False
    assert result["failures"]


def test_audit_rejects_stored_lazy_audit_overclaim(tmp_path, monkeypatch):
    output, _source, _lazy, audit_path, _archive = package(tmp_path, monkeypatch)
    row = copy.deepcopy(PASS)
    row["runtime_closure_qualified"] = True
    write_json(audit_path, row)
    result = run_audit(output)
    assert result["prepare_qualified"] is False
