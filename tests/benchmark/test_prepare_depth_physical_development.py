"""Prospective single depth study: no Gazebo or PX4 is started here."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest


def fixture_inputs(tmp_path, monkeypatch):
    from tools.benchmark import capture_contract
    from tools.benchmark import prepare_depth_physical_development as stage

    source = tmp_path / "source"
    source.mkdir()
    (source / "trajectory-gauge-policy.json").write_text('{"fixed":"policy"}')
    (source / "execution-contract.json").write_text('{"fixed":"execution"}')
    (source / "runtime-binding-v3.json").write_text('{"fixed":"binding"}')
    audit = source / "final-audit-v2.json"
    audit.write_text(json.dumps({"input_sha256": {
        "execution-contract.json": hashlib.sha256((source / "execution-contract.json").read_bytes()).hexdigest(),
        "runtime-binding-v3.json": hashlib.sha256((source / "runtime-binding-v3.json").read_bytes()).hexdigest(),
    }}))
    binary = tmp_path / "health-probe"
    binary.write_bytes(b"native health binary")
    config = tmp_path / "estimator.yaml"
    config.write_text("fixed: true\n")
    module = tmp_path / "reference.so"
    module.write_bytes(b"reference module")
    capture = Path(stage.__file__).resolve().with_name("capture_disarmed_sensors.py")
    interpreter = tmp_path / "python3"
    interpreter.write_bytes(b"fixed test interpreter")
    source_contract = {
        "profiles": dict(stage.SOURCE_PROFILES),
        "inputs": {"shadow_binary": str(binary), "shadow_config": str(config),
                   "reference_module": str(module)},
        "reference_sha256": "a" * 64,
    }
    binding = {
        "schema": "capture-resource-binding-v3",
        "inventory": {"runtime-root:openvins": [str(binary)]},
        "environment": {"HOME": str(tmp_path)},
        "graph": {"environment": {"LANG": "C.UTF-8"}},
    }
    monkeypatch.setattr(stage, "_load_source", lambda _source, selected: (
        source, Path(selected).resolve(), source_contract, binding))
    monkeypatch.setattr(stage, "validate_binding", lambda value: value)
    monkeypatch.setattr(capture_contract, "trajectory_gauge_policy_record", lambda path: {
        "schema": "trajectory-gauge-policy-v1", "path": str(path), "sha256": "b" * 64,
    })
    return stage, source, audit, binary, capture, interpreter


def test_prepare_depth_study_freezes_flag_and_unchanged_workload(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    output = tmp_path / "depth-study"
    selected = stage.prepare(
        output, source_study=source, source_audit=audit, health_binary=binary,
        capture_script=capture, python=interpreter, resources=[], seed=28001,
    )
    contract = json.loads((output / "execution-contract.json").read_text())
    assert contract["record_depth_payload"] is True
    assert (contract["simulation_duration_ns"], contract["physics_step_ns"],
            contract["imu_hz"], contract["rgbd_hz"], contract["rgbd_size"]) == (
                25_000_000_000, 1_000_000, 250, 10, [160, 120])
    assert contract["profiles"] == {**stage.SOURCE_PROFILES, "health_profile": stage.PROFILE}
    assert selected["command"].count("--record-depth-payload") == 1
    assert selected["future_destination"] == str((output / "capture-v1").resolve())
    assert selected["role"] == "development" and selected["fusion_eligible"] is False
    inventory = json.loads((output / "runtime-binding-v3.json").read_text())["inventory"]
    assert str(Path(stage.__file__).resolve()) in inventory["runtime:depth-study-code"]
    assert any(selected["command"][0] in paths for paths in inventory.values())
    assert not (output / "capture-v1").exists()
    with pytest.raises(FileExistsError):
        stage.prepare(output, source_study=source, source_audit=audit, health_binary=binary,
                      capture_script=capture, python=interpreter, resources=[], seed=28001)


def test_prepare_depth_study_refuses_busy_or_bad_source_without_output(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    output = tmp_path / "depth-study"
    with pytest.raises(ValueError, match="competing"):
        stage.prepare(output, source_study=source, source_audit=audit, health_binary=binary,
        capture_script=capture, python=interpreter, resources=["PX4"], seed=28001)
    assert not output.exists()
    monkeypatch.setattr(stage, "_load_source", lambda *_args: (_ for _ in ()).throw(ValueError("source failed")))
    with pytest.raises(ValueError, match="source failed"):
        stage.prepare(output, source_study=source, source_audit=audit, health_binary=binary,
        capture_script=capture, python=interpreter, resources=[], seed=28001)
    assert not output.exists()


def test_prepare_depth_study_retains_partial_failure(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    output = tmp_path / "depth-study"
    monkeypatch.setattr(stage, "snapshot", lambda *_args: (_ for _ in ()).throw(OSError("snapshot failed")))
    with pytest.raises(OSError, match="snapshot failed"):
        stage.prepare(output, source_study=source, source_audit=audit, health_binary=binary,
        capture_script=capture, python=interpreter, resources=[], seed=28001)
    assert output.exists()
    assert (output / "trajectory-gauge-policy.json").is_file()
    assert not (output / "execution-contract.json").exists()


def test_prepare_depth_study_rejects_unrelated_audit_and_modified_source(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    other = tmp_path / "other-qualified-audit.json"
    other.write_bytes(audit.read_bytes())
    options = dict(source_study=source, health_binary=binary, capture_script=capture,
                   python=interpreter, resources=[], seed=28001)
    with pytest.raises(ValueError, match="source audit"):
        stage.prepare(tmp_path / "wrong-audit", source_audit=other, **options)
    (source / "execution-contract.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="source audit"):
        stage.prepare(tmp_path / "changed-source", source_audit=audit, **options)
    assert not (tmp_path / "wrong-audit").exists()
    assert not (tmp_path / "changed-source").exists()


def test_prepare_depth_study_rejects_unbound_capture_or_interpreter(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    arbitrary = tmp_path / "capture.py"
    arbitrary.write_text("# arbitrary launcher\n")
    options = dict(source_study=source, source_audit=audit, health_binary=binary,
                   resources=[], seed=28001)
    with pytest.raises(ValueError, match="capture script"):
        stage.prepare(tmp_path / "wrong-capture", capture_script=arbitrary,
                      python=interpreter, **options)
    with pytest.raises(ValueError, match="interpreter"):
        stage.prepare(tmp_path / "missing-interpreter", capture_script=capture,
                      python=tmp_path / "missing-python", **options)
    assert not (tmp_path / "wrong-capture").exists()
    assert not (tmp_path / "missing-interpreter").exists()


def test_prepare_depth_study_resolves_interpreter_alias(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    alias = tmp_path / "python-alias"
    try:
        alias.symlink_to(interpreter)
    except OSError:
        pytest.skip("host does not permit test symlink")
    output = tmp_path / "depth-study"
    selected = stage.prepare(
        output, source_study=source, source_audit=audit, health_binary=binary,
        capture_script=capture, python=alias, resources=[], seed=28001,
    )
    assert selected["command"][0] == str(interpreter.resolve())
    inventory = json.loads((output / "runtime-binding-v3.json").read_text())["inventory"]
    assert any(selected["command"][0] in paths for paths in inventory.values())


def test_prepare_depth_study_binds_collector_import_closure(tmp_path, monkeypatch):
    stage, source, audit, binary, capture, interpreter = fixture_inputs(tmp_path, monkeypatch)
    from tools.benchmark import capture_disarmed_sensors as collector

    output = tmp_path / "depth-study"
    stage.prepare(output, source_study=source, source_audit=audit, health_binary=binary,
                  capture_script=capture, python=interpreter, resources=[], seed=28001)
    inventory = json.loads((output / "runtime-binding-v3.json").read_text())["inventory"]
    declared = {Path(path).resolve() for paths in inventory.values() for path in paths}
    benchmark_root = Path(collector.__file__).resolve().parent
    imported = {
        Path(module.__file__).resolve()
        for module in tuple(sys.modules.values())
        if getattr(module, "__file__", None)
        and Path(module.__file__).resolve().is_relative_to(benchmark_root)
    }
    assert imported <= declared
    assert (benchmark_root / "openvins_health_contract.py") in declared
    assert (benchmark_root / "openvins_health_physical_faults.py") in declared


def test_collector_closure_ignores_missing_file_outside_bound_roots(monkeypatch):
    from tools.benchmark import prepare_depth_physical_development as stage

    unrelated = types.ModuleType("external_missing_ops_for_depth_study")
    unrelated.__file__ = "_ops.py"
    monkeypatch.setitem(sys.modules, unrelated.__name__, unrelated)
    paths = stage.collector_code_paths(Path(stage.__file__).resolve().parents[2])
    assert str(Path(stage.__file__).resolve()) in paths


def test_collector_closure_rejects_missing_file_inside_bound_roots(monkeypatch):
    from tools.benchmark import prepare_depth_physical_development as stage

    root = Path(stage.__file__).resolve().parents[2]
    missing = types.ModuleType("missing_bound_depth_module")
    missing.__file__ = str(root / "tools/benchmark/does_not_exist_depth.py")
    monkeypatch.setitem(sys.modules, missing.__name__, missing)
    with pytest.raises(FileNotFoundError):
        stage.collector_code_paths(root)
