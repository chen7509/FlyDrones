"""Build, but never execute, a physical retry bound to startup-preflight evidence."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.estimator_physical_refusal_preflight import OUTPUT_NAMES as SOURCE_NAMES
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

OUTPUT_NAMES = set(SOURCE_NAMES) | {"startup-authorization-contract.json"}
COPY_NAMES = (
    "trajectory-gauge-policy.json", "lazy-runtime-contract.json",
    "estimator-readiness-contract.json", "physical-refusal-contract.json",
)
CODE_NAMES = (
    "tools/benchmark/capture_contract.py", "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/runtime_resource_binding.py", "tools/benchmark/physical_retry_preflight.py",
    "tools/benchmark/audit_physical_retry_preflight.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def validate_startup(startup, audit_path):
    startup = Path(startup).resolve(strict=True)
    result = read_declaration(startup / "result.json")
    supervisor = read_declaration(startup / "supervisor.json")
    audit = read_declaration(audit_path)
    forbidden = ("process.json", "px4.log", "px4-ulog-manifest.json", "motion-profile.json")
    if (
        result.get("status") != "capture_completed"
        or result.get("startup_preflight_only") is not True
        or result.get("startup_preflight_completed") is not True
        or result.get("errors") != []
        or result.get("runtime_binding", {}).get("pre_recorded") is not True
        or result.get("runtime_binding", {}).get("declared_files_stable") is not True
        or result.get("runtime_binding", {}).get("local_file_graph_verified") is not True
        or result.get("runtime_binding", {}).get("runtime_mapping_coverage_verified") is not False
        or supervisor.get("worker_exit") != 0
        or supervisor.get("cleanup", {}).get("graceful_group_cleanup_verified") is not True
        or audit.get("failures") != []
        or audit.get("startup_preflight_qualified") is not True
        or any((startup / name).exists() for name in forbidden)
    ):
        raise ValueError("startup preflight not qualified")
    return startup, result


def prepare(output, *, source, source_audit, startup, startup_audit, capture_script, python, resources):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    source = Path(source).resolve(strict=True)
    expected_files = set(SOURCE_NAMES) | {
        "startup-preflight-v1.supervisor-environment.json",
        "startup-preflight-v1.supervisor-events.jsonl",
    }
    if {p.name for p in source.iterdir() if p.is_file()} != expected_files:
        raise ValueError("source package members differ")
    source_check = read_declaration(source_audit)
    if source_check.get("failures") != [] or source_check.get("prepare_qualified") is not True:
        raise ValueError("source package audit failed")
    startup, startup_result = validate_startup(startup, startup_audit)
    source_manifest = read_declaration(source / "study-manifest.json")
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")
    if source_manifest.get("prepare_only") is not True:
        raise ValueError("source package is not prepare-only")
    output.mkdir(parents=True)
    for name in COPY_NAMES:
        shutil.copy2(source / name, output / name)
    contract_path = output / "startup-authorization-contract.json"
    evidence = [
        startup / "result.json", startup / "supervisor.json", startup / "runtime-binding-pre.json",
        startup / "runtime-binding-post.json", startup / "resource-graph.json",
        startup.with_name(startup.name + ".supervisor-environment.json"),
        startup.with_name(startup.name + ".supervisor-events.jsonl"), Path(startup_audit), Path(source_audit),
    ]
    contract = {
        "schema": "capture-startup-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "startup_result": record(startup / "result.json"),
        "startup_audit": record(startup_audit),
        "startup_phases": startup_result["runtime_binding"]["phases"],
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(contract_path, contract)
    binding = copy.deepcopy(source_binding)
    root = Path(__file__).resolve().parents[2]
    _add_missing(binding["inventory"], "runtime:physical-retry-code", [str((root / n).resolve(strict=True)) for n in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:startup-authorization", [contract_path])
    _add_missing(binding["inventory"], "evidence:startup-preflight", evidence)
    binding["baseline"] = snapshot(binding["inventory"])
    binding = validate_binding(binding)
    binding_path = output / "runtime-binding-v3.json"
    execution_path = output / "execution-contract.json"
    policy_path = output / "trajectory-gauge-policy.json"
    args = _study_args(output / "capture-v1", source_execution, policy_path, binding_path, execution_path)
    environment = derive_launch_environment(binding)
    execution = execution_contract(args, environment)
    write_manifest(binding_path, binding)
    write_manifest(execution_path, execution)
    manifest = {
        "schema": "estimator-physical-retry-preflight-v1", "prepare_only": True,
        "source": str(source), "source_manifest": record(source / "study-manifest.json"),
        "startup_authorization": record(contract_path), "execution_contract": execution,
        "runtime_binding": str(binding_path.resolve()), "future_destination": str((output / "capture-v1").resolve()),
        "command": declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment),
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    import argparse

    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "source", "source-audit", "startup", "startup-audit", "capture-script", "python"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    values = vars(parser.parse_args(argv))
    values.pop("prepare_only")
    print(json.dumps(prepare(**values, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
