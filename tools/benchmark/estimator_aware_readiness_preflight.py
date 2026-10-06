"""Prepare, but never launch, one estimator-aware supported-motion study."""

from __future__ import annotations

import copy
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy

SOURCE_NAMES = {
    "execution-contract.json",
    "lazy-runtime-contract.json",
    "runtime-binding-v3.json",
    "study-manifest.json",
    "trajectory-gauge-policy.json",
}
OUTPUT_NAMES = SOURCE_NAMES | {"estimator-readiness-contract.json"}
OLD_PROFILE = "ready-shadow-heartbeat-v1"
NEW_PROFILE = "ready-shadow-heartbeat-estimator-v1"
FALSE_CLAIMS = (
    "physical_execution_qualified",
    "runtime_mapping_coverage_verified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "flight_ready",
)
CODE_PATHS = (
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/journaled_heartbeat_lane.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/readiness_anchor.py",
    "tools/benchmark/ready_shadow_fanout.py",
)


def _record(path):
    return file_record(Path(path).resolve(strict=True))


def estimator_code_paths():
    root = Path(__file__).resolve().parents[2]
    return [str((root / relative).resolve(strict=True)) for relative in CODE_PATHS]


def _exact_files(root, expected, label):
    if {path.name for path in Path(root).iterdir()} != set(expected):
        raise ValueError(label + " member set differs")


def _validate_source_archive(source_root, source_audit, source_archive):
    archive = Path(source_archive).resolve(strict=True)
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("source evidence archive CRC failure")
        names = set(package.namelist())
        expected = {"study-v1/" + name for name in SOURCE_NAMES} | {"verification/audit-v1.json"}
        if not expected <= names:
            raise ValueError("source evidence archive members missing")
        for name in SOURCE_NAMES:
            if package.read("study-v1/" + name) != (source_root / name).read_bytes():
                raise ValueError("source evidence archive differs: " + name)
        if package.read("verification/audit-v1.json") != Path(source_audit).read_bytes():
            raise ValueError("source audit differs from evidence archive")
    return _record(archive)


def _load_source(source_study, source_audit, source_archive, *, source_auditor=None,
                 policy_validator=validate_trajectory_gauge_policy):
    root = Path(source_study).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source study must be a directory")
    _exact_files(root, SOURCE_NAMES, "source study")
    if (root / "capture-v1").exists():
        raise ValueError("source capture destination exists")
    stored_audit = read_declaration(source_audit)
    archive_record = _validate_source_archive(root, source_audit, source_archive)
    if (stored_audit.get("schema") != "openvins-lazy-runtime-prepare-audit-v1"
            or stored_audit.get("failures") != []
            or stored_audit.get("prepare_qualified") is not True):
        raise ValueError("source audit is not passing archived evidence")
    if source_auditor is not None:
        recomputed_audit = source_auditor(root)
        if not _typed_equal(stored_audit, recomputed_audit):
            raise ValueError("source audit differs from injected recomputation")
    binding = read_declaration(root / "runtime-binding-v3.json")
    contract = read_declaration(root / "execution-contract.json")
    manifest = read_declaration(root / "study-manifest.json")
    policy = read_declaration(root / "trajectory-gauge-policy.json")
    policy_validator(policy)
    if (binding.get("schema") != "capture-resource-binding-v3"
            or contract.get("schema") != "capture-execution-v3"
            or manifest.get("schema") != "openvins-lazy-runtime-prepare-v1"
            or manifest.get("prepare_only") is not True
            or not _typed_equal(manifest.get("execution_contract"), contract)):
        raise ValueError("source package schema or execution")
    if contract.get("profiles", {}).get("source_fanout_profile") != OLD_PROFILE:
        raise ValueError("source fan-out profile")
    for key in FALSE_CLAIMS:
        if manifest.get(key) is not False:
            raise ValueError("source downstream overclaim: " + key)
    fresh = snapshot(binding.get("inventory"))
    source_baseline_current = _typed_equal(binding.get("baseline", {}).get("files"), fresh["files"])
    if contract.get("launch_environment") != derive_launch_environment(binding):
        raise ValueError("source launch environment drift")
    return root, binding, contract, policy, stored_audit, archive_record, source_baseline_current


def _add_missing(inventory, role, paths):
    if role in inventory:
        raise ValueError("inventory role collision: " + role)
    known = {str(Path(path).resolve(strict=True)) for values in inventory.values() for path in values}
    selected = []
    for path in paths:
        resolved = str(Path(path).resolve(strict=True))
        if resolved not in known:
            known.add(resolved)
            selected.append(resolved)
    if selected:
        inventory[role] = sorted(selected)


