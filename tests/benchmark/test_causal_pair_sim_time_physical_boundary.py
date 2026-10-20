import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark.causal_pair_sim_time_physical_boundary as boundary_module
import tools.benchmark.execute_causal_pair_sim_time_physical_boundary as executor_module
from tools.benchmark.audit_causal_pair_sim_time_physical_boundary import audit_boundary
from tools.benchmark.causal_pair_sim_time_physical_boundary import _require_audits, _verify_archive, build_boundary
from tools.benchmark.execute_causal_pair_sim_time_physical_boundary import execute

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v18"
PACKAGE_AUDIT = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-audit-v3-after-startup.json"
STARTUP_AUDIT = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-startup-audit-v1.json"
STARTUP_DISPATCH = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v10-dispatch.json"
STARTUP_COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v10-completion.json"
ARCHIVE = ROOT / "evidence/causal-pair-sim-time-retry-preflight-dev-1701.zip"


def adapt_saved_audits(monkeypatch):
    package = json.loads(PACKAGE_AUDIT.read_text(encoding="utf-8"))
    startup = json.loads(STARTUP_AUDIT.read_text(encoding="utf-8"))
    monkeypatch.setattr(boundary_module, "audit_retry_package", lambda *args, **kwargs: package)
    monkeypatch.setattr(boundary_module, "audit_startup_preflight", lambda *args, **kwargs: startup)


def make_boundary(tmp_path, monkeypatch):
    adapt_saved_audits(monkeypatch)
    study = tmp_path / "study"
    study.mkdir()
    for source in STUDY.iterdir():
        if source.is_file():
            shutil.copy2(source, study / source.name)
    (study / "startup-preflight-v1").mkdir()
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
    )


def test_real_inputs_build_closed_one_shot_boundary(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    assert value["schema"] == "causal-pair-sim-time-physical-boundary-v1"
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
    )
    mutation(kwargs)
    with pytest.raises((ValueError, FileExistsError), match=match):
        build_boundary(**kwargs)


def test_independent_audit_rejects_command_and_claim_drift(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    good = audit_boundary(boundary, resources=[], observed_git_head="a" * 40)
    assert good["boundary_qualified"] is True

    changed = copy.deepcopy(value)
    changed["command"].append("--startup-preflight")
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is False

    changed = copy.deepcopy(value)
    changed["fusion_eligible"] = True
    boundary.write_text(json.dumps(changed), encoding="utf-8")
    assert audit_boundary(boundary, resources=[], observed_git_head="a" * 40)["boundary_qualified"] is False


def test_independent_audit_rejects_live_resources(tmp_path, monkeypatch):
    value = make_boundary(tmp_path, monkeypatch)
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(value), encoding="utf-8")
    result = audit_boundary(boundary, resources=["gazebo"], observed_git_head="a" * 40)
    assert result["boundary_qualified"] is False
    assert any("resources" in failure for failure in result["failures"])


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


def test_executor_refuses_unqualified_boundary_without_running(tmp_path, monkeypatch):
    boundary = tmp_path / "boundary.json"
    boundary.write_text("{}", encoding="utf-8")
    called = False

    def runner(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        executor_module,
        "audit_boundary",
        lambda *args, **kwargs: {"boundary_qualified": False, "failures": ["head"]},
    )
    with pytest.raises(ValueError, match="not qualified"):
        execute(boundary, resources_fn=lambda: [], runner=runner)
    assert called is False


def test_executor_writes_once_and_preserves_command_returncode(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        executor_module,
        "audit_boundary",
        lambda *args, **kwargs: {"boundary_qualified": True, "failures": []},
    )
    result = execute(boundary, resources_fn=lambda: [], runner=lambda *args, **kwargs: SimpleNamespace(returncode=7))
    assert result == 7
    assert json.loads(dispatch.read_text())["single_actual_attempt"] is True
    assert json.loads(completion.read_text())["command_returncode"] == 7
    with pytest.raises(FileExistsError):
        execute(boundary, resources_fn=lambda: [], runner=lambda *args, **kwargs: SimpleNamespace(returncode=0))
