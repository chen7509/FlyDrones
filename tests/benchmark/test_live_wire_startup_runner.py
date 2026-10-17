"""The startup diagnostic must be ready before a capture command can run."""

import json
import subprocess

import pytest


def test_observed_runner_starts_capture_after_observer_ready(tmp_path):
    from tools.benchmark.live_wire_startup_runner import run_observed_capture

    log = tmp_path / "px4.log"
    observed = tmp_path / "startup-observation.json"
    summary = tmp_path / "startup-summary.json"
    invoked = []

    def fake_runner(command, **kwargs):
        invoked.append((command, kwargs))
        assert observed.exists()
        assert not log.exists()
        log.write_text("INFO Startup script returned successfully\n", encoding="utf8")
        return subprocess.CompletedProcess(command, 0)

    completed = run_observed_capture(
        ["fake-capture"], log_path=log, observation_path=observed,
        summary_path=summary, observer_deadline_ns=1_000_000_000,
        ready_timeout_s=1, runner=fake_runner, cwd=tmp_path,
        study_manifest_sha256="a" * 64, diagnostic_declaration_sha256="b" * 64,
    )
    assert completed.returncode == 0
    assert len(invoked) == 1
    saved = json.loads(summary.read_text(encoding="utf8"))
    assert saved["observer_ready"] is True
    assert saved["runner_invoked"] is True
    assert saved["capture_returncode"] == 0
    assert saved["observer_status"] == "startup_completed"
    assert saved["study_manifest_sha256"] == "a" * 64
    assert saved["diagnostic_declaration_sha256"] == "b" * 64
    assert saved["qualification_granted"] is False


def test_preexisting_px4_log_prevents_capture_and_retains_failure(tmp_path):
    from tools.benchmark.live_wire_startup_runner import run_observed_capture

    log = tmp_path / "px4.log"
    log.write_text("historical\n")
    invoked = []

    def forbidden_runner(*args, **kwargs):
        invoked.append((args, kwargs))
        raise AssertionError("capture should not start")

    summary = tmp_path / "startup-summary.json"
    with pytest.raises(ValueError, match="observer failed before capture"):
        run_observed_capture(
            ["fake-capture"], log_path=log,
            observation_path=tmp_path / "startup-observation.json",
            summary_path=summary, observer_deadline_ns=40_000_000,
            ready_timeout_s=1, runner=forbidden_runner,
        )
    assert invoked == []
    saved = json.loads(summary.read_text(encoding="utf8"))
    assert saved["runner_invoked"] is False
    assert saved["capture_returncode"] is None
    assert "existed before observer" in saved["observer_failure"]


def test_capture_exception_keeps_observer_and_raw_error(tmp_path):
    from tools.benchmark.live_wire_startup_runner import run_observed_capture

    log = tmp_path / "px4.log"
    summary = tmp_path / "startup-summary.json"

    def failed_capture(*args, **kwargs):
        log.write_text("INFO Startup script returned with return value: 15\n", encoding="utf8")
        raise RuntimeError("capture launcher failed")

    with pytest.raises(RuntimeError, match="capture launcher failed"):
        run_observed_capture(
            ["fake-capture"], log_path=log,
            observation_path=tmp_path / "startup-observation.json",
            summary_path=summary, observer_deadline_ns=1_000_000_000,
            ready_timeout_s=1, runner=failed_capture,
        )
    saved = json.loads(summary.read_text(encoding="utf8"))
    assert saved["runner_invoked"] is True
    assert saved["capture_returncode"] is None
    assert "capture launcher failed" in saved["capture_failure"]
    assert saved["observer_status"] == "startup_failed"


def test_missing_log_remains_missing_without_inventing_px4_startup(tmp_path):
    from tools.benchmark.live_wire_startup_runner import run_observed_capture

    summary = tmp_path / "startup-summary.json"
    completed = run_observed_capture(
        ["fake-capture"], log_path=tmp_path / "px4.log",
        observation_path=tmp_path / "startup-observation.json",
        summary_path=summary, observer_deadline_ns=40_000_000,
        ready_timeout_s=1,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 2),
    )
    assert completed.returncode == 2
    saved = json.loads(summary.read_text(encoding="utf8"))
    assert saved["capture_returncode"] == 2
    assert saved["observer_status"] == "deadline_without_log"
    assert saved["qualification_granted"] is False
