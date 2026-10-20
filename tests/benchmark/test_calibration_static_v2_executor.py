import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "results/target-bearing-runtime-freeze-v2-dev-1701/run-static-preparation-v2.py"


def load(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("static_v2_coordinator_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "results/target-bearing-runtime-freeze-v2-dev-1701")
    monkeypatch.setattr(module, "FOLDER", module.OUT / "frozen-study-v2")
    module.OUT.mkdir(parents=True)
    return module


def facts():
    return dict(
        windows_available=2**30,
        wsl=dict(available=2**30, processes=[]),
        windows_processes=[],
        blocked_processes=[],
        docker_exit=0,
        docker_running="",
    )


def test_first_refusal_retains_exact_facts_without_claim(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    first = facts()
    first["windows_available"] -= 1
    monkeypatch.setattr(m, "admission", lambda: first)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    monkeypatch.setattr(m, "preidentity", lambda: pytest.fail("resource refusal must precede identity calls"))
    result = m.execute()
    assert result["attempt_consumed"] is False
    assert json.loads((m.OUT / "first-admission-private.json").read_text())["facts"] == first
    assert not (m.OUT / "attempt.json").exists()


def test_existing_claim_refuses_before_admission(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    (m.OUT / "attempt.json").write_text("{}")
    monkeypatch.setattr(m, "admission", lambda: pytest.fail("no gate for consumed attempt"))
    with pytest.raises(FileExistsError):
        m.execute()


def configure(m, monkeypatch):
    monkeypatch.setattr(m, "CONTROL", {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/1000"})
    monkeypatch.setattr(m, "admission", facts)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    monkeypatch.setattr(m, "preidentity", lambda: {"fixture": "identity"})
    monkeypatch.setattr(m, "verify_preidentity", lambda identity: None)
    monkeypatch.setattr(m, "manager_call", lambda *args: subprocess.CompletedProcess(args, 0, b"LoadState=not-found\n", b""))
    monkeypatch.setattr(m, "observe_release", lambda unit: {"owned_group_released": True})
    monkeypatch.setattr(m, "verify_result", lambda: {"fixture_only": True})
    monkeypatch.setattr(m, "postidentity", lambda: {"fixture_only": True})


class Child:
    pid = 991

    def __init__(self):
        self.calls = []

    def poll(self):
        return None

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout):
        self.calls.append(("wait", timeout))
        return 0


def test_after_spawn_writer_failure_cleans_owned_child_and_preserves_primary(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    write = m.write

    def fail(path, row):
        if path.name == "launcher.json":
            raise OSError("fixture postspawn writer")
        write(path, row)

    monkeypatch.setattr(m, "write", fail)
    result = m.execute()
    assert result["attempt_consumed"] is True and "postspawn writer" in result["error"]
    assert "terminate" in child.calls and ("wait", 5) in child.calls
    assert (m.OUT / "completion.json").is_file()


def test_timeout_unknown_scope_never_stops_unit(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()

    def wait(timeout):
        child.calls.append(("wait", timeout))
        if timeout == 240:
            raise subprocess.TimeoutExpired("fixture", 240)
        return -15

    child.wait = wait
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    calls = []
    monkeypatch.setattr(
        m, "manager_call", lambda *args: calls.append(args) or subprocess.CompletedProcess(args, 0, b"LoadState=not-found\n", b"")
    )
    result = m.execute()
    assert result["attempt_consumed"] is True and result["error"]
    assert not any("stop" in args for args in calls)
    assert result["escaped_closure"] == "unknown"


def test_stop_requires_fresh_matching_invocation_and_group(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    unit = "fly-calibration-prepare-" + "a" * 24 + ".scope"
    inside = dict(cgroup="/fixture/" + unit, systemd_properties="InvocationID=original\nControlGroup=/fixture/" + unit)
    calls = []
    monkeypatch.setattr(
        m,
        "manager_call",
        lambda *args: (
            calls.append(args) or subprocess.CompletedProcess(args, 0, b"InvocationID=other\nControlGroup=/fixture\n", b"")
        ),
    )
    with pytest.raises(ValueError, match="ownership"):
        m.stop_if_owned(unit, inside)
    assert not any("stop" in args for args in calls)


def test_second_refusal_after_preidentity_never_claims(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    calls = []

    def collect():
        data = facts()
        if calls:
            data["wsl"]["available"] -= 1
        calls.append(True)
        return data

    monkeypatch.setattr(m, "admission", collect)
    result = m.execute()
    assert result["attempt_consumed"] is False and len(calls) == 2
    assert not (m.OUT / "attempt.json").exists()


def test_changed_postidentity_is_terminal_even_with_successful_launcher(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(m, "postidentity", lambda: (_ for _ in ()).throw(ValueError("fixture changed tool")), raising=False)
    result = m.execute()
    assert result["error"] and "changed tool" in result["postidentity_error"]


def test_manager_control_must_join_observed_uid(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    record = dict(
        error=None,
        sources={"fixture": "source"},
        files_before=[],
        files_after=[],
        uid=1000,
        manager_control_environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8", XDG_RUNTIME_DIR="/run/user/1001"),
    )
    with pytest.raises(ValueError, match="manager"):
        m.verify_preidentity(record)


def test_completion_writer_cannot_mask_primary_spawn_failure(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("primary spawn")))
    write = m.write

    def fail(path, row):
        if path.name == "completion.json":
            raise OSError("secondary writer")
        write(path, row)

    monkeypatch.setattr(m, "write", fail)
    result = m.execute()
    assert "primary spawn" in result["error"] and "secondary writer" in result["completion_writer_error"]
    assert json.loads((m.OUT / "completion-fallback.json").read_text())["error"] == result["error"]


def test_version_postpin_failure_keeps_partial_owned_query(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    seen = []

    def pin(path):
        seen.append(path)
        if len(seen) > 1:
            raise OSError("postpin lost")
        return {"requested": path, "sha256": "a" * 64}

    query = {
        "exit": 1,
        "error": "primary version failure",
        "stdout_hex": b"partial".hex(),
        "stderr_hex": "",
        "reader_complete": True,
        "output_limit_exceeded": False,
    }
    row = m.version_observation("/fixture/tool", m.OUT / "version.json", pin=pin, run=lambda *a: query)
    assert row["query"] == query and "postpin lost" in row["postpin_error"]
    assert json.loads((m.OUT / "version.json").read_text())["query"] == query


def test_preidentity_uses_current_python_roots_not_historical_unselected_roots(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    producer = __import__("tools.benchmark.prepare_calibration_capture_v2", fromlist=["x"])
    declared = __import__("tools.benchmark.declared_runtime_snapshot", fromlist=["x"])
    contract = __import__("tools.benchmark.calibration_capture_contract", fromlist=["x"])
    scope = __import__("tools.benchmark.calibration_capture_scope", fromlist=["x"])
    monkeypatch.setattr(m.sys, "platform", "linux")
    monkeypatch.setattr(m.os, "getuid", lambda: 1000, raising=False)
    (m.OUT / "first-admission.json").write_text('{"static_admitted":true}')
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "inventory": {
                    "runtime-root:python-old": ["/old/python-extension.so"],
                    "runtime-root:renderer": ["/current/renderer.so"],
                    "runtime:dependencies": ["/retained/candidate.so"],
                }
            }
        )
    )
    monkeypatch.setattr(producer, "CATALOG", catalog)
    old = tmp_path / "v1"
    old.mkdir()
    (old / "agent-runtime.json").write_text("{}")
    (old / "agent-deployment.json").write_text("{}")
    monkeypatch.setattr(producer, "V1_FOLDER", old)
    monkeypatch.setattr(
        producer,
        "reuse_agent_cache",
        lambda *a: {"files": [{"requested": "/retained/agent"}], "bundle": {"requested": "/retained/bundle"}},
    )
    monkeypatch.setattr(contract, "scene_record", lambda *a: {"path": "/retained/scene", "files": {"manifest.json": {}}})
    monkeypatch.setattr(
        scope, "manager_environment", lambda: {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/1000"}
    )
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    monkeypatch.setattr(m.importlib.metadata, "version", lambda *a: "fixture version")
    seen = []

    def record(path):
        seen.append(str(path))
        return {"requested": str(path), "resolved": str(path), "sha256": "a" * 64}

    monkeypatch.setattr(declared, "file_record", record)
    monkeypatch.setattr(
        m,
        "version_observation",
        lambda path, *a: {
            "file_before": record(path),
            "file_after": record(path),
            "query": {"exit": 0, "error": None, "reader_complete": True, "output_limit_exceeded": False},
        },
    )
    m.linux_preidentity()
    assert "/old/python-extension.so" not in seen
    assert "/current/renderer.so" in seen and "/retained/candidate.so" in seen
    assert "/retained/agent" in seen and "/retained/bundle" in seen and str(Path("/retained/scene") / "manifest.json") in seen
    assert any(path.endswith("_hashlib.pyd") or path.endswith("_hashlib.so") or "_hashlib." in path for path in seen)


def test_later_file_pin_failure_retains_actual_prefix(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)

    def pin(path):
        if path == "/second":
            raise OSError("later pin failed")
        return {"requested": path, "sha256": "a" * 64}

    row = m.observe_files(["/first", "/second"], m.OUT / "pins.json", pin=pin)
    assert row["files"] == [{"requested": "/first", "sha256": "a" * 64}]
    assert row["failed_path"] == "/second" and "later pin failed" in row["error"]
    assert json.loads((m.OUT / "pins.json").read_text()) == row
