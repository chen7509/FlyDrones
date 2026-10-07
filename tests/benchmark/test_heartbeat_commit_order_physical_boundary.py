import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark.execute_heartbeat_commit_order_physical_boundary as executor_module
import tools.benchmark.heartbeat_commit_order_physical_boundary as boundary_module
from tools.benchmark.audit_heartbeat_commit_order_physical_boundary import audit_boundary
from tools.benchmark.execute_heartbeat_commit_order_physical_boundary import execute
from tools.benchmark.heartbeat_commit_order_physical_boundary import (
    _verify_archive,
    _verify_evidence_bytes,
    build_boundary,
)

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v21"
PACKAGE_AUDIT = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v21-audit-v3-poststartup.json"
STARTUP_AUDIT = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-audit.json"
STARTUP_DISPATCH = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-dispatch.json"
STARTUP_COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-completion.json"
ARCHIVE = ROOT / "evidence/heartbeat-commit-order-retry-preflight-dev-1701.zip"


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


def test_real_inputs_build_closed_one_shot_boundary(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    assert value["schema"] == "heartbeat-commit-order-physical-boundary-v1"
    assert value["head"] == "a" * 40
    assert value["destination"].endswith("/study/capture-v1")
    assert value["resources_before"] == []
    assert value["single_actual_attempt"] is True and value["physical_run"] is True
    assert value["physical_execution_qualified"] is False
    assert "--startup-preflight" not in value["command"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda values: values.update(expected_head="b" * 40), "committed head"),
        (lambda values: values.update(resources=["px4"]), "competing resources"),
        (lambda values: values["dispatch"].write_text("used"), "one-shot output exists"),
    ],
)
def test_builder_rejects_head_resources_and_reuse(tmp_path, mutation, match):
    head_file = tmp_path / "head.txt"
    head_file.write_text("a" * 40 + "\n")
    values = dict(
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
    mutation(values)
    with pytest.raises((ValueError, FileExistsError), match=match):
        build_boundary(**values)


def test_independent_audit_rejects_command_claim_and_resource_drift(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        "tools.benchmark.audit_heartbeat_commit_order_physical_boundary.build_boundary",
        lambda **kwargs: value,
    )
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is True
    changed = copy.deepcopy(value)
    changed["fusion_eligible"] = True
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is False
    boundary.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        "tools.benchmark.audit_heartbeat_commit_order_physical_boundary.build_boundary",
        boundary_module.build_boundary,
    )
    assert audit_boundary(boundary, resources=["gazebo"], observed_git_head="a" * 40)["boundary_qualified"] is False


def test_archive_byte_and_member_drift_are_rejected(tmp_path):
    changed = tmp_path / ARCHIVE.name
    shutil.copy2(ARCHIVE, changed)
    data = bytearray(changed.read_bytes())
    data[-1] ^= 1
    changed.write_bytes(data)
    with pytest.raises(ValueError, match="archive identity"):
        _verify_archive(changed)
    changed_audit = tmp_path / "package-audit.json"
    changed_audit.write_bytes(PACKAGE_AUDIT.read_bytes() + b" ")
    with pytest.raises(ValueError, match="evidence archive bytes:package_audit"):
        _verify_evidence_bytes(
            ARCHIVE,
            study=STUDY,
            package_audit=changed_audit,
            startup_audit=STARTUP_AUDIT,
            startup_dispatch=STARTUP_DISPATCH,
            startup_completion=STARTUP_COMPLETION,
        )


def test_executor_refuses_unqualified_boundary_without_running(tmp_path, monkeypatch):
    boundary = tmp_path / "boundary.json"
    boundary.write_text("{}", encoding="utf-8")
    called = []
    monkeypatch.setattr(executor_module, "audit_boundary", lambda *args, **kwargs: {"boundary_qualified": False, "failures": ["head"]})
    with pytest.raises(ValueError, match="not qualified"):
        execute(boundary, resources_fn=lambda: [], runner=lambda *args, **kwargs: called.append(args))
    assert called == []


def test_executor_writes_once_and_preserves_returncode(tmp_path, monkeypatch):
    destination = tmp_path / "capture-v1"
    boundary = tmp_path / "boundary.json"
    dispatch, completion, output = (tmp_path / name for name in ("dispatch.json", "completion.json", "output.txt"))
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
