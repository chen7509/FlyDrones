"""Prepare one prospective raw-depth physical study without launching it."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

from tools.benchmark.capture_contract import (
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import _add_missing
from tools.benchmark.openvins_health_physical_preflight import (
    PROFILE,
    SOURCE_PROFILES,
    _load_source,
    run_args,
)
from tools.benchmark.runtime_resource_binding import validate_binding

SEED = 28001
CODE_PATHS = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/disarmed_sensor_provenance.py",
    "tools/benchmark/ready_shadow_fanout.py",
    "tools/benchmark/openvins_health_contract.py",
    "tools/benchmark/openvins_health_physical_faults.py",
    "tools/benchmark/prepare_depth_physical_development.py",
)


def collector_code_paths(root):
    # The collector's top-level imports include its wire/bootstrap modules.
    # Bind that actual import closure before the capture worker checks it.
    from tools.benchmark import capture_disarmed_sensors  # noqa: F401

    roots = (root / "tools/benchmark", root / "src/flydrones")
    paths = {(root / name).resolve(strict=True) for name in CODE_PATHS}
    for module in tuple(sys.modules.values()):
        location = getattr(module, "__file__", None)
        if location is None:
            continue
        module_path = Path(location)
        lexical = module_path.absolute()
        candidate = module_path.resolve(strict=False)
        if any(lexical.is_relative_to(scope) or candidate.is_relative_to(scope)
               for scope in roots):
            paths.add(module_path.resolve(strict=True))
    return [str(path) for path in sorted(paths)]


def prepare(output, *, source_study, source_audit, health_binary, capture_script,
            python, resources, seed=SEED):
    if resources:
        raise ValueError("competing resources present")
    if type(seed) is not int or seed != SEED:
        raise ValueError("single depth development seed differs")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    source, audit_path, source_contract, source_binding = _load_source(source_study, source_audit)
    audit = read_declaration(audit_path)
    if (audit_path != (source / "final-audit-v2.json").resolve(strict=True)
            or audit.get("input_sha256", {}).get("execution-contract.json")
            != hashlib.sha256((source / "execution-contract.json").read_bytes()).hexdigest()
            or audit.get("input_sha256", {}).get("runtime-binding-v3.json")
            != hashlib.sha256((source / "runtime-binding-v3.json").read_bytes()).hexdigest()):
        raise ValueError("source audit does not bind this study")
    health_binary = Path(health_binary).resolve(strict=True)
    capture_script = Path(capture_script).resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    if capture_script != (root / "tools/benchmark/capture_disarmed_sensors.py").resolve(strict=True):
        raise ValueError("capture script is not the fixed collector")
    python = Path(python)
    if not python.is_absolute():
        raise ValueError("interpreter must be an existing absolute file")
    try:
        python = python.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("interpreter must be an existing absolute file") from exc
    if not python.is_file():
        raise ValueError("interpreter must be an existing absolute file")
    code_paths = collector_code_paths(root)
    output.mkdir(parents=True)
    policy_path = output / "trajectory-gauge-policy.json"
    shutil.copy2(source / "trajectory-gauge-policy.json", policy_path)
    binding = copy.deepcopy(source_binding)
    binding["inventory"]["runtime-root:openvins"] = [str(health_binary)]
    _add_missing(binding["inventory"], "runtime:depth-study-code", code_paths)
    _add_missing(binding["inventory"], "runtime:depth-study-interpreter", [str(python)])
    _add_missing(binding["inventory"], "evidence:depth-study-source", [audit_path])
    binding["baseline"] = snapshot(binding["inventory"])
    binding = validate_binding(binding)
    binding_path = output / "runtime-binding-v3.json"
    execution_path = output / "execution-contract.json"
    args = run_args(
        output=output / "capture-v1", source_contract=source_contract,
        health_binary=health_binary, policy_path=policy_path,
        binding_path=binding_path, execution_path=execution_path, seed=seed,
    )
    args.record_depth_payload = True
    environment = derive_launch_environment(binding)
    contract = execution_contract(args, environment)
    if (contract.get("record_depth_payload") is not True
            or contract.get("profiles") != {**SOURCE_PROFILES, "health_profile": PROFILE}
            or (contract["simulation_duration_ns"], contract["physics_step_ns"],
                contract["imu_hz"], contract["rgbd_hz"], contract["rgbd_size"])
            != (25_000_000_000, 1_000_000, 250, 10, [160, 120])):
        raise ValueError("depth study would change frozen physical workload")
    write_manifest(binding_path, binding)
    write_manifest(execution_path, contract)
    command = declared_command(args, python, capture_script, environment)
    manifest = {
        "schema": "openvins-health-physical-run-preflight-v1",
        "prepare_only": True,
        "run_id": f"depth-development-seed-{seed}",
        "role": "development",
        "seed": seed,
        "source_study": str(source),
        "source_audit": file_record(audit_path),
        "preparer": file_record(__file__),
        "health_binary": file_record(health_binary),
        "health_profile": PROFILE,
        "execution_contract": contract,
        "runtime_binding": str(binding_path.resolve()),
        "future_destination": str((output / "capture-v1").resolve()),
        "command": command,
        "depth_payload_required": True,
        "depth_effect_isolated": False,
        "source_estimator_binary": file_record(source_contract["inputs"]["shadow_binary"]),
        "held_out_results_viewed": False,
        "test_set_tuning_allowed": False,
        "physical_run_completed": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "source-study", "source-audit", "health-binary", "capture-script", "python"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED, choices=[SEED])
    parser.add_argument("--prepare-only", action="store_true", required=True)
    values = vars(parser.parse_args(argv))
    values.pop("prepare_only")
    print(json.dumps(prepare(**values, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
