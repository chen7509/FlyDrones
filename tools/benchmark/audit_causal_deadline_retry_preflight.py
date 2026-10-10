"""Independently audit a causal-deadline-corrected physical retry package."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.causal_deadline_retry_preflight import OUTPUT_NAMES, record, validate_correction, validate_failed_attempt
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args


def audit(root):
    root = Path(root).resolve(strict=True)
    failures = []
    try:
        if {p.name for p in root.iterdir()} != OUTPUT_NAMES:
            failures.append("output members")
        manifest = read_declaration(root / "study-manifest.json")
        contract = read_declaration(root / "deadline-correction-authorization.json")
        binding = read_declaration(root / "runtime-binding-v3.json")
        execution = read_declaration(root / "execution-contract.json")
        source = Path(manifest["source"]).resolve(strict=True)
        source_execution = read_declaration(source / "execution-contract.json")
        if manifest.get("schema") != "causal-deadline-physical-retry-preflight-v1" or manifest.get("prepare_only") is not True:
            failures.append("manifest schema")
        if contract.get("schema") != "causal-deadline-correction-authorization-v1" or contract.get("physical_run") is not False:
            failures.append("authorization contract")
        if not _typed_equal(manifest.get("source_manifest"), record(source / "study-manifest.json")):
            failures.append("source manifest record")
        validate_failed_attempt(
            Path(contract["failed_result"]["requested"]).parent,
            contract["attempt_audit"]["requested"],
            contract["completion"]["requested"],
        )
        validate_correction(contract["correction_audit"]["requested"], contract["correction_archive"]["requested"])
        if not _typed_equal(binding, validate_binding(binding)):
            failures.append("binding validation")
        if not _typed_equal(binding["baseline"]["files"], snapshot(binding["inventory"])["files"]):
            failures.append("binding baseline")
        environment = derive_launch_environment(binding)
        args = _study_args(root / "capture-v1", source_execution, root / "trajectory-gauge-policy.json", root / "runtime-binding-v3.json", root / "execution-contract.json")
        expected_execution = execution_contract(args, environment)
        if not _typed_equal(execution, expected_execution):
            failures.append("execution recomputation")
        for key in (
            "wall_budget_s",
            "supervisor_s",
            "simulation_duration_ns",
            "physics_step_ns",
            "imu_hz",
            "rgbd_hz",
            "rgbd_size",
            "estimator_run",
            "profiles",
            "inputs",
            "reference_sha256",
        ):
            if not _typed_equal(execution.get(key), source_execution.get(key)):
                failures.append("execution changed:" + key)
        expected_command = declared_command(args, manifest["command"][0], manifest["command"][1], environment)
        if not _typed_equal(manifest.get("command"), expected_command):
            failures.append("command recomputation")
        if manifest.get("future_destination") != str((root / "capture-v1").resolve()) or (root / "capture-v1").exists():
            failures.append("future destination")
        for key in FALSE_CLAIMS:
            if manifest.get(key) is not False or contract.get(key) is not False:
                failures.append("overclaim:" + key)
    except Exception as exc:
        failures.append("audit:" + repr(exc))
    return {
        "schema": "causal-deadline-physical-retry-audit-v1",
        "failures": failures,
        "prepare_qualified": not failures,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.input)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["prepare_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
