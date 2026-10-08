"""Prospective manifest checks with real files and explicitly synthetic assets.

Tiny fixture binaries are never executed and do not qualify installed resources.
"""

import builtins
import hashlib
import importlib.util
import json
import socket
import subprocess
from pathlib import Path

import pytest

from tests.benchmark.test_bound_resource_graph import graph_fixture
from tools.benchmark import capture_contract as contract
from tools.benchmark.capture_disarmed_sensors import parse_capture_args
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy


def api():
    assert importlib.util.find_spec("tools.benchmark.live_wire_study") is not None, "study validator missing"
    from tools.benchmark import live_wire_study

    return live_wire_study


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def fixture(tmp_path):
    binding, _, _, _, _ = graph_fixture(tmp_path)
    binding["schema"] = "capture-resource-binding-v3"
    binding["runtime_maps"] = dict(
        self_phases=["postimports", "postfinalize", "postfirststep"],
        owned_roles={"px4": ["ready", "prestop"], "openvins": ["ready", "prestop"]},
        max_maps_bytes=8 * 1024 * 1024,
        max_observations=8,
    )
    paths = {
        k: tmp_path / name
        for k, name in dict(
            python="python",
            capture="capture.py",
            auditor="auditor.py",
            execution="execution.json",
            binding="binding.json",
            wire_config="wire.json",
            gauge_policy="gauge.json",
        ).items()
    }
    for role in ("python", "capture", "auditor"):
        paths[role].write_text("fixture only, never executed: " + role)
    native, reference, px4 = [tmp_path / n for n in ("online_probe", "reference.so", "px4")]
    for path in (native, reference, px4):
        path.write_text("fixture only, never executed: " + path.name)
    config = tmp_path / "estimator_config.yaml"
    config.write_text("relative_config_imu: kalibr_imu_chain.yaml\nrelative_config_imucam: kalibr_imucam_chain.yaml\n")
    calibrations = [tmp_path / n for n in ("kalibr_imu_chain.yaml", "kalibr_imucam_chain.yaml")]
    for path in calibrations:
        path.write_text("fixture calibration, not loaded")
    freeze = write(
        tmp_path / "freeze.json",
        {"sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [config, *calibrations]}},
    )
    wire = dict(schema="capture-wire-v1", session_id="normal-v1.clock", sim_origin_ns=0, remote_origin_ns=0)
    gauge = trajectory_gauge_policy()
    write(paths["wire_config"], wire)
    write(paths["gauge_policy"], gauge)
    binding["inventory"]["runtime-root:px4"] = [str(px4)]
    binding["inventory"]["runtime-root:openvins"] = [str(native)]
    binding["inventory"]["runtime-root:native-reference"] = [str(reference)]
    binding["inventory"]["config"] = [str(p) for p in [config, *calibrations, freeze]]
    binding["inventory"]["policy"] = [str(paths["wire_config"]), str(paths["gauge_policy"])]
    binding["baseline"] = snapshot(binding["inventory"])
    write(paths["binding"], binding)
    outputs = {
        k: str(tmp_path / n)
        for k, n in dict(
            capture="live-capture", dispatch="dispatch.json", completion="completion.json", audit="audit.json"
        ).items()
    }
    args = parse_capture_args(
        [
            "--output",
            outputs["capture"],
            "--execution-contract",
            str(paths["execution"]),
            "--runtime-binding",
            str(paths["binding"]),
            "--wire-config",
            str(paths["wire_config"]),
            "--trajectory-gauge-policy",
            str(paths["gauge_policy"]),
            "--shadow-binary",
            str(native),
            "--shadow-config",
            str(config),
            "--reference-module",
            str(reference),
            "--reference-sha256",
            hashlib.sha256(reference.read_bytes()).hexdigest(),
            "--simulation-seed",
            "27601",
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--motion-intent-profile",
            "native-beginning-zupt-v1",
            "--health-profile",
            "px4-d6f12ad-gate-floor-v1",
        ]
    )
    env = contract.derive_launch_environment(binding)
    execution = contract.execution_contract(args, env)
    write(paths["execution"], execution)
    manifest = dict(
        schema="live-wire-study-v1",
        study_id="normal-v1",
        producer_commit="a" * 40,
        role="development",
        simulation_seed=27601,
        expected_status="capture_completed",
        clock_scope="postupdate-simulation-epoch-v1",
        live_activation_authorized=False,
        endpoint=dict(
            local_host="127.0.0.1",
            local_port=14548,
            peer_host="127.0.0.1",
            peer_port=14588,
            sender_system=254,
            sender_component=191,
            target_system=9,
            target_component=1,
            instance=8,
        ),
        limits=dict(
            bootstrap_wall_ns=8_000_000_000,
            accepted_samples=500,
            operational_ns=2_000_000_000,
            source_startup_ns=10_000_000_000,
            readiness_sim_ns=8_000_000_000,
            anchor_ahead_ns=200_000_000,
            cleanup_ns=10_000_000_000,
            max_datagrams=4096,
            max_segments=64,
            segment_events=8192,
            journal_bytes=512 * 1024 * 1024,
        ),
        outputs=outputs,
        files={k: file_record(p) for k, p in paths.items()},
        command=contract.declared_command(args, str(paths["python"]), str(paths["capture"]), env),
    )
    manifest_path = write(tmp_path / "manifest.json", manifest)
    return manifest, dict(execution=execution, binding=binding, wire_config=wire, gauge_policy=gauge), manifest_path


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
