"""Status synthetic admission/result checks; tests never launch Docker."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.connectome import run_status_journal_synthetic as subject


def test_direct_script_imports_without_project_pythonpath():
    root = Path(__file__).resolve().parents[2]
    script = root / "tools/connectome/run_status_journal_synthetic.py"
    command = [sys.executable, "-I", "-c",
               "import runpy; runpy.run_path(" + repr(str(script)) + ", run_name='import_only')"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


def passing():
    source = {"file_count": 263, "profile_sha256": subject.SOURCE_PROFILE_SHA256,
              "verified": True}
    result = {
        "docker_exit": 0, "timed_out": False, "launch_error": None,
        "daemon_id_after": "fixed", "owned_container_remaining": "",
        "source_after": source, "harness_after": subject.HARNESS,
        "cdr_parity": {"independent_cdr_parity": True, "samples": 3,
                       "unavailable_ratios": ["vel_test_ratio"]},
        "cases": {
            "normal": {"writer_exit": 0, "publisher_exit": 0,
                       "audit_completed": True, "samples": 3, "training_eligible": False},
            "fsync_eio": {"writer_exit": 2, "publisher_exit": 0,
                          "audit_completed": False, "training_eligible": False,
                          "terminal_claimed_complete": True,
                          "injection_marker": True},
            "close_eio": {"writer_exit": 2, "publisher_exit": 0,
                          "audit_completed": False, "training_eligible": False,
                          "terminal_claimed_complete": True,
                          "injection_marker": True},
            "partial_then_eio": {"writer_exit": 1, "publisher_exit": 0,
                                 "audit_error": "truncated", "training_eligible": False,
                                 "injection_marker": True},
        },
    }
    preflight = {"daemon_id": "fixed", "source": source}
    return result, preflight


def test_qualification_needs_parity_exit_failure_and_owned_cleanup():
    result, preflight = passing()
    assert subject._qualifies(result, preflight)
    mutations = (
        ("docker_exit", 1), ("timed_out", True),
        ("daemon_id_after", "changed"), ("owned_container_remaining", "alive"),
        ("harness_after", {}), ("cdr_parity", {}),
    )
    for key, value in mutations:
        changed, before = passing()
        changed[key] = value
        assert not subject._qualifies(changed, before), key
    for mode, field, value in (
        ("normal", "samples", 2), ("normal", "audit_completed", False),
        ("fsync_eio", "writer_exit", 0), ("close_eio", "audit_completed", True),
        ("partial_then_eio", "training_eligible", True),
        ("fsync_eio", "injection_marker", False),
        ("fsync_eio", "writer_exit", 124),
        ("close_eio", "terminal_claimed_complete", False),
        ("partial_then_eio", "writer_exit", 124),
        ("partial_then_eio", "audit_error", None),
    ):
        changed, before = passing()
        changed["cases"][mode][field] = value
        assert not subject._qualifies(changed, before), (mode, field)


def test_opaque_sensitive_host_process_refuses_preflight(monkeypatch):
    opaque = subject._INACCESSIBLE
    processes = [
        SimpleNamespace(pid=1001, info={"name": "python.exe", "cmdline": opaque}),
        SimpleNamespace(pid=1002, info={"name": "notepad.exe", "cmdline": opaque}),
        SimpleNamespace(pid=1003, info={"name": opaque, "cmdline": ["pytest"]}),
    ]
    monkeypatch.setattr(subject.psutil, "process_iter", lambda *_a, **_k: processes)
    monkeypatch.setattr(subject, "_windows_process_name",
                        lambda _pid: (_ for _ in ()).throw(RuntimeError("inaccessible")))
    competitors, errors = subject._host_competitors()
    assert competitors == []
    assert [(item["pid"], item["reason"]) for item in errors] == [
        (1001, "inaccessible_launcher_command"),
        (1003, "inaccessible_process_name"),
    ]


def test_existing_result_refuses_second_launch(tmp_path, monkeypatch):
    result = tmp_path / "existing"
    result.mkdir()
    monkeypatch.setattr(subject, "RESULT", result)
    monkeypatch.setattr(subject.subprocess, "run", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(FileExistsError):
        subject.main()


def test_v2_retry_requires_documented_prelaunch_competitor_refusal(tmp_path, monkeypatch):
    import json

    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "run-profile.json").write_text("{}\n")
    (prior / "tools").mkdir()
    (prior / "preflight.json").write_text(json.dumps({
        "competing_processes": [{"pid": 56828, "name": "python.exe"}],
    }))
    (prior / "result.json").write_text(json.dumps({
        "status": "preflight_failed", "started": False,
        "error": "RuntimeError('status synthetic preflight refused')",
    }))
    monkeypatch.setattr(subject, "PRIOR", prior)
    assert subject._prior_preflight_refusal()
    (prior / "launch.json").write_text("{}\n")
    with pytest.raises(ValueError):
        subject._prior_preflight_refusal()
