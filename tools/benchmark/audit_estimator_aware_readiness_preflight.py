"""Independently audit an estimator-aware prepare-only package."""

from __future__ import annotations

import copy
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
from tools.benchmark.estimator_aware_readiness_preflight import (
    FALSE_CLAIMS,
    NEW_PROFILE,
    OUTPUT_NAMES,
    SOURCE_NAMES,
    _add_missing,
    _load_source,
    _record,
    estimator_code_paths,
    readiness_contract,
)
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy


def _require(condition, failures, label):
    if not condition:
        failures.append(label)


def audit(directory, *, source_auditor=None,
          policy_validator=validate_trajectory_gauge_policy):
    root = Path(directory).resolve(strict=True)
    failures = []
    try:
        _require({path.name for path in root.iterdir()} == OUTPUT_NAMES, failures, "output member set")
        manifest = read_declaration(root / "study-manifest.json")
        binding = read_declaration(root / "runtime-binding-v3.json")
        execution = read_declaration(root / "execution-contract.json")
        policy = read_declaration(root / "trajectory-gauge-policy.json")
        lazy = read_declaration(root / "lazy-runtime-contract.json")
        readiness = read_declaration(root / "estimator-readiness-contract.json")
    except Exception as exc:
        failures.append("read:" + repr(exc))
        manifest, binding, execution, policy, lazy, readiness = {}, {}, {}, {}, {}, {}

    _require(manifest.get("schema") == "estimator-aware-readiness-preflight-v1", failures,
             "manifest schema")
    _require(manifest.get("prepare_only") is True, failures, "prepare-only claim")
    _require(binding.get("schema") == "capture-resource-binding-v3", failures, "binding schema")
    _require(execution.get("schema") == "capture-execution-v3", failures, "execution schema")
    for key in FALSE_CLAIMS:
        _require(manifest.get(key) is False, failures, "manifest overclaim: " + key)
    _require(not (root / "capture-v1").exists(), failures, "capture destination exists")
    _require(manifest.get("future_destination") == str((root / "capture-v1").resolve()), failures,
             "future destination")

    try:
        source_root, source_binding, source_contract, source_policy, _, _, _ = _load_source(
            manifest["source_study"], readiness["source_audit"]["resolved"],
            readiness["source_archive"]["resolved"],
            source_auditor=source_auditor, policy_validator=policy_validator,
        )
        _require(_typed_equal(policy, source_policy), failures, "policy copy")
        _require(_typed_equal(lazy, read_declaration(source_root / "lazy-runtime-contract.json")), failures,
                 "lazy contract copy")
        expected_readiness = readiness_contract(
            source_root,
            readiness["source_audit"]["resolved"],
            readiness["source_archive"]["resolved"],
        )
        _require(_typed_equal(readiness, expected_readiness), failures, "readiness contract")
        source_paths = [source_root / name for name in sorted(SOURCE_NAMES)] + [
            Path(readiness["source_audit"]["resolved"]),
            Path(readiness["source_archive"]["resolved"]),
        ]
        _require(_typed_equal(manifest.get("source_records"), [_record(path) for path in source_paths]),
                 failures, "source records")

        expected_binding = copy.deepcopy(source_binding)
        inventory = expected_binding["inventory"]
        inventory["runtime:trajectory-gauge-policy"] = [str((root / "trajectory-gauge-policy.json").resolve())]
        inventory["runtime:openvins-lazy-contract"] = [str((root / "lazy-runtime-contract.json").resolve())]
        _add_missing(inventory, "runtime:estimator-aware-readiness-code", estimator_code_paths())
        _add_missing(
            inventory,
            "runtime:estimator-aware-readiness-contract",
            [root / "estimator-readiness-contract.json"],
        )
        _add_missing(inventory, "evidence:estimator-aware-source", source_paths)
        fresh = snapshot(inventory)
        _require(_typed_equal(binding.get("baseline", {}).get("files"), fresh["files"]), failures,
                 "binding baseline")
        expected_binding["baseline"] = binding.get("baseline")
        _require(_typed_equal(binding, expected_binding), failures, "binding recomputation")
        _require(_typed_equal(binding.get("runtime_maps"), source_binding.get("runtime_maps")), failures,
                 "runtime maps changed")

        environment = derive_launch_environment(binding)
        args = _study_args(
            root / "capture-v1", source_contract, root / "trajectory-gauge-policy.json",
            root / "runtime-binding-v3.json", root / "execution-contract.json",
        )
        args.source_fanout_profile = NEW_PROFILE
        expected_execution = execution_contract(args, environment)
        _require(_typed_equal(execution, expected_execution), failures, "execution recomputation")
        for key in (
            "wall_budget_s", "supervisor_s", "simulation_duration_ns", "physics_step_ns",
            "imu_hz", "rgbd_hz", "rgbd_size", "estimator_run", "inputs", "reference_sha256",
            "launch_environment",
        ):
            _require(_typed_equal(execution.get(key), source_contract.get(key)), failures,
                     "unexpected execution change: " + key)
        expected_profiles = copy.deepcopy(source_contract.get("profiles"))
        expected_profiles["source_fanout_profile"] = NEW_PROFILE
        _require(_typed_equal(execution.get("profiles"), expected_profiles), failures,
                 "profile change differs")
        _require(_typed_equal(manifest.get("execution_contract"), execution), failures,
                 "manifest execution")
        command = manifest.get("command")
        _require(type(command) is list and len(command) >= 2, failures, "command shape")
        if type(command) is list and len(command) >= 2:
            expected_command = declared_command(args, command[0], command[1], environment)
            _require(_typed_equal(command, expected_command), failures, "command recomputation")
        _require(manifest.get("runtime_binding") == str((root / "runtime-binding-v3.json").resolve()),
                 failures, "manifest binding")
        _require(manifest.get("trajectory_gauge_policy")
                 == str((root / "trajectory-gauge-policy.json").resolve()), failures,
                 "manifest policy")
        _require(_typed_equal(manifest.get("readiness_contract"),
                              _record(root / "estimator-readiness-contract.json")), failures,
                 "manifest readiness contract")
    except Exception as exc:
        failures.append("derived package:" + repr(exc))

    return {
        "schema": "estimator-aware-readiness-preflight-audit-v1",
        "failures": failures,
        "prepare_qualified": not failures,
        **{key: False for key in FALSE_CLAIMS},
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
    return 0 if result["prepare_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["audit"]
