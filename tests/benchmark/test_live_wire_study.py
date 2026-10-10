"""Prospective manifest checks with real files and explicitly synthetic assets.

Tiny fixture binaries are never executed and do not qualify installed resources.
"""

import builtins
import importlib.util
import socket
import subprocess
from pathlib import Path

import pytest

from tests.benchmark.live_wire_study_fixture import fixture, write
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot


def api():
    assert importlib.util.find_spec("tools.benchmark.live_wire_study") is not None, "study validator missing"
    from tools.benchmark import live_wire_study

    return live_wire_study


def test_pure_validates_without_reading_or_granting_live_authority(tmp_path, monkeypatch):
    module = api()
    manifest, documents, _ = fixture(tmp_path)

    def forbidden(*_a, **_k):
        raise AssertionError("pure validator performed I/O")

    with monkeypatch.context() as m:
        m.setattr(Path, "open", forbidden)
        m.setattr(Path, "stat", forbidden)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(socket, "socket", forbidden)
        result = module.validate_live_wire_study(manifest, **documents)
    assert result["document_validated"] is True
    assert result["files_verified"] is False
    assert result["live_qualified"] is False and result["fusion_qualified"] is False
    result["manifest"]["command"].append("changed")
    assert manifest["command"][-1] != "changed"


def test_staged_startup_study_validates_files_without_granting_live_authority(tmp_path):
    manifest, _, path = fixture(tmp_path, staged_wire=True)
    result = api().validate_live_wire_study_files(path)
    assert result["files_verified"] is True
    assert result["manifest"] == manifest
    assert result["live_qualified"] is False and result["fusion_qualified"] is False
    assert all(not Path(p).exists() for p in manifest["outputs"].values())


@pytest.mark.parametrize("cap", [0, 60_000_000_001, True, 60.0])
def test_staged_startup_study_rejects_invalid_cap(tmp_path, cap):
    manifest, docs, _ = fixture(tmp_path, staged_wire=True)
    docs["wire_config"]["startup_max_wall_ns"] = cap
    docs["execution"]["wire"]["configuration"]["startup_max_wall_ns"] = cap
    with pytest.raises(ValueError, match="invalid startup wall cap"):
        api().validate_live_wire_study(manifest, **docs)


@pytest.mark.parametrize(
    "mutation",
    [
        "startup",
        "worker",
        "extra_command",
        "wrong_command_input",
        "missing_native",
        "missing_config",
        "missing_reference",
        "no_estimator",
        "wrong_load",
        "float_limit",
        "bool_seed",
        "heldout",
        "extra_authority",
        "grant",
        "clock_scope",
        "clock_origin",
        "clock_session",
        "loose_timeout",
        "remote_endpoint",
        "wrong_profile",
        "duplicate_output",
        "nested_output",
        "output_input_collision",
        "bad_hash",
        "missing_file_role",
        "missing_owned_native",
        "missing_baseline",
        "wrong_environment",
    ],
)
def test_refuses_incompatible_or_misbound_study(tmp_path, mutation):
    module = api()
    manifest, docs, _ = fixture(tmp_path)
    if mutation == "startup":
        manifest["command"].append("--startup-preflight")
    elif mutation == "worker":
        manifest["command"].append("--worker")
    elif mutation == "extra_command":
        manifest["command"] += ["--unknown", "ignored"]
    elif mutation == "wrong_command_input":
        manifest["command"][manifest["command"].index("--shadow-config") + 1] = "/wrong"
    elif mutation.startswith("missing_") and mutation in ("missing_native", "missing_config", "missing_reference"):
        field = {"missing_native": "shadow_binary", "missing_config": "shadow_config", "missing_reference": "reference_module"}[
            mutation
        ]
        docs["execution"]["inputs"][field] = None
    elif mutation == "no_estimator":
        docs["execution"]["estimator_run"] = False
    elif mutation == "wrong_load":
        docs["execution"]["imu_hz"] = 100
    elif mutation == "float_limit":
        manifest["limits"]["accepted_samples"] = 500.0
    elif mutation == "bool_seed":
        manifest["simulation_seed"] = True
    elif mutation == "heldout":
        manifest["role"] = "held-out"
    elif mutation == "extra_authority":
        manifest["network_authorized"] = True
    elif mutation == "grant":
        manifest["live_activation_authorized"] = True
    elif mutation == "clock_scope":
        manifest["clock_scope"] = "px4-request-echo"
    elif mutation == "clock_origin":
        docs["wire_config"]["remote_origin_ns"] = 123
    elif mutation == "clock_session":
        docs["wire_config"]["session_id"] = "other-session"
    elif mutation == "loose_timeout":
        manifest["limits"]["bootstrap_wall_ns"] *= 2
    elif mutation == "remote_endpoint":
        manifest["endpoint"]["peer_host"] = "192.168.1.2"
    elif mutation == "wrong_profile":
        docs["execution"]["profiles"]["motion_intent_profile"] = None
    elif mutation == "duplicate_output":
        manifest["outputs"]["audit"] = manifest["outputs"]["dispatch"]
    elif mutation == "nested_output":
        manifest["outputs"]["audit"] = str(Path(manifest["outputs"]["capture"]) / "audit.json")
    elif mutation == "output_input_collision":
        manifest["outputs"]["capture"] = str(tmp_path)
    elif mutation == "bad_hash":
        manifest["files"]["auditor"]["sha256"] = "bad"
    elif mutation == "missing_file_role":
        del manifest["files"]["auditor"]
    elif mutation == "missing_owned_native":
        del docs["binding"]["runtime_maps"]["owned_roles"]["openvins"]
    elif mutation == "missing_baseline":
        docs["binding"]["baseline"]["files"].pop()
    elif mutation == "wrong_environment":
        docs["execution"]["launch_environment"]["HOME"] = "different"
    with pytest.raises(ValueError):
        module.validate_live_wire_study(manifest, **docs)


