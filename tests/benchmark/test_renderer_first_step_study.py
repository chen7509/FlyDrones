import hashlib
import json

import pytest

from tools.benchmark.renderer_first_step_study import build_command, run_study


def inputs(tmp_path):
    environment = tmp_path / "environment.json"
    environment.write_text(json.dumps({
        "schema": "renderer-probe-environment-v1",
        "materialized": {"HOME": "/home/test", "MESA_SHADER_CACHE_DISABLE": "true"},
    }))
    world = tmp_path / "world.sdf"
    world.write_text("<sdf/>")
    historical = tmp_path / "historical.json"
    historical.write_text("{}")
    python = tmp_path / "python3"
    python.write_text("binary")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    return environment, world, historical, baseline, python


def test_build_command_is_absolute_and_targets_fresh_output(tmp_path):
    environment, world, historical, baseline, python = inputs(tmp_path)
    sha = hashlib.sha256(environment.read_bytes()).hexdigest()
    command, paths = build_command(
        output=tmp_path / "capture", environment=environment, environment_sha256=sha,
        world=world, historical=historical, historical_sha256="b" * 64,
        cache_path="/home/test/.cache/mesa_shader_cache/index", python=python,
        baseline=baseline, baseline_sha256="c" * 64,
    )
    assert command[:3] == [str(python.resolve()), "-m", "tools.benchmark.renderer_first_step_probe"]
    assert str((tmp_path / "capture").resolve()) in command
    assert all(path.is_absolute() for path in paths.values())


def test_build_command_rejects_drift_and_reused_output(tmp_path):
    environment, world, historical, baseline, python = inputs(tmp_path)
    kwargs = dict(
        output=tmp_path / "capture", environment=environment, environment_sha256="0" * 64,
        world=world, historical=historical, historical_sha256="b" * 64,
        cache_path="/cache", python=python,
        baseline=baseline, baseline_sha256="c" * 64,
    )
    with pytest.raises(ValueError, match="hash"):
        build_command(**kwargs)
    kwargs["environment_sha256"] = hashlib.sha256(environment.read_bytes()).hexdigest()
    (tmp_path / "capture").mkdir()
    with pytest.raises(ValueError, match="reused"):
        build_command(**kwargs)


def test_run_study_passes_exact_environment_and_declared_timeout(tmp_path):
    environment, world, historical, baseline, python = inputs(tmp_path)
    sha = hashlib.sha256(environment.read_bytes()).hexdigest()
    calls = []

    def supervisor(command, output, **kwargs):
        calls.append((command, output, kwargs))
        return {"capture_status": "probe_completed"}

    result = run_study(
        output=tmp_path / "capture", environment=environment, environment_sha256=sha,
        world=world, historical=historical, historical_sha256="b" * 64,
        cache_path="/cache", python=python, supervisor=supervisor,
        baseline=baseline, baseline_sha256="c" * 64,
    )
    assert result["launch"]["runtime_closure_qualified"] is False
    assert calls[0][2]["launch_environment"] == {
        "HOME": "/home/test", "MESA_SHADER_CACHE_DISABLE": "true",
    }
    assert calls[0][2]["timeout_s"] == 60
