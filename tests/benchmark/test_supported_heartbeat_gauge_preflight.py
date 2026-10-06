import hashlib
import json
from pathlib import Path

import pytest

from tools.benchmark.declared_runtime_snapshot import snapshot


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def base_package(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    runtime = tmp_path / "runtime.bin"
    shadow = tmp_path / "online_probe"
    config = tmp_path / "config.yaml"
    reference = tmp_path / "reference.so"
    for path in (runtime, shadow, config, reference):
        path.write_bytes(path.name.encode())
    inventory = {"runtime:test": [str(runtime.resolve())]}
    environment = {"HOME": "/home/test", "GZ_PARTITION": None, "SDF_PATH": ""}
    binding = {
        "schema": "capture-resource-binding-v3",
        "inventory": inventory,
        "baseline": snapshot(inventory),
        "environment": environment,
        "graph": {"environment": {}},
        "generated": {},
        "runtime_maps": {},
    }
    contract = {
        "schema": "capture-execution-v2",
        "wall_budget_s": 300,
        "supervisor_s": 300,
        "simulation_duration_ns": 25_000_000_000,
        "physics_step_ns": 1_000_000,
        "imu_hz": 250,
        "rgbd_hz": 10,
        "rgbd_size": [160, 120],
        "estimator_run": True,
        "profiles": {
            "motion_profile": "supported-ready-v1",
            "physics_trace_profile": "substep-ready-v1",
            "reference_fault_profile": None,
            "source_fanout_profile": "ready-shadow-heartbeat-v1",
        },
        "inputs": {
            "shadow_binary": str(shadow.resolve()),
            "shadow_config": str(config.resolve()),
            "reference_module": str(reference.resolve()),
        },
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "launch_environment": environment,
    }
    write_json(source / "runtime-binding-v3.json", binding)
    write_json(source / "execution-contract.json", contract)
    write_json(source / "study-manifest.json", {
        "schema": "full-load-runtime-mapping-study-v1",
        "prepare_only": True,
        "execution_contract": contract,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    })
    return source


def test_prepare_builds_v3_policy_bound_command_without_launch(tmp_path):
    from tools.benchmark import supported_heartbeat_gauge_preflight as preflight

    source = base_package(tmp_path)
    output = tmp_path / "preflight"
    manifest = preflight.prepare_study(
        output,
        source_study=source,
        capture_script=Path("/study/capture_disarmed_sensors.py"),
        python=Path("/usr/bin/python3"),
        resources=[],
    )
    contract = json.loads((output / "execution-contract.json").read_text())
    binding = json.loads((output / "runtime-binding-v3.json").read_text())
    policy = json.loads((output / "trajectory-gauge-policy.json").read_text())
    assert manifest["schema"] == "supported-heartbeat-gauge-preflight-v1"
    assert manifest["prepare_only"] is True
    assert contract["schema"] == "capture-execution-v3"
    assert contract["trajectory_gauge_policy"]["sha256"] == hashlib.sha256(
        (output / "trajectory-gauge-policy.json").read_bytes()).hexdigest()
    assert binding["inventory"]["runtime:trajectory-gauge-policy"] == [
        str((output / "trajectory-gauge-policy.json").resolve())]
    from tools.benchmark import trajectory_gauge_contract

    assert binding["inventory"]["runtime:trajectory-gauge-code"] == [
        str(Path(trajectory_gauge_contract.__file__).resolve())]
    assert policy["anchor_source"] == "immutable_readiness_anchor"
    assert "anchor_ns" not in policy
    assert "--trajectory-gauge-policy" in manifest["command"]
    assert manifest["command"][manifest["command"].index("--output") + 1] == str(
        (output / "capture-v1").resolve())
    assert manifest["physical_run_completed"] is False
    assert manifest["fusion_eligible"] is False
    assert not (output / "capture-v1").exists()


@pytest.mark.parametrize("failure", ["active", "reused", "profile", "budget", "claim"])
def test_prepare_refuses_resource_reuse_or_source_overclaim(tmp_path, failure):
    from tools.benchmark import supported_heartbeat_gauge_preflight as preflight

    source = base_package(tmp_path)
    output = tmp_path / "preflight"
    resources = [{"pid": 1}] if failure == "active" else []
    if failure == "reused":
        output.mkdir()
    elif failure in {"profile", "budget"}:
        path = source / "execution-contract.json"
        doc = json.loads(path.read_text())
        if failure == "profile":
            doc["profiles"]["source_fanout_profile"] = "ready-shadow-v1"
        else:
            doc["wall_budget_s"] = 301
        write_json(path, doc)
    elif failure == "claim":
        path = source / "study-manifest.json"
        doc = json.loads(path.read_text())
        doc["fusion_eligible"] = True
        write_json(path, doc)
    with pytest.raises((ValueError, FileExistsError), match="competing|exists|source|profile|budget|claim"):
        preflight.prepare_study(
            output,
            source_study=source,
            capture_script=Path("/study/capture_disarmed_sensors.py"),
            python=Path("/usr/bin/python3"),
            resources=resources,
        )