def test_file_adapter_verifies_actual_bytes_and_has_no_runtime_effect(tmp_path, monkeypatch):
    module = api()
    manifest, _, path = fixture(tmp_path)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "gz" or name.startswith("gz."):
            raise AssertionError("runtime imported")
        return real_import(name, *args, **kwargs)

    def forbidden(*_a, **_k):
        raise AssertionError("runtime effect")

    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", guarded_import)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(socket, "socket", forbidden)
        result = module.validate_live_wire_study_files(path)
    assert result["files_verified"] is True and result["live_qualified"] is False
    assert result["manifest"] == manifest
    assert all(not Path(p).exists() for p in manifest["outputs"].values())


@pytest.mark.parametrize("mutation", ["content", "missing", "native", "calibration", "duplicate_json", "existing_output"])
def test_file_adapter_refuses_drift_without_creating_output(tmp_path, mutation):
    module = api()
    manifest, docs, path = fixture(tmp_path)
    if mutation == "content":
        Path(manifest["files"]["wire_config"]["requested"]).write_text("{}")
    elif mutation == "missing":
        Path(manifest["files"]["auditor"]["requested"]).unlink()
    elif mutation == "native":
        Path(docs["execution"]["inputs"]["shadow_binary"]).write_text("drift")
    elif mutation == "calibration":
        (tmp_path / "kalibr_imu_chain.yaml").write_text("drift")
    elif mutation == "duplicate_json":
        path.write_text(path.read_text()[:-1] + ',"study_id":"other"}')
    elif mutation == "existing_output":
        Path(manifest["outputs"]["dispatch"]).write_text("old evidence")
    with pytest.raises((ValueError, FileNotFoundError)):
        module.validate_live_wire_study_files(path)
    assert not Path(manifest["outputs"]["capture"]).exists()
    if mutation == "existing_output":
        assert Path(manifest["outputs"]["dispatch"]).read_text() == "old evidence"


def test_output_created_during_final_dependency_read_is_refused(tmp_path, monkeypatch):
    module = api()
    manifest, _, path = fixture(tmp_path)
    real_snapshot = module.snapshot
    calls = 0

    def concurrent_output(inventory):
        nonlocal calls
        calls += 1
        result = real_snapshot(inventory)
        if calls == 2:
            Path(manifest["outputs"]["dispatch"]).write_text("other dispatch evidence")
        return result

    monkeypatch.setattr(module, "snapshot", concurrent_output)
    with pytest.raises(ValueError, match="output already exists"):
        module.validate_live_wire_study_files(path)
    assert Path(manifest["outputs"]["dispatch"]).read_text() == "other dispatch evidence"
    assert not Path(manifest["outputs"]["capture"]).exists()


def test_dependency_changed_during_final_read_is_refused(tmp_path, monkeypatch):
    module = api()
    _, docs, path = fixture(tmp_path)
    real_snapshot = module.snapshot
    calls = 0

    def concurrent_dependency(inventory):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(docs["execution"]["inputs"]["shadow_binary"]).write_text("changed concurrently")
        return real_snapshot(inventory)

    monkeypatch.setattr(module, "snapshot", concurrent_dependency)
    with pytest.raises(ValueError):
        module.validate_live_wire_study_files(path)


@pytest.mark.parametrize("omitted", ["kalibr_imu_chain.yaml", "kalibr_imucam_chain.yaml", "freeze.json"])
def test_self_consistent_inventory_missing_required_estimator_file_is_refused(tmp_path, omitted):
    module = api()
    manifest, docs, path = fixture(tmp_path)
    binding = docs["binding"]
    binding["inventory"]["config"].remove(str(tmp_path / omitted))
    binding["baseline"] = snapshot(binding["inventory"])
    binding_path = Path(manifest["files"]["binding"]["requested"])
    write(binding_path, binding)
    manifest["files"]["binding"] = file_record(binding_path)
    write(path, manifest)
    with pytest.raises(ValueError, match="complete frozen estimator configuration"):
        module.validate_live_wire_study_files(path)
