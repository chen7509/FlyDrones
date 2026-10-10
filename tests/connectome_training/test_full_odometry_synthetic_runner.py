"""Fail-closed checks for the one-shot synthetic DDS harness."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/connectome/run_full_odometry_synthetic.py"
SPEC = importlib.util.spec_from_file_location("full_odometry_synthetic_runner", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_owned_container_inspection_error_is_unknown_not_absent(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="daemon unavailable")

    monkeypatch.setattr(runner.subprocess, "run", failed)
    remaining, error = runner.inspect_owned_container()
    assert remaining is None
    assert "daemon unavailable" in error


def test_timeout_cleanup_error_is_recorded_and_inspection_still_attempted(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["rm", "-f"]:
            raise subprocess.TimeoutExpired(args, 15)
        return subprocess.CompletedProcess(args, 0, stdout="owned-id\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    cleanup, error = runner.cleanup_owned_container()
    remaining, inspection_error = runner.inspect_owned_container()
    assert cleanup is None and "TimeoutExpired" in error
    assert remaining == "owned-id" and inspection_error is None
    assert len(calls) == 2


def test_fourth_attempt_requires_exact_preserved_unlaunched_v3_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    prior = tmp_path / "results/px4-ros2-full-synthetic-dev-1701-v3"
    prior.mkdir(parents=True)
    (prior / "result.json").write_text(
        json.dumps({"status": "preflight_failed", "started": False}), encoding="utf-8"
    )
    assert runner.select_result(["--retry-after-memory-refusal"]) == (
        tmp_path / "results/px4-ros2-full-synthetic-dev-1701-v4"
    )
    (prior / "launch.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unlaunched"):
        runner.select_result(["--retry-after-memory-refusal"])
