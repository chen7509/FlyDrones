"""Predeclare unarmed physical OpenVINS source-loss and restart studies."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import _add_missing
from tools.benchmark.openvins_health_physical_faults import PROFILES
from tools.benchmark.openvins_health_physical_preflight import (
    PROFILE,
    _load_source,
    run_args,
)
from tools.benchmark.runtime_resource_binding import validate_binding

CODE_PATHS = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/openvins_health_contract.py",
    "tools/benchmark/openvins_health_physical_faults.py",
    "tools/benchmark/openvins_health_fault_physical_preflight.py",
    "tools/benchmark/openvins_online_shadow.py",
)


def fault_plan():
    return [
        {
            "run_id": "source-loss-retry-seed-27311",
            "role": "source_loss",
            "seed": 27311,
            "health_fault_profile": "imu-source-loss-after-8s-immediate-v2",
            "expected_capture_status": "capture_failed",
            "expected_command_returncode": 2,
        },
        {
            "run_id": "native-restart-retry-seed-27312",
            "role": "native_restart",
            "seed": 27312,
            "health_fault_profile": "native-restart-after-8s-failclosed-v2",
            "expected_capture_status": "capture_failed",
            "expected_command_returncode": 2,
        },
    ]


def fault_run_args(base, profile):
    if profile not in PROFILES:
        raise ValueError("unknown health fault profile")
    values = vars(base).copy()
    values["health_fault_profile"] = profile
    return SimpleNamespace(**values)


def prepare(
    output,
    *,
    source_study,
    source_audit,
    health_binary,
    capture_script,
    python,
    resources,
):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    source, audit_path, source_contract, source_binding = _load_source(source_study, source_audit)
    health_binary = Path(health_binary).resolve(strict=True)
    capture_script = Path(capture_script).resolve(strict=True)
    python = Path(python).absolute()
    root = Path(__file__).resolve().parents[2]
    code_paths = [str((root / name).resolve(strict=True)) for name in CODE_PATHS]
    output.mkdir(parents=True)
    runs = []
    for selected in fault_plan():
        run_root = output / selected["run_id"]
        run_root.mkdir()
        policy_path = run_root / "trajectory-gauge-policy.json"
        shutil.copy2(source / "trajectory-gauge-policy.json", policy_path)
        binding = copy.deepcopy(source_binding)
        binding["inventory"]["runtime-root:openvins"] = [str(health_binary)]
        _add_missing(binding["inventory"], "runtime:openvins-health-fault-code", code_paths)
        _add_missing(binding["inventory"], "evidence:openvins-health-source", [audit_path])
        if selected["role"] == "native_restart":
            owned = binding["runtime_maps"]["owned_roles"]
            if "openvins-restart" in owned:
                raise ValueError("source binding already contains restart role")
            owned["openvins-restart"] = ["ready", "prestop"]
        binding["baseline"] = snapshot(binding["inventory"])
        binding = validate_binding(binding)
        binding_path = run_root / "runtime-binding-v3.json"
        execution_path = run_root / "execution-contract.json"
        base = run_args(
            output=run_root / "capture-v1",
            source_contract=source_contract,
            health_binary=health_binary,
            policy_path=policy_path,
            binding_path=binding_path,
            execution_path=execution_path,
            seed=selected["seed"],
        )
        args = fault_run_args(base, selected["health_fault_profile"])
        environment = derive_launch_environment(binding)
        execution = execution_contract(args, environment)
        write_manifest(binding_path, binding)
        write_manifest(execution_path, execution)
        command = declared_command(args, python, capture_script, environment)
        manifest = {
            "schema": "openvins-health-physical-fault-preflight-v1",
            "prepare_only": True,
            **selected,
            "fault_contract": PROFILES[selected["health_fault_profile"]],
            "source_study": str(source),
            "source_audit": file_record(audit_path),
            "health_binary": file_record(health_binary),
            "health_profile": PROFILE,
            "execution_contract": execution,
            "runtime_binding": str(binding_path.resolve()),
            "future_destination": str((run_root / "capture-v1").resolve()),
            "command": command,
            "truth_used_online": False,
            "odometry_published": False,
            "armed": False,
            "fault_result_viewed": False,
            "test_set_tuning_allowed": False,
            "physical_run_completed": False,
            "fusion_eligible": False,
            "flight_ready": False,
        }
        manifest_path = run_root / "study-manifest.json"
        write_manifest(manifest_path, manifest)
        runs.append({**selected, "manifest": file_record(manifest_path)})
    cohort = {
        "schema": "openvins-health-physical-fault-cohort-preflight-v1",
        "prepare_only": True,
        "created_before_any_fault_result": True,
        "fault_result_viewed": False,
        "test_set_tuning_allowed": False,
        "workload": {
            "simulation_duration_ns": 25_000_000_000,
            "physics_step_ns": 1_000_000,
            "imu_hz": 250,
            "rgbd_hz": 10,
            "rgbd_size": [160, 120],
            "motion_geometry": "supported-ready-v1/native-beginning-zupt-v1",
        },
        "profile": PROFILE,
        "runs": runs,
        "truth_used_online": False,
        "odometry_published": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(output / "fault-cohort-manifest.json", cohort)
    return cohort


def main(argv=None):
    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "source-study", "source-audit", "health-binary", "capture-script", "python"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    values = vars(parser.parse_args(argv))
    values.pop("prepare_only")
    print(json.dumps(prepare(**values, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
