import copy
import json
import os
import shutil
from pathlib import Path

import pytest

import tools.benchmark.causal_pair_sim_time_physical_boundary as boundary_module
from tools.benchmark.audit_causal_pair_sim_time_physical_boundary import audit_boundary
from tools.benchmark.causal_pair_sim_time_physical_boundary import _require_audits, _verify_archive, build_boundary

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v18"
PACKAGE_AUDIT = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-audit-v3-after-startup.json"
STARTUP_AUDIT = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-startup-audit-v1.json"
STARTUP_DISPATCH = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v10-dispatch.json"
STARTUP_COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v10-completion.json"
ARCHIVE = ROOT / "evidence/causal-pair-sim-time-retry-preflight-dev-1701.zip"


def make_boundary(tmp_path):
    head_file = tmp_path / "head.txt"
    head_file.write_text("a" * 40 + "\n", encoding="utf-8")
    return build_boundary(
        study=STUDY,
        package_audit=PACKAGE_AUDIT,
        startup_audit=STARTUP_AUDIT,
        startup_dispatch=STARTUP_DISPATCH,
        startup_completion=STARTUP_COMPLETION,
        evidence_archive=ARCHIVE,
        expected_head="a" * 40,
        head_file=head_file,
        dispatch=tmp_path / "dispatch.json",
        completion=tmp_path / "completion.json",
        output=tmp_path / "output.txt",
        resources=[],
    )


@pytest.mark.skipif(os.name == "nt", reason="the declared physical package uses WSL absolute paths")
def test_real_inputs_build_closed_one_shot_boundary(tmp_path):
    value = make_boundary(tmp_path)
    assert value["schema"] == "causal-pair-sim-time-physical-boundary-v1"
    assert value["head"] == "a" * 40
    assert value["destination"].endswith("/study-v18/capture-v1")
    assert value["resources_before"] == []
    assert value["single_actual_attempt"] is True
    assert value["physical_run"] is True
    assert value["physical_execution_qualified"] is False
    assert "--startup-preflight" not in value["command"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda kw: kw.update(expected_head="b" * 40), "committed head"),
        (lambda kw: kw.update(resources=["px4"]), "competing resources"),
        (lambda kw: kw["dispatch"].write_text("used"), "one-shot output exists"),
    ],
)
def test_builder_rejects_head_resources_and_reuse(tmp_path, mutation, match):
    head_file = tmp_path / "head.txt"
    head_file.write_text("a" * 40 + "\n")
    kwargs = dict(
        study=STUDY,
        package_audit=PACKAGE_AUDIT,
        startup_audit=STARTUP_AUDIT,
        startup_dispatch=STARTUP_DISPATCH,
        startup_completion=STARTUP_COMPLETION,
        evidence_archive=ARCHIVE,
        expected_head="a" * 40,
        head_file=head_file,
        dispatch=tmp_path / "dispatch.json",
        completion=tmp_path / "completion.json",
        output=tmp_path / "output.txt",
        resources=[],
    )
    mutation(kwargs)
    with pytest.raises((ValueError, FileExistsError), match=match):
        build_boundary(**kwargs)


@pytest.mark.skipif(os.name == "nt", reason="the declared physical package uses WSL absolute paths")
def test_independent_audit_rejects_command_and_claim_drift(tmp_path):
    value = make_boundary(tmp_path)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    good = audit_boundary(boundary, resources=[])
    assert good["boundary_qualified"] is True

    changed = copy.deepcopy(value)
    changed["command"].append("--startup-preflight")
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[])["boundary_qualified"] is False

    changed = copy.deepcopy(value)
    changed["fusion_eligible"] = True
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[])["boundary_qualified"] is False


@pytest.mark.skipif(os.name == "nt", reason="the declared physical package uses WSL absolute paths")
def test_independent_audit_rejects_live_resources(tmp_path):
    value = make_boundary(tmp_path)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    result = audit_boundary(boundary, resources=["gazebo"])
    assert result["boundary_qualified"] is False
    assert "resources" in result["failures"]


def test_archive_byte_drift_is_rejected(tmp_path):
    changed = tmp_path / ARCHIVE.name
    shutil.copy2(ARCHIVE, changed)
    data = bytearray(changed.read_bytes())
    data[-1] ^= 1
    changed.write_bytes(data)
    with pytest.raises(ValueError, match="archive identity"):
        _verify_archive(changed)


@pytest.mark.parametrize("kind", ["package", "startup"])
def test_saved_audit_drift_is_rejected_before_dispatch(tmp_path, monkeypatch, kind):
    saved_package = json.loads(PACKAGE_AUDIT.read_text(encoding="utf-8"))
    monkeypatch.setattr(boundary_module, "audit_retry_package", lambda *args, **kwargs: saved_package)
    package = PACKAGE_AUDIT
    startup = STARTUP_AUDIT
    if kind == "package":
        value = copy.deepcopy(saved_package)
        value["prepare_qualified"] = False
        package = tmp_path / "package.json"
        package.write_text(json.dumps(value), encoding="utf-8")
    else:
        value = json.loads(STARTUP_AUDIT.read_text(encoding="utf-8"))
        value["startup_preflight_qualified"] = False
        startup = tmp_path / "startup.json"
        startup.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match=f"live {kind} audit"):
        _require_audits(STUDY, package, startup, STARTUP_DISPATCH, STARTUP_COMPLETION)
