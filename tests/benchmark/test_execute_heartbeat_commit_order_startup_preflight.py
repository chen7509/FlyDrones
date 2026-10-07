import json
from types import SimpleNamespace

import pytest

import tools.benchmark.execute_heartbeat_commit_order_startup_preflight as module


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path):
    study = tmp_path / "root/results/base/study-v20"
    study.mkdir(parents=True)
    write(
        study / "study-manifest.json",
        {
            "schema": "heartbeat-commit-order-retry-preflight-v1",
            "prepare_only": True,
            "future_destination": str((study / "capture-v1").resolve()),
            "command": ["python", "capture.py", "--output", str((study / "capture-v1").resolve())],
        },
    )
    audit = {
        "schema": "heartbeat-commit-order-retry-audit-v1",
        "failures": [],
        "prepare_qualified": True,
    }
    audit_path = tmp_path / "audit.json"
    write(audit_path, audit)
    return study, audit_path, audit


def kwargs(tmp_path, monkeypatch):
    study, audit_path, audit = fixture(tmp_path)
    monkeypatch.setattr(module, "audit_package", lambda path: audit)
    return {
        "study": study,
        "prepare_audit": audit_path,
        "expected_head": "a" * 40,
        "observed_head": "a" * 40,
        "dispatch": tmp_path / "dispatch.json",
        "completion": tmp_path / "completion.json",
        "output": tmp_path / "output.txt",
    }


def test_executes_only_startup_preflight_and_records_completion(tmp_path, monkeypatch):
    values = kwargs(tmp_path, monkeypatch)
    seen = []

    def runner(command, **options):
        seen.append((command, options))
        return SimpleNamespace(returncode=0)

    assert module.execute(**values, resources_fn=lambda: [], runner=runner) == 0
    dispatch = json.loads(values["dispatch"].read_text())
    completion = json.loads(values["completion"].read_text())
    assert dispatch["physical_run"] is False
    assert dispatch["command"][-1] == "--startup-preflight"
    assert dispatch["command"][dispatch["command"].index("--output") + 1].endswith("startup-preflight-v1")
    assert completion["physical_run"] is False and completion["returncode"] == 0
    assert seen and "--startup-preflight" in seen[0][0]
    assert seen[0][1]["cwd"] == values["study"].parents[2]


@pytest.mark.parametrize("fault", ["head", "resources", "existing", "audit"])
def test_refuses_before_dispatch(tmp_path, monkeypatch, fault):
    values = kwargs(tmp_path, monkeypatch)
    resources = []
    if fault == "head":
        values["observed_head"] = "b" * 40
    elif fault == "resources":
        resources = [{"pid": 1}]
    elif fault == "existing":
        values["dispatch"].write_text("used")
    else:
        changed = json.loads(values["prepare_audit"].read_text())
        changed["prepare_qualified"] = False
        write(values["prepare_audit"], changed)
    called = []
    with pytest.raises((ValueError, FileExistsError)):
        module.execute(
            **values,
            resources_fn=lambda: resources,
            runner=lambda *args, **options: called.append(args),
        )
    assert called == []


def test_launcher_failure_is_retained_once(tmp_path, monkeypatch):
    values = kwargs(tmp_path, monkeypatch)

    def fail(*args, **options):
        raise OSError("launcher failure")

    assert module.execute(**values, resources_fn=lambda: [], runner=fail) == 2
    completion = json.loads(values["completion"].read_text())
    assert "launcher failure" in completion["launcher_error"]
    with pytest.raises(FileExistsError):
        module.execute(**values, resources_fn=lambda: [], runner=fail)
