import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark.execute_source_watchdog_physical_boundary as executor_module
import tools.benchmark.source_watchdog_physical_boundary as boundary_module
from tools.benchmark.audit_source_watchdog_physical_boundary import audit_boundary
from tools.benchmark.audit_source_watchdog_startup_preflight import audit_startup
from tools.benchmark.execute_source_watchdog_physical_boundary import execute
from tools.benchmark.source_watchdog_physical_boundary import (
    _require_audits,
    _verify_archive,
    _verify_evidence_bytes,
    build_boundary,
)

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v19"
PACKAGE_AUDIT = ROOT / "results/source-watchdog-retry-preflight-dev-1701/study-v19-audit-v4-final.json"
STARTUP_AUDIT = ROOT / "results/source-watchdog-retry-preflight-dev-1701/startup-preflight-audit.json"
STARTUP_DISPATCH = ROOT / "results/source-watchdog-retry-preflight-dev-1701/startup-preflight-dispatch.json"
STARTUP_COMPLETION = ROOT / "results/source-watchdog-retry-preflight-dev-1701/startup-preflight-completion.json"
ARCHIVE = ROOT / "evidence/source-watchdog-retry-preflight-dev-1701.zip"


def adapt_saved_audits(monkeypatch):
    package = json.loads(PACKAGE_AUDIT.read_text(encoding="utf-8"))
    startup = json.loads(STARTUP_AUDIT.read_text(encoding="utf-8"))
    monkeypatch.setattr(boundary_module, "audit_retry_package", lambda *args, **kwargs: package)
    monkeypatch.setattr(boundary_module, "audit_startup", lambda *args, **kwargs: startup)
    monkeypatch.setattr(boundary_module, "_verify_evidence_bytes", lambda *args, **kwargs: None)


def make_boundary(tmp_path, monkeypatch):
    adapt_saved_audits(monkeypatch)
    study = tmp_path / "study"
    shutil.copytree(STUDY, study)
    manifest_path = study / "study-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    destination = study / "capture-v1"
    manifest["future_destination"] = destination.as_posix()
    manifest["command"][manifest["command"].index("--output") + 1] = destination.as_posix()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    head_file = tmp_path / "head.txt"
    head_file.write_text("a" * 40 + "\n", encoding="utf-8")
    return build_boundary(
        study=study,
        package_audit=PACKAGE_AUDIT,
        startup_audit=STARTUP_AUDIT,
        startup_dispatch=STARTUP_DISPATCH,
        startup_completion=STARTUP_COMPLETION,
        evidence_archive=ARCHIVE,
        expected_head="a" * 40,
        head_file=head_file,
        observed_git_head="a" * 40,
        dispatch=tmp_path / "dispatch.json",
        completion=tmp_path / "completion.json",
        output=tmp_path / "output.txt",
        resources=[],
        verify_archive_evidence=True,
    )


def test_real_startup_evidence_passes_independent_audit():
    value = audit_startup(STUDY, STARTUP_DISPATCH, STARTUP_COMPLETION)
    assert value["failures"] == []
    assert value["startup_preflight_qualified"] is True
    assert value["physical_execution_qualified"] is False


def test_real_inputs_build_closed_one_shot_boundary(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    assert value["schema"] == "source-watchdog-physical-boundary-v1"
    assert value["head"] == "a" * 40
    assert value["destination"].replace("\\", "/").endswith("/study/capture-v1")
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
        observed_git_head="a" * 40,
        dispatch=tmp_path / "dispatch.json",
        completion=tmp_path / "completion.json",
        output=tmp_path / "output.txt",
        resources=[],
        verify_archive_evidence=True,
    )
    mutation(kwargs)
    with pytest.raises((ValueError, FileExistsError), match=match):
        build_boundary(**kwargs)


def test_independent_audit_rejects_command_claim_and_resource_drift(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is True

    changed = copy.deepcopy(value)
    changed["command"].append("--startup-preflight")
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is False

    changed = copy.deepcopy(value)
    changed["fusion_eligible"] = True
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is False

    boundary.write_text(json.dumps(value), encoding="utf-8")
    assert audit_boundary(boundary, resources=["gazebo"], observed_git_head="a" * 40)["boundary_qualified"] is False


def test_archive_byte_drift_is_rejected(tmp_path):
    changed = tmp_path / ARCHIVE.name
    shutil.copy2(ARCHIVE, changed)
    data = bytearray(changed.read_bytes())
    data[-1] ^= 1
    changed.write_bytes(data)
    with pytest.raises(ValueError, match="archive identity"):
        _verify_archive(changed)


def test_archive_evidence_byte_drift_is_rejected(tmp_path):
    changed = tmp_path / "package-audit.json"
    changed.write_bytes(PACKAGE_AUDIT.read_bytes() + b" ")
    with pytest.raises(ValueError, match="evidence archive bytes:package_audit"):
        _verify_evidence_bytes(
            ARCHIVE,
            study=STUDY,
            package_audit=changed,
            startup_audit=STARTUP_AUDIT,
            startup_dispatch=STARTUP_DISPATCH,
            startup_completion=STARTUP_COMPLETION,
        )


def test_saved_startup_audit_drift_is_rejected(tmp_path, monkeypatch):
    package = json.loads(PACKAGE_AUDIT.read_text(encoding="utf-8"))
    monkeypatch.setattr(boundary_module, "audit_retry_package", lambda *args, **kwargs: package)
    changed = json.loads(STARTUP_AUDIT.read_text(encoding="utf-8"))
    changed["startup_preflight_qualified"] = False
    path = tmp_path / "startup-audit.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="live startup audit"):
        _require_audits(STUDY, PACKAGE_AUDIT, path, STARTUP_DISPATCH, STARTUP_COMPLETION)


def test_executor_refuses_unqualified_boundary_without_running(tmp_path, monkeypatch):
    boundary = tmp_path / "boundary.json"
    boundary.write_text("{}", encoding="utf-8")
    called = False

    def runner(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(executor_module, "audit_boundary", lambda *args, **kwargs: {"boundary_qualified": False, "failures": ["head"]})
    with pytest.raises(ValueError, match="not qualified"):
        execute(boundary, resources_fn=lambda: [], runner=runner)
    assert called is False


def test_executor_writes_once_and_preserves_returncode(tmp_path, monkeypatch):
    destination = tmp_path / "capture-v1"
    boundary = tmp_path / "boundary.json"
    dispatch = tmp_path / "dispatch.json"
    completion = tmp_path / "completion.json"
    output = tmp_path / "output.txt"
    boundary.write_text(
        json.dumps(
            {
                "study": tmp_path.as_posix(),
                "destination": destination.as_posix(),
                "command": ["declared", "command"],
                "head": "a" * 40,
                "dispatch": dispatch.as_posix(),
                "completion": completion.as_posix(),
                "output": output.as_posix(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(executor_module, "audit_boundary", lambda *args, **kwargs: {"boundary_qualified": True, "failures": []})
    result = execute(boundary, resources_fn=lambda: [], runner=lambda *args, **kwargs: SimpleNamespace(returncode=7))
    assert result == 7
    assert json.loads(dispatch.read_text())["single_actual_attempt"] is True
    assert json.loads(completion.read_text())["command_returncode"] == 7
    with pytest.raises(FileExistsError):
        execute(boundary, resources_fn=lambda: [], runner=lambda *args, **kwargs: SimpleNamespace(returncode=0))
