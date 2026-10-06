"""Build a prepare-only package for one qualified OpenVINS lazy mapping."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from tools.benchmark.audit_openvins_lazy_runtime_closure import audit as closure_audit
from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.supported_heartbeat_gauge_preflight import (
    EXPECTED_PROFILES,
    EXPECTED_WORKLOAD,
    _study_args,
)
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy

PACKAGE_ARCHIVE_SHA256 = "3de9b639d4abe5d8f0e0adbb7e26e32bf9de9473b19155d76a3a24c88b62cfea"
UPSTREAM_COMMIT = "8b829acc65569019edb896c5150d427f288e8aba"
PACKAGE_VERSION = "2021.11.0-2ubuntu2"
OUTPUT_NAMES = {
    "execution-contract.json",
    "lazy-runtime-contract.json",
    "runtime-binding-v3.json",
    "study-manifest.json",
    "trajectory-gauge-policy.json",
}
PROBE_NAMES = {
    "states.jsonl", "fast.jsonl", "native.log", "native-requests.jsonl",
    "native-acks.jsonl", "native-session.json", "maps-before.json",
    "maps-after.json", "probe-result.json",
}
FALSE_CLAIMS = (
    "runtime_closure_qualified", "estimator_health_qualified",
    "physical_execution_qualified", "vio_accuracy_qualified", "fusion_eligible", "flight_ready",
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _record(path):
    return file_record(Path(path).resolve(strict=True))


def _exact_files(directory, expected, label):
    actual = {path.name for path in Path(directory).iterdir()}
    if actual != set(expected):
        raise ValueError(f"{label} member set differs")


def lazy_code_paths():
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "tools/benchmark/openvins_lazy_runtime_closure.py",
        root / "tools/benchmark/audit_openvins_lazy_runtime_closure.py",
    ]
    return [str(path.resolve(strict=True)) for path in paths]


def validate_lazy_source(lazy_study, lazy_audit, package_archive, *, closure_auditor=closure_audit):
    root = Path(lazy_study).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("lazy study must be a directory")
    _exact_files(root, {"provenance.json", "probe"}, "lazy study")
    probe_root = root / "probe"
    if not probe_root.is_dir():
        raise ValueError("lazy probe directory missing")
    _exact_files(probe_root, PROBE_NAMES, "lazy probe")

    recomputed = closure_auditor(root)
    stored = read_declaration(lazy_audit)
    if (not _typed_equal(stored, recomputed) or stored.get("failures") != []
            or stored.get("lazy_mapping_qualified") is not True):
        raise ValueError("lazy source audit is not an exact passing recomputation")
    for key in FALSE_CLAIMS:
        if key in stored and stored.get(key) is not False:
            raise ValueError("lazy audit overclaim: " + key)

    provenance = read_declaration(root / "provenance.json")
    probe = read_declaration(probe_root / "probe-result.json")
    if (provenance.get("schema") != "openvins-lazy-runtime-provenance-v1"
            or probe.get("schema") != "openvins-lazy-runtime-probe-v1"
            or probe.get("probe_qualified") is not True
            or probe.get("lazy_mapping_qualified") is not True):
        raise ValueError("lazy study schema or qualification")
    for document in (provenance, probe):
        for key in FALSE_CLAIMS:
            if key in document and document.get(key) is not False:
                raise ValueError("lazy source overclaim: " + key)
    if provenance.get("ordinary_elf_closure_contains_allocator") is not False:
        raise ValueError("allocator must remain outside ordinary ELF closure")
    package = provenance.get("package_relation")
    if (type(package) is not dict or package.get("source") != "onetbb"
            or package.get("version") != PACKAGE_VERSION
            or package.get("tbb_package") != "libtbb12"
            or package.get("allocator_package") != "libtbbmalloc2"):
        raise ValueError("unexpected oneTBB package relation")
    upstream = provenance.get("upstream")
    if (type(upstream) is not dict or upstream.get("commit") != UPSTREAM_COMMIT
            or upstream.get("license") != "Apache-2.0"):
        raise ValueError("unexpected oneTBB upstream identity")
    files = provenance.get("files")
    roles = {"binary", "config", "tbb", "allocator", "allocator_source", "license"}
    if type(files) is not dict or set(files) != roles:
        raise ValueError("lazy provenance file roles")
    for role, record in files.items():
        if _record(record["requested"]) != record:
            raise ValueError("lazy provenance file drift: " + role)
    added = probe.get("added")
    allocator = files["allocator"]
    expected_mapping = {
        "path": allocator["resolved"],
        "device": added[0].get("device") if type(added) is list and len(added) == 1 else None,
        "inode": added[0].get("inode") if type(added) is list and len(added) == 1 else None,
    }
    if type(added) is not list or added != [expected_mapping] or expected_mapping["inode"] != allocator["identity"]["inode"]:
        raise ValueError("lazy allocator mapping identity")

    archive = Path(package_archive).resolve(strict=True)
    if _sha(archive) != PACKAGE_ARCHIVE_SHA256:
        raise ValueError("fixed allocator package archive hash mismatch")
    audit_path = Path(lazy_audit).resolve(strict=True)
    source_paths = [root / "provenance.json", *sorted(probe_root.iterdir()), audit_path, archive]
    source_paths += [Path(path) for path in lazy_code_paths()]
    source_paths += [Path(record["resolved"]) for record in files.values()]
    unique = sorted({str(Path(path).resolve(strict=True)) for path in source_paths})
    source_records = [_record(path) for path in unique]
    return {
        "schema": "openvins-lazy-runtime-prepare-contract-v1",
        "source_study": str(root),
        "source_audit": _record(audit_path),
        "source_records": source_records,
        "expected_mapping": expected_mapping,
        "allocator": allocator,
        "package_archive": _record(archive),
        "package_relation": copy.deepcopy(package),
        "upstream": copy.deepcopy(upstream),
        "trigger": "first_acknowledged_imu",
        "ordinary_elf_closure_contains_allocator": False,
        "lazy_mapping_qualified": True,
        "runtime_closure_qualified": False,
        "estimator_health_qualified": False,
        "physical_execution_qualified": False,
        "vio_accuracy_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def _load_preflight(source_study, policy_validator=validate_trajectory_gauge_policy):
    root = Path(source_study).resolve(strict=True)
    names = {
        "runtime-binding-v3.json", "execution-contract.json", "study-manifest.json",
        "trajectory-gauge-policy.json", "preflight-audit-prelaunch.json",
    }
    if not root.is_dir() or any(not (root / name).is_file() for name in names):
        raise ValueError("supported preflight source is incomplete")
    binding = read_declaration(root / "runtime-binding-v3.json")
    contract = read_declaration(root / "execution-contract.json")
    manifest = read_declaration(root / "study-manifest.json")
    policy = read_declaration(root / "trajectory-gauge-policy.json")
    source_audit = read_declaration(root / "preflight-audit-prelaunch.json")
    policy_validator(policy)
    if (binding.get("schema") != "capture-resource-binding-v3"
            or contract.get("schema") != "capture-execution-v3"
            or manifest.get("schema") != "supported-heartbeat-gauge-preflight-v1"
            or manifest.get("prepare_only") is not True
            or source_audit.get("preflight_qualified") is not True
            or source_audit.get("failures") != []):
        raise ValueError("supported preflight source qualification")
    for key, value in EXPECTED_WORKLOAD.items():
        if not _typed_equal(contract.get(key), value):
            raise ValueError("source workload mismatch: " + key)
    if not _typed_equal(contract.get("profiles"), EXPECTED_PROFILES):
        raise ValueError("source profiles mismatch")
    if not _typed_equal(manifest.get("execution_contract"), contract):
        raise ValueError("source manifest execution contract mismatch")
    if contract.get("launch_environment") != derive_launch_environment(binding):
        raise ValueError("source launch environment mismatch")
    source_false_claims = (
        "runtime_closure_qualified", "vio_accuracy_qualified", "estimator_health_qualified",
        "fusion_eligible", "flight_ready", "physical_run_completed",
    )
    if any(manifest.get(key) is not False for key in source_false_claims):
        raise ValueError("source downstream claim must remain false")
    baseline = snapshot(binding["inventory"])
    if not _typed_equal(binding.get("baseline", {}).get("files"), baseline["files"]):
        raise ValueError("source runtime binding baseline drift")
    return root, names, binding, contract, policy


def _add_new_role(inventory, role, paths):
    if role in inventory:
        raise ValueError("lazy integration role collision: " + role)
    known = {str(Path(path).resolve(strict=True)) for values in inventory.values() for path in values}
    added = []
    for path in paths:
        resolved = str(Path(path).resolve(strict=True))
        if resolved not in known:
            known.add(resolved)
            added.append(resolved)
    if added:
        inventory[role] = sorted(added)
    return added


def prepare_study(output, *, source_study, lazy_study, lazy_audit, package_archive,
                  capture_script, python, resources, closure_auditor=closure_audit,
                  policy_validator=validate_trajectory_gauge_policy):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError("destination exists: " + str(output))
    source_root, source_names, source_binding, source_contract, policy = _load_preflight(
        source_study, policy_validator)
    lazy_contract = validate_lazy_source(
        lazy_study, lazy_audit, package_archive, closure_auditor=closure_auditor)

    output.mkdir(parents=True)
    policy_path = output / "trajectory-gauge-policy.json"
    shutil.copy2(source_root / "trajectory-gauge-policy.json", policy_path)
    policy_validator(read_declaration(policy_path))
    lazy_path = output / "lazy-runtime-contract.json"
    write_manifest(lazy_path, lazy_contract)

    binding = copy.deepcopy(source_binding)
    inventory = binding["inventory"]
    inventory["runtime:trajectory-gauge-policy"] = [str(policy_path.resolve())]
    source_paths = [source_root / name for name in sorted(source_names)]
    _add_new_role(inventory, "runtime:lazy-prepare-source", source_paths)
    _add_new_role(inventory, "runtime:openvins-lazy-evidence",
                  [record["resolved"] for record in lazy_contract["source_records"]])
    _add_new_role(inventory, "runtime:openvins-lazy-contract", [lazy_path])
    declared = {str(Path(path).resolve(strict=True)) for values in inventory.values() for path in values}
    if lazy_contract["allocator"]["resolved"] not in declared:
        raise ValueError("allocator absent from prospective runtime inventory")
    binding["baseline"] = snapshot(inventory)

    binding_path = output / "runtime-binding-v3.json"
    execution_path = output / "execution-contract.json"
    args = _study_args(output / "capture-v1", source_contract, policy_path, binding_path, execution_path)
    environment = derive_launch_environment(binding)
    contract = execution_contract(args, environment)
    write_manifest(binding_path, binding)
    write_manifest(execution_path, contract)
    command = declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment)
    source_records = [_record(path) for path in source_paths]
    manifest = {
        "schema": "openvins-lazy-runtime-prepare-v1",
        "prepare_only": True,
        "source_study": str(source_root),
        "source_records": source_records,
        "lazy_contract": _record(lazy_path),
        "runtime_binding": str(binding_path.resolve()),
        "execution_contract": contract,
        "trajectory_gauge_policy": str(policy_path.resolve()),
        "command": command,
        "physical_execution_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
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
    parser.add_argument("--lazy-study", type=Path, required=True)
    parser.add_argument("--lazy-audit", type=Path, required=True)
    parser.add_argument("--package-archive", type=Path, required=True)
    parser.add_argument("--capture-script", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    from tools.benchmark.capture_disarmed_sensors import active_resources

    result = prepare_study(
        args.output, source_study=args.source_study, lazy_study=args.lazy_study,
        lazy_audit=args.lazy_audit, package_archive=args.package_archive,
        capture_script=args.capture_script, python=args.python, resources=active_resources())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "OUTPUT_NAMES", "PACKAGE_ARCHIVE_SHA256", "PROBE_NAMES", "lazy_code_paths",
    "prepare_study", "validate_lazy_source",
]