def readiness_contract(source_root, source_audit, source_archive):
    paths = estimator_code_paths()
    binding = read_declaration(Path(source_root) / "runtime-binding-v3.json")
    current = snapshot(binding["inventory"])
    return {
        "schema": "estimator-aware-readiness-contract-v1",
        "profile": NEW_PROFILE,
        "source_profile": OLD_PROFILE,
        "source_package": str(source_root),
        "source_audit": _record(source_audit),
        "source_archive": _record(source_archive),
        "source_historical_audit_archived": True,
        "source_baseline_current": _typed_equal(
            binding.get("baseline", {}).get("files"), current["files"]
        ),
        "code_records": [_record(path) for path in paths],
        "eligibility": {
            "source_readiness_required": True,
            "native_camera_ack_required": True,
            "internal_initialized_required": True,
            "ack_freshness_ns": 2_000_000_000,
            "future_anchor_offset_ns": 200_000_000,
            "startup_deadline_ns": 8_000_000_000,
            "first_evidence_immutable": True,
            "latest_evidence_refreshable": True,
        },
        "truth_used": False,
        "public_initialized_is_accuracy": False,
        "internal_initialized_is_accuracy": False,
        "quality_available": False,
        "reset_counter_available": False,
        "physical_execution_qualified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def prepare_study(output, *, source_study, source_audit, source_archive, capture_script, python,
                  resources, source_auditor=None,
                  policy_validator=validate_trajectory_gauge_policy):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError("destination exists: " + str(output))
    source_root, source_binding, source_contract, policy, _, _, _ = _load_source(
        source_study, source_audit, source_archive, source_auditor=source_auditor,
        policy_validator=policy_validator,
    )
    output.mkdir(parents=True)
    policy_path = output / "trajectory-gauge-policy.json"
    lazy_path = output / "lazy-runtime-contract.json"
    shutil.copy2(source_root / "trajectory-gauge-policy.json", policy_path)
    shutil.copy2(source_root / "lazy-runtime-contract.json", lazy_path)
    policy_validator(read_declaration(policy_path))
    if not _typed_equal(read_declaration(policy_path), policy):
        raise ValueError("trajectory policy copy differs")

    readiness_path = output / "estimator-readiness-contract.json"
    readiness = readiness_contract(source_root, source_audit, source_archive)
    write_manifest(readiness_path, readiness)

    binding = copy.deepcopy(source_binding)
    inventory = binding["inventory"]
    inventory["runtime:trajectory-gauge-policy"] = [str(policy_path.resolve())]
    inventory["runtime:openvins-lazy-contract"] = [str(lazy_path.resolve())]
    _add_missing(inventory, "runtime:estimator-aware-readiness-code", estimator_code_paths())
    _add_missing(inventory, "runtime:estimator-aware-readiness-contract", [readiness_path])
    source_paths = [source_root / name for name in sorted(SOURCE_NAMES)] + [
        Path(source_audit), Path(source_archive),
    ]
    _add_missing(inventory, "evidence:estimator-aware-source", source_paths)
    binding["baseline"] = snapshot(inventory)

    binding_path = output / "runtime-binding-v3.json"
    execution_path = output / "execution-contract.json"
    args = _study_args(output / "capture-v1", source_contract, policy_path, binding_path, execution_path)
    args.source_fanout_profile = NEW_PROFILE
    environment = derive_launch_environment(binding)
    contract = execution_contract(args, environment)
    write_manifest(binding_path, binding)
    write_manifest(execution_path, contract)
    command = declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment)
    manifest = {
        "schema": "estimator-aware-readiness-preflight-v1",
        "prepare_only": True,
        "source_study": str(source_root),
        "source_records": [_record(path) for path in source_paths],
        "readiness_contract": _record(readiness_path),
        "runtime_binding": str(binding_path.resolve()),
        "execution_contract": contract,
        "trajectory_gauge_policy": str(policy_path.resolve()),
        "future_destination": str((output / "capture-v1").resolve()),
        "command": command,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-study", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--capture-script", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    from tools.benchmark.capture_disarmed_sensors import active_resources

    result = prepare_study(
        args.output,
        source_study=args.source_study,
        source_audit=args.source_audit,
        source_archive=args.source_archive,
        capture_script=args.capture_script,
        python=args.python,
        resources=active_resources(),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["OUTPUT_NAMES", "prepare_study"]
