"""Prepare, but never launch, the supported heartbeat trajectory study."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy

SOURCE_FILES = ("runtime-binding-v3.json", "execution-contract.json", "study-manifest.json")
EXPECTED_PROFILES = {
    "motion_profile": "supported-ready-v1",
    "physics_trace_profile": "substep-ready-v1",
    "reference_fault_profile": None,
    "source_fanout_profile": "ready-shadow-heartbeat-v1",
}
EXPECTED_WORKLOAD = {
    "wall_budget_s": 300,
    "supervisor_s": 300,
    "simulation_duration_ns": 25_000_000_000,
    "physics_step_ns": 1_000_000,
    "imu_hz": 250,
    "rgbd_hz": 10,
    "rgbd_size": [160, 120],
    "estimator_run": True,
}
FALSE_SOURCE_CLAIMS = (
    "runtime_mapping_coverage_verified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "flight_ready",
)
WORKER_POLICY_PATHS = (
    "tools/benchmark/openvins_causal_input.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/trajectory_gauge_contract.py",
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prospective_worker_code_paths():
    root = Path(__file__).resolve().parents[2]
    paths = []
    for relative in WORKER_POLICY_PATHS:
        path = (root / relative).resolve(strict=True)
        if not path.is_file():
            raise ValueError("prospective worker policy module is not a regular file")
        paths.append(str(path))
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate prospective worker policy module")
    return sorted(paths)


def _load_source(source_study):
    root = Path(source_study).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source study must be a directory")
    paths = {name: root / name for name in SOURCE_FILES}
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("source study is incomplete")
    binding = read_declaration(paths["runtime-binding-v3.json"])
    contract = read_declaration(paths["execution-contract.json"])
    manifest = read_declaration(paths["study-manifest.json"])
    if binding.get("schema") != "capture-resource-binding-v3":
        raise ValueError("source binding schema")
    if contract.get("schema") != "capture-execution-v2":
        raise ValueError("source execution schema")
    if manifest.get("schema") != "full-load-runtime-mapping-study-v1" or manifest.get("prepare_only") is not True:
        raise ValueError("source study schema")
    if not _typed_equal(manifest.get("execution_contract"), contract):
        raise ValueError("source execution contract differs from manifest")
    for key, expected in EXPECTED_WORKLOAD.items():
        if not _typed_equal(contract.get(key), expected):
            raise ValueError("source budget or workload mismatch: " + key)
    if not _typed_equal(contract.get("profiles"), EXPECTED_PROFILES):
        raise ValueError("source profile mismatch")
    if contract.get("launch_environment") != derive_launch_environment(binding):
        raise ValueError("source launch environment mismatch")
    if any(manifest.get(key) is not False for key in FALSE_SOURCE_CLAIMS):
        raise ValueError("source claim must remain false")
    inputs = contract.get("inputs")
    if type(inputs) is not dict or set(inputs) != {"shadow_binary", "shadow_config", "reference_module"}:
        raise ValueError("source estimator inputs")
    if any(type(value) is not str or not Path(value).is_file() for value in inputs.values()):
        raise ValueError("source estimator input missing")
    return root, paths, binding, contract


def _study_args(output, source_contract, policy_path, binding_path, contract_path):
    profiles = source_contract["profiles"]
    inputs = source_contract["inputs"]
    return SimpleNamespace(
        output=Path(output),
        shadow_binary=Path(inputs["shadow_binary"]),
        shadow_config=Path(inputs["shadow_config"]),
        reference_module=Path(inputs["reference_module"]),
        reference_sha256=source_contract["reference_sha256"],
        reference_fault_profile=profiles["reference_fault_profile"],
        source_fanout_profile=profiles["source_fanout_profile"],
        motion_profile=profiles["motion_profile"],
        physics_trace_profile=profiles["physics_trace_profile"],
        trajectory_gauge_policy=Path(policy_path),
        execution_contract=Path(contract_path),
        runtime_binding=Path(binding_path),
    )


def prepare_study(output, *, source_study, capture_script, python, resources):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError("destination exists: " + str(output))
    root, source_paths, binding, source_contract = _load_source(source_study)
    output.mkdir(parents=True)
    policy_path = output / "trajectory-gauge-policy.json"
    write_manifest(policy_path, trajectory_gauge_policy())

    bound = copy.deepcopy(binding)
    inventory = bound.get("inventory")
    if type(inventory) is not dict or "runtime:trajectory-gauge-policy" in inventory:
        raise ValueError("trajectory policy inventory role collision")
    inventory["runtime:trajectory-gauge-policy"] = [str(policy_path.resolve())]
    code_role = "runtime:prospective-worker-policy-code"
    if code_role in inventory:
        raise ValueError("prospective worker policy code inventory role collision")
    inventory[code_role] = prospective_worker_code_paths()
    bound["baseline"] = snapshot(inventory)
    binding_path = output / "runtime-binding-v3.json"
    contract_path = output / "execution-contract.json"
    args = _study_args(output / "capture-v1", source_contract, policy_path, binding_path, contract_path)
    environment = derive_launch_environment(bound)
    contract = execution_contract(args, environment)
    write_manifest(binding_path, bound)
    write_manifest(contract_path, contract)
    command = declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment)
    source_records = [
        {"path": str(source_paths[name].resolve()), "bytes": source_paths[name].stat().st_size,
         "sha256": _sha(source_paths[name])}
        for name in SOURCE_FILES
    ]
    manifest = {
        "schema": "supported-heartbeat-gauge-preflight-v1",
        "prepare_only": True,
        "source_study": str(root),
        "source_records": source_records,
        "command": command,
        "execution_contract": contract,
        "runtime_binding": str(binding_path.resolve()),
        "trajectory_gauge_policy": str(policy_path.resolve()),
        "preflight_audited": False,
        "physical_run_completed": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "runtime_closure_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-study", type=Path, required=True)
    parser.add_argument("--capture-script", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    from tools.benchmark.capture_disarmed_sensors import active_resources

    print(json.dumps(prepare_study(
        args.output, source_study=args.source_study, capture_script=args.capture_script,
        python=args.python, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
