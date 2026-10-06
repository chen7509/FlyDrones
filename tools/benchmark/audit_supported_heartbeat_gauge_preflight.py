"""Independently audit a prepare-only supported heartbeat gauge package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.supported_heartbeat_gauge_preflight import (
    EXPECTED_PROFILES,
    EXPECTED_WORKLOAD,
    FALSE_SOURCE_CLAIMS,
    _study_args,
    prospective_worker_code_paths,
)
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy


def _require(condition, failures, message):
    if not condition:
        failures.append(message)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(directory):
    root = Path(directory).resolve(strict=True)
    failures = []
    try:
        manifest = read_declaration(root / "study-manifest.json")
        contract = read_declaration(root / "execution-contract.json")
        binding = read_declaration(root / "runtime-binding-v3.json")
        policy = read_declaration(root / "trajectory-gauge-policy.json")
    except Exception as exc:
        failures.append("read:" + repr(exc))
        manifest, contract, binding, policy = {}, {}, {}, {}

    _require(manifest.get("schema") == "supported-heartbeat-gauge-preflight-v1", failures, "manifest:schema")
    _require(manifest.get("prepare_only") is True, failures, "manifest:prepare_only")
    _require(contract.get("schema") == "capture-execution-v3", failures, "contract:schema")
    _require(binding.get("schema") == "capture-resource-binding-v3", failures, "binding:schema")
    try:
        validate_trajectory_gauge_policy(policy)
    except Exception as exc:
        failures.append("policy:" + repr(exc))

    for key, expected in EXPECTED_WORKLOAD.items():
        _require(_typed_equal(contract.get(key), expected), failures, "workload:" + key)
    _require(_typed_equal(contract.get("profiles"), EXPECTED_PROFILES), failures, "profiles")
    for key in (*FALSE_SOURCE_CLAIMS, "physical_run_completed"):
        if key in manifest:
            _require(manifest.get(key) is False, failures, "claim:" + key)

    policy_path = root / "trajectory-gauge-policy.json"
    policy_record = contract.get("trajectory_gauge_policy")
    _require(type(policy_record) is dict, failures, "policy:record")
    if type(policy_record) is dict and policy_path.is_file():
        _require(policy_record.get("path") == str(policy_path.absolute()), failures, "policy:path")
        _require(policy_record.get("resolved") == str(policy_path.resolve()), failures, "policy:resolved")
        _require(policy_record.get("bytes") == policy_path.stat().st_size, failures, "policy:bytes")
        _require(policy_record.get("sha256") == _sha(policy_path), failures, "policy:sha256")

    inventory = binding.get("inventory")
    expected_policy_inventory = [str(policy_path.resolve())]
    _require(type(inventory) is dict, failures, "binding:inventory")
    if type(inventory) is dict:
        _require(inventory.get("runtime:trajectory-gauge-policy") == expected_policy_inventory,
                 failures, "binding:policy_inventory")
        _require(inventory.get("runtime:prospective-worker-policy-code") == prospective_worker_code_paths(),
                 failures, "binding:policy_code_inventory")
        try:
            fresh = snapshot(inventory)
            baseline = binding.get("baseline")
            _require(type(baseline) is dict and baseline.get("schema") == "declared-files-v1"
                     and _typed_equal(baseline.get("files"), fresh["files"]), failures, "binding:baseline")
        except Exception as exc:
            failures.append("binding:snapshot:" + repr(exc))

    _require(_typed_equal(manifest.get("execution_contract"), contract), failures, "manifest:contract")
    _require(manifest.get("runtime_binding") == str((root / "runtime-binding-v3.json").resolve()),
             failures, "manifest:binding_path")
    _require(manifest.get("trajectory_gauge_policy") == str(policy_path.resolve()),
             failures, "manifest:policy_path")
    _require(not (root / "capture-v1").exists(), failures, "capture:destination_exists")

    records = manifest.get("source_records")
    _require(type(records) is list and len(records) == 3, failures, "source:records")
    if type(records) is list:
        for index, row in enumerate(records):
            try:
                path = Path(row["path"]).resolve(strict=True)
                _require(path.is_file(), failures, f"source:{index}:regular")
                _require(row["bytes"] == path.stat().st_size, failures, f"source:{index}:bytes")
                _require(row["sha256"] == _sha(path), failures, f"source:{index}:sha256")
            except Exception as exc:
                failures.append(f"source:{index}:" + repr(exc))

    command = manifest.get("command")
    _require(type(command) is list and len(command) >= 2 and all(type(item) is str for item in command),
             failures, "command:shape")
    if type(command) is list and len(command) >= 2:
        _require(Path(command[0]).is_absolute() and Path(command[1]).is_absolute(),
                 failures, "command:absolute_executables")
        try:
            environment = derive_launch_environment(binding)
            args = _study_args(root / "capture-v1", contract, policy_path,
                               root / "runtime-binding-v3.json", root / "execution-contract.json")
            expected_contract = execution_contract(args, environment)
            _require(_typed_equal(contract, expected_contract), failures, "contract:recomputed")
            expected_command = declared_command(args, command[0], command[1], environment)
            _require(_typed_equal(command, expected_command), failures, "command:exact")
        except Exception as exc:
            failures.append("contract_or_command:" + repr(exc))

    return {
        "schema": "supported-heartbeat-gauge-preflight-audit-v1",
        "failures": failures,
        "preflight_qualified": not failures,
        "physical_run_completed": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "runtime_closure_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.input)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["preflight_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
