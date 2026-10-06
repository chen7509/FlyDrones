import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools.benchmark.declared_runtime_snapshot import snapshot
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy

PASS = {
    "schema": "openvins-lazy-runtime-prepare-audit-v1",
    "failures": [],
    "prepare_qualified": True,
    "physical_execution_qualified": False,
    "runtime_mapping_coverage_verified": False,
    "runtime_closure_qualified": False,
    "vio_accuracy_qualified": False,
    "estimator_health_qualified": False,
    "fusion_eligible": False,
    "flight_ready": False,
}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def source_package(tmp_path):
    root = tmp_path / "lazy-prepare"
    root.mkdir()
    runtime = tmp_path / "runtime.bin"
    shadow = tmp_path / "online_probe"
    config = tmp_path / "config.yaml"
    reference = tmp_path / "reference.so"
    for path in (runtime, shadow, config, reference):
        path.write_bytes(path.name.encode())
    policy = root / "trajectory-gauge-policy.json"
    write_json(policy, trajectory_gauge_policy())
    lazy = root / "lazy-runtime-contract.json"
    write_json(lazy, {"schema": "openvins-lazy-runtime-prepare-contract-v1"})
    inventory = {
        "runtime:openvins-lazy-contract": [str(lazy.resolve())],
        "runtime:test": [str(runtime.resolve())],
        "runtime:trajectory-gauge-policy": [str(policy.resolve())],
    }
    environment = {"HOME": "/home/test", "SDF_PATH": ""}
    binding = {
        "schema": "capture-resource-binding-v3",
        "inventory": inventory,
        "baseline": snapshot(inventory),
        "environment": environment,
        "graph": {"environment": {}},
        "generated": {},
        "runtime_maps": {"owned_roles": ["px4", "openvins"]},
    }
    contract = {
        "schema": "capture-execution-v3",
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
        "trajectory_gauge_policy": {
            "path": str(policy.absolute()),
            "resolved": str(policy.resolve()),
            "bytes": policy.stat().st_size,
            "sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
            "schema": "trajectory-gauge-policy-v1",
        },
    }
    write_json(root / "runtime-binding-v3.json", binding)
    write_json(root / "execution-contract.json", contract)
    write_json(root / "study-manifest.json", {
        "schema": "openvins-lazy-runtime-prepare-v1",
        "prepare_only": True,
        "execution_contract": contract,
        "physical_execution_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    })
    audit = tmp_path / "lazy-prepare-audit.json"
    write_json(audit, PASS)
    archive = tmp_path / "source-evidence.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as package:
        for name in sorted(path.name for path in root.iterdir()):
            package.write(root / name, "study-v1/" + name)
        package.write(audit, "verification/audit-v1.json")
    return root, audit, archive


def fake_source_auditor(_root):
    return dict(PASS)


def build(tmp_path):
    from tools.benchmark.estimator_aware_readiness_preflight import prepare_study

    source, audit, archive = source_package(tmp_path)
    output = tmp_path / "prepared"
    prepare_study(
        output,
        source_study=source,
        source_audit=audit,
        source_archive=archive,
        capture_script=Path("/study/capture.py"),
        python=Path("/usr/bin/python3"),
        resources=[],
        source_auditor=fake_source_auditor,
        policy_validator=lambda value: value,
    )
    return output, source, audit


def test_prepare_changes_only_readiness_profile_and_never_launches(tmp_path):
    output, source, _ = build(tmp_path)
    old = json.loads((source / "execution-contract.json").read_text())
    new = json.loads((output / "execution-contract.json").read_text())
    manifest = json.loads((output / "study-manifest.json").read_text())
    binding = json.loads((output / "runtime-binding-v3.json").read_text())
    assert new["profiles"] == {
        **old["profiles"],
        "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
    }
    for key in (
        "wall_budget_s", "supervisor_s", "simulation_duration_ns", "physics_step_ns",
        "imu_hz", "rgbd_hz", "rgbd_size", "estimator_run", "inputs", "reference_sha256",
        "launch_environment",
    ):
        assert new[key] == old[key]
    assert binding["runtime_maps"] == json.loads(
        (source / "runtime-binding-v3.json").read_text()
    )["runtime_maps"]
    assert binding["baseline"]["files"] == snapshot(binding["inventory"])["files"]
    assert manifest["command"][manifest["command"].index("--source-fanout-profile") + 1] == (
        "ready-shadow-heartbeat-estimator-v1"
    )
    assert manifest["future_destination"] == str((output / "capture-v1").resolve())
    assert not (output / "capture-v1").exists()
    assert manifest["physical_execution_qualified"] is False
    assert manifest["runtime_closure_qualified"] is False
    assert manifest["vio_accuracy_qualified"] is False
    assert manifest["fusion_eligible"] is False


@pytest.mark.parametrize("failure", ["active", "existing", "audit", "stored", "source", "capture"])
def test_prepare_refuses_invalid_source_or_destination(tmp_path, failure):
    from tools.benchmark.estimator_aware_readiness_preflight import prepare_study

    source, audit, archive = source_package(tmp_path)
    output = tmp_path / "prepared"
    resources = [{"pid": 1}] if failure == "active" else []
    auditor = fake_source_auditor
    if failure == "existing":
        output.mkdir()
    elif failure == "audit":
        def auditor(_root):
            return {**PASS, "failures": ["bad"], "prepare_qualified": False}
    elif failure == "stored":
        write_json(audit, {**PASS, "scope": "drift"})
    elif failure == "source":
        row = json.loads((source / "study-manifest.json").read_text())
        row["fusion_eligible"] = True
        write_json(source / "study-manifest.json", row)
    elif failure == "capture":
        (source / "capture-v1").mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        prepare_study(
            output,
            source_study=source,
            source_audit=audit,
            source_archive=archive,
            capture_script=Path("/study/capture.py"),
            python=Path("/usr/bin/python3"),
            resources=resources,
            source_auditor=auditor,
            policy_validator=lambda value: value,
        )
