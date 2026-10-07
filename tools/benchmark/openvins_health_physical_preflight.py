"""Freeze development and held-out physical OpenVINS health studies without running them."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import _add_missing
from tools.benchmark.runtime_resource_binding import validate_binding

PROFILE = "px4-d6f12ad-gate-floor-v1"
SOURCE_PROFILES = {
    "motion_profile": "supported-ready-v1",
    "physics_trace_profile": "substep-ready-v1",
    "reference_fault_profile": None,
    "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
    "motion_intent_profile": "native-beginning-zupt-v1",
}
CODE_PATHS = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/openvins_health_contract.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/openvins_health_physical_preflight.py",
    "tools/benchmark/audit_openvins_health_cohort.py",
)


def cohort_plan():
    return [
        {"run_id": "development-seed-27101", "role": "development", "seed": 27101},
        {"run_id": "held-out-seed-27111", "role": "held_out", "seed": 27111},
        {"run_id": "held-out-seed-27112", "role": "held_out", "seed": 27112},
        {"run_id": "held-out-seed-27113", "role": "held_out", "seed": 27113},
    ]


def run_args(*, output, source_contract, health_binary, policy_path, binding_path, execution_path, seed):
    profiles = source_contract["profiles"]
    inputs = source_contract["inputs"]
    return SimpleNamespace(
        output=Path(output),
        shadow_binary=Path(health_binary),
        shadow_config=Path(inputs["shadow_config"]),
        reference_module=Path(inputs["reference_module"]),
        reference_sha256=source_contract["reference_sha256"],
        reference_fault_profile=profiles["reference_fault_profile"],
        source_fanout_profile=profiles["source_fanout_profile"],
        motion_profile=profiles["motion_profile"],
        physics_trace_profile=profiles["physics_trace_profile"],
        motion_intent_profile=profiles["motion_intent_profile"],
        health_profile=PROFILE,
        simulation_seed=seed,
        trajectory_gauge_policy=Path(policy_path),
        execution_contract=Path(execution_path),
        runtime_binding=Path(binding_path),
        startup_preflight=False,
    )


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_source(source_study, source_audit):
    source = Path(source_study).resolve(strict=True)
    audit_path = Path(source_audit).resolve(strict=True)
    audit = read_declaration(audit_path)
    if (
        audit.get("failures") != []
        or audit.get("physical_execution_qualified") is not True
        or audit.get("vio_accuracy_screens_qualified") is not True
        or audit.get("fusion_eligible") is not False
    ):
        raise ValueError("source physical study is not a qualified closed-fusion baseline")
    contract = read_declaration(source / "execution-contract.json")
    binding = validate_binding(read_declaration(source / "runtime-binding-v3.json"))
    if contract.get("schema") != "capture-execution-v3" or contract.get("profiles") != SOURCE_PROFILES:
        raise ValueError("source physical execution profile differs")
    if contract.get("simulation_duration_ns") != 25_000_000_000:
        raise ValueError("source physical duration differs")
    if contract.get("physics_step_ns") != 1_000_000 or contract.get("imu_hz") != 250:
        raise ValueError("source physical sampling differs")
    if contract.get("rgbd_hz") != 10 or contract.get("rgbd_size") != [160, 120]:
        raise ValueError("source camera workload differs")
    if contract.get("inputs", {}).get("shadow_binary") not in binding["inventory"].get("runtime-root:openvins", []):
        raise ValueError("source OpenVINS binary is not bound")
    return source, audit_path, contract, binding


def prepare(output, *, source_study, source_audit, health_binary, capture_script, python, resources):
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
    plan = cohort_plan()
    output.mkdir(parents=True)
    runs = []
    for selected in plan:
        run_root = output / selected["run_id"]
        run_root.mkdir()
        policy_path = run_root / "trajectory-gauge-policy.json"
        shutil.copy2(source / "trajectory-gauge-policy.json", policy_path)
        binding = copy.deepcopy(source_binding)
        binding["inventory"]["runtime-root:openvins"] = [str(health_binary)]
        _add_missing(binding["inventory"], "runtime:openvins-health-code", code_paths)
        _add_missing(binding["inventory"], "evidence:openvins-health-source", [audit_path, source / "final-audit-v2.json"])
        binding["baseline"] = snapshot(binding["inventory"])
        binding = validate_binding(binding)
        binding_path = run_root / "runtime-binding-v3.json"
        execution_path = run_root / "execution-contract.json"
        args = run_args(
            output=run_root / "capture-v1",
            source_contract=source_contract,
            health_binary=health_binary,
            policy_path=policy_path,
            binding_path=binding_path,
            execution_path=execution_path,
            seed=selected["seed"],
        )
        environment = derive_launch_environment(binding)
        execution = execution_contract(args, environment)
        write_manifest(binding_path, binding)
        write_manifest(execution_path, execution)
        command = declared_command(args, python, capture_script, environment)
        manifest = {
            "schema": "openvins-health-physical-run-preflight-v1",
            "prepare_only": True,
            **selected,
            "source_study": str(source),
            "source_audit": file_record(audit_path),
            "health_binary": file_record(health_binary),
            "health_profile": PROFILE,
            "execution_contract": execution,
            "runtime_binding": str(binding_path.resolve()),
            "future_destination": str((run_root / "capture-v1").resolve()),
            "command": command,
            "held_out_results_viewed": False,
            "test_set_tuning_allowed": False,
            "physical_run_completed": False,
            "covariance_sim_domain_qualified": False,
            "fusion_eligible": False,
            "flight_ready": False,
        }
        manifest_path = run_root / "study-manifest.json"
        write_manifest(manifest_path, manifest)
        runs.append({**selected, "manifest": file_record(manifest_path)})
    cohort = {
        "schema": "openvins-health-physical-cohort-preflight-v1",
        "prepare_only": True,
        "created_before_any_cohort_result": True,
        "development_must_complete_before_held_out_dispatch": True,
        "held_out_results_viewed": False,
        "test_set_tuning_allowed": False,
        "motion_geometry": "supported-ready-v1/native-beginning-zupt-v1",
        "randomization_scope": "gz.math7 global seed; same geometry; full plugin RNG coverage unqualified",
        "profile": PROFILE,
        "source_study": file_record(source / "study-manifest.json"),
        "source_audit": file_record(audit_path),
        "health_binary": file_record(health_binary),
        "runs": runs,
        "covariance_sim_domain_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(output / "cohort-manifest.json", cohort)
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
