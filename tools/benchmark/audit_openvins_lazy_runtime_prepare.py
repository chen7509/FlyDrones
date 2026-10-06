"""Independently audit an OpenVINS lazy-mapping prepare-only package."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.benchmark.audit_openvins_lazy_runtime_closure import audit as closure_audit
from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.openvins_lazy_runtime_prepare import (
    FALSE_CLAIMS,
    OUTPUT_NAMES,
    _add_new_role,
    _load_preflight,
    _record,
    _study_args,
    validate_lazy_source,
)
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy


def _require(condition, failures, label):
    if not condition:
        failures.append(label)


def audit(directory, *, closure_auditor=closure_audit,
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
    except Exception as exc:
        failures.append("read:" + repr(exc))
        manifest, binding, execution, policy, lazy = {}, {}, {}, {}, {}

    try:
        policy_validator(policy)
    except Exception as exc:
        failures.append("policy:" + repr(exc))
    _require(manifest.get("schema") == "openvins-lazy-runtime-prepare-v1", failures,
             "manifest schema")
    _require(manifest.get("prepare_only") is True, failures, "prepare-only claim")
    _require(binding.get("schema") == "capture-resource-binding-v3", failures, "binding schema")
    _require(execution.get("schema") == "capture-execution-v3", failures, "execution schema")
    for key in FALSE_CLAIMS:
        _require(manifest.get(key) is False, failures, "manifest overclaim: " + key)
    _require(manifest.get("runtime_mapping_coverage_verified") is False, failures,
             "runtime mapping overclaim")
    _require(not (root / "capture-v1").exists(), failures, "capture destination exists")

    try:
        recomputed_lazy = validate_lazy_source(
            lazy["source_study"], lazy["source_audit"]["resolved"],
            lazy["package_archive"]["resolved"], closure_auditor=closure_auditor)
        _require(_typed_equal(lazy, recomputed_lazy), failures, "lazy contract recomputation")
    except Exception as exc:
        failures.append("lazy source:" + repr(exc))
        recomputed_lazy = None

    try:
        source_root, source_names, source_binding, source_contract, source_policy = _load_preflight(
            manifest["source_study"], policy_validator)
        _require(_typed_equal(policy, source_policy), failures, "policy copy")
        source_paths = [source_root / name for name in sorted(source_names)]
        source_records = [_record(path) for path in source_paths]
        _require(_typed_equal(manifest.get("source_records"), source_records), failures,
                 "source record recomputation")

        expected_binding = copy.deepcopy(source_binding)
        inventory = expected_binding["inventory"]
        inventory["runtime:trajectory-gauge-policy"] = [str((root / "trajectory-gauge-policy.json").resolve())]
        _add_new_role(inventory, "runtime:lazy-prepare-source", source_paths)
        if recomputed_lazy is not None:
            _add_new_role(inventory, "runtime:openvins-lazy-evidence",
                          [record["resolved"] for record in recomputed_lazy["source_records"]])
        _add_new_role(inventory, "runtime:openvins-lazy-contract", [root / "lazy-runtime-contract.json"])
        fresh_baseline = snapshot(inventory)
        _require(_typed_equal(binding.get("baseline", {}).get("files"), fresh_baseline["files"]),
                 failures, "binding baseline")
        expected_binding["baseline"] = binding.get("baseline")
        _require(_typed_equal(binding, expected_binding), failures, "binding recomputation")
        declared = {str(Path(path).resolve(strict=True)) for paths in binding.get("inventory", {}).values()
                    for path in paths}
        _require(recomputed_lazy is not None
                 and recomputed_lazy["allocator"]["resolved"] in declared, failures,
                 "allocator declaration")

        environment = derive_launch_environment(binding)
        args = _study_args(root / "capture-v1", source_contract,
                           root / "trajectory-gauge-policy.json",
                           root / "runtime-binding-v3.json", root / "execution-contract.json")
        expected_execution = execution_contract(args, environment)
        _require(_typed_equal(execution, expected_execution), failures, "execution recomputation")
        command = manifest.get("command")
        _require(type(command) is list and len(command) >= 2
                 and all(type(value) is str for value in command), failures, "command shape")
        if type(command) is list and len(command) >= 2:
            expected_command = declared_command(args, command[0], command[1], environment)
            _require(_typed_equal(command, expected_command), failures, "command recomputation")
            _require(Path(command[0]).is_absolute() and Path(command[1]).is_absolute(), failures,
                     "absolute command")
        _require(_typed_equal(manifest.get("execution_contract"), execution), failures,
                 "manifest execution")
        _require(manifest.get("runtime_binding") == str((root / "runtime-binding-v3.json").resolve()),
                 failures, "manifest binding")
        _require(manifest.get("trajectory_gauge_policy")
                 == str((root / "trajectory-gauge-policy.json").resolve()), failures,
                 "manifest policy")
        _require(_typed_equal(manifest.get("lazy_contract"), _record(root / "lazy-runtime-contract.json")),
                 failures, "manifest lazy contract")
    except Exception as exc:
        failures.append("derived package:" + repr(exc))

    return {
        "schema": "openvins-lazy-runtime-prepare-audit-v1",
        "failures": failures,
        "prepare_qualified": not failures,
        "physical_execution_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
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
    return 0 if result["prepare_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["audit"]
