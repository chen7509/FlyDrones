"""Prepare, but never launch, the corrected estimator-aware study-v3 package."""

from __future__ import annotations

import copy
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import (
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import (
    FALSE_CLAIMS,
    NEW_PROFILE,
    _add_missing,
)
from tools.benchmark.estimator_aware_readiness_preflight import (
    OUTPUT_NAMES as SOURCE_NAMES,
)
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

OUTPUT_NAMES = set(SOURCE_NAMES) | {"physical-refusal-contract.json"}
SOURCE_POST_RUN_NAMES = {
    "capture-v1.supervisor-environment.json",
    "capture-v1.supervisor-events.jsonl",
}
MAX_SOURCE_SIM_LEAD_NS = 1_000_000
CODE_PATHS = (
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/renderer_first_step_probe.py",
    "tools/benchmark/renderer_first_step_study.py",
    "tools/benchmark/audit_renderer_first_step_probe.py",
    "tools/benchmark/estimator_physical_refusal_preflight.py",
    "tools/benchmark/audit_estimator_physical_refusal_preflight.py",
)


def _record(path):
    return file_record(Path(path).resolve(strict=True))


def code_paths():
    root = Path(__file__).resolve().parents[2]
    return [str((root / path).resolve(strict=True)) for path in CODE_PATHS]


def validate_source_package(source, audit_path, archive_path):
    source = Path(source).resolve(strict=True)
    if {path.name for path in source.iterdir() if path.is_file()} != (
        set(SOURCE_NAMES) | SOURCE_POST_RUN_NAMES
    ):
        raise ValueError("source study file set differs")
    audit = read_declaration(audit_path)
    if (
        audit.get("schema") != "estimator-aware-readiness-preflight-audit-v1"
        or audit.get("failures") != []
        or audit.get("prepare_qualified") is not True
    ):
        raise ValueError("source prepare audit not qualified")
    archive = Path(archive_path).resolve(strict=True)
    prefix = "results/estimator-aware-readiness-preflight-dev-1701/study-v2/"
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("source archive CRC failure")
        for name in SOURCE_NAMES:
            if bundle.read(prefix + name) != (source / name).read_bytes():
                raise ValueError("source archive member differs: " + name)
        if bundle.read("results/estimator-aware-readiness-preflight-dev-1701/audit-v2.json") != Path(audit_path).read_bytes():
            raise ValueError("source archive audit differs")
    manifest = read_declaration(source / "study-manifest.json")
    binding = read_declaration(source / "runtime-binding-v3.json")
    execution = read_declaration(source / "execution-contract.json")
    if (
        manifest.get("schema") != "estimator-aware-readiness-preflight-v1"
        or manifest.get("prepare_only") is not True
        or execution.get("profiles", {}).get("source_fanout_profile") != NEW_PROFILE
        or binding.get("schema") != "capture-resource-binding-v3"
    ):
        raise ValueError("source study schema or profile")
    return source, binding, execution


def validate_failed_capture(capture):
    capture = Path(capture).resolve(strict=True)
    result = read_declaration(capture / "result.json")
    if (
        result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 10_000_000
        or result.get("motion", {}).get("active_steps") != 0
        or result.get("motion", {}).get("support_steps") != 0
        or result.get("motion", {}).get("absolute_impulse_ns") != 0.0
        or result.get("source_fanout", {}).get("fusion_eligible") is not False
        or result.get("px4_exit_code") != -9
    ):
        raise ValueError("retained physical refusal differs")
    errors = result.get("errors", [])
    if not any("process mapping not covered" in value for value in errors) or not any(
        "future acknowledgement source" in value for value in errors
    ):
        raise ValueError("retained refusal causes missing")
    return capture, result


def validate_probe(probe, probe_audit):
    probe = Path(probe).resolve(strict=True)
    result = read_declaration(probe / "result.json")
    audit = read_declaration(probe_audit)
    if (
        result.get("status") != "probe_completed"
        or result.get("runtime_closure_qualified") is not True
        or result.get("mapping", {}).get("cache_absent") is not True
        or len(result.get("mapping", {}).get("historical_additions", [])) != 23
        or audit.get("failures") != []
        or audit.get("probe_qualified") is not True
        or audit.get("isolated_renderer_mapping_closure_qualified") is not True
        or audit.get("full_capture_runtime_closure_qualified") is not False
    ):
        raise ValueError("renderer probe is not narrowly qualified")
    return probe, result, audit


def augment_binding(binding, *, renderer_libraries, evidence_paths, contract_path):
    binding = copy.deepcopy(binding)
    environment = binding.get("environment")
    if type(environment) is not dict or environment.get("MESA_SHADER_CACHE_DISABLE") not in (None, "true"):
        raise ValueError("binding Mesa environment conflicts")
    environment["MESA_SHADER_CACHE_DISABLE"] = "true"
    inventory = binding["inventory"]
    _add_missing(
        inventory, "runtime:renderer-first-step-libraries",
        [row["path"] for row in renderer_libraries],
    )
    _add_missing(inventory, "runtime:physical-refusal-code", code_paths())
    _add_missing(inventory, "runtime:physical-refusal-contract", [contract_path])
    _add_missing(inventory, "evidence:physical-refusal", evidence_paths)
    binding["baseline"] = snapshot(inventory)
    return binding


def prepare_study(output, *, source_study, source_audit, source_archive, failed_capture,
                  probe, probe_audit, capture_script, python, resources):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError(str(output))
    source, source_binding, source_execution = validate_source_package(
        source_study, source_audit, source_archive,
    )
    failed_capture, failed_result = validate_failed_capture(failed_capture)
    probe, probe_result, _ = validate_probe(probe, probe_audit)
    output.mkdir(parents=True)
    for name in ("trajectory-gauge-policy.json", "lazy-runtime-contract.json", "estimator-readiness-contract.json"):
        shutil.copy2(source / name, output / name)

    evidence_paths = [
        failed_capture / "result.json",
        failed_capture / "runtime-maps-postfirststep.json",
        failed_capture / "runtime-maps-postfirststep.txt",
        failed_capture / "runtime-binding-pre.json",
        failed_capture.with_name(failed_capture.name + ".supervisor-events.jsonl"),
        probe / "result.json", probe / "maps-before.txt", probe / "maps-after.txt",
        probe / "supervisor.json", probe.with_name(probe.name + ".launch.json"),
        probe.with_name(probe.name + ".supervisor-environment.json"),
        probe.with_name(probe.name + ".supervisor-events.jsonl"), Path(probe_audit),
        Path(source_audit), Path(source_archive),
    ]
    contract_path = output / "physical-refusal-contract.json"
    contract = {
        "schema": "estimator-physical-refusal-contract-v1",
        "source_study": str(source),
        "source_audit": _record(source_audit),
        "source_archive": _record(source_archive),
        "failed_capture": _record(failed_capture / "result.json"),
        "failed_end_sim_ns": failed_result["end_sim_ns"],
        "failed_force_steps": failed_result["motion"]["active_steps"],
        "timestamp_contract": {
            "sim_age_field_required": True,
            "max_source_sim_lead_ns": MAX_SOURCE_SIM_LEAD_NS,
            "derived_age_must_match": True,
            "future_wall_arrival_rejected": True,
            "camera_ack_after_source_sample_rejected": True,
        },
        "renderer_probe": _record(probe / "result.json"),
        "renderer_probe_audit": _record(probe_audit),
        "renderer_historical_additions": probe_result["mapping"]["historical_additions"],
        "renderer_baseline_additions": probe_result["mapping"]["baseline_additions"],
        "mesa_shader_cache_disabled": True,
        "truth_used": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(contract_path, contract)

    binding = augment_binding(
        source_binding, renderer_libraries=probe_result["mapping"]["historical_additions"],
        evidence_paths=evidence_paths, contract_path=contract_path,
    )
    binding_path = output / "runtime-binding-v3.json"
    execution_path = output / "execution-contract.json"
    policy_path = output / "trajectory-gauge-policy.json"
    args = _study_args(output / "capture-v1", source_execution, policy_path, binding_path, execution_path)
    environment = derive_launch_environment(binding)
    execution = execution_contract(args, environment)
    write_manifest(binding_path, binding)
    write_manifest(execution_path, execution)
    command = declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment)
    manifest = {
        "schema": "estimator-physical-refusal-preflight-v1",
        "prepare_only": True,
        "source_study": str(source),
        "source_records": [_record(source / name) for name in sorted(SOURCE_NAMES)],
        "physical_refusal_contract": _record(contract_path),
        "runtime_binding": str(binding_path.resolve()),
        "execution_contract": execution,
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
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-study", required=True, type=Path)
    parser.add_argument("--source-audit", required=True, type=Path)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--failed-capture", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--probe-audit", required=True, type=Path)
    parser.add_argument("--capture-script", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    from tools.benchmark.capture_disarmed_sensors import active_resources

    arguments = vars(args)
    arguments.pop("prepare_only")
    result = prepare_study(**arguments, resources=active_resources())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
