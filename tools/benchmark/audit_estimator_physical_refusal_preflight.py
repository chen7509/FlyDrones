"""Independently audit the corrected estimator-aware study-v3 prepare package."""

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
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.estimator_physical_refusal_preflight import (
    FALSE_CLAIMS,
    MAX_SOURCE_SIM_LEAD_NS,
    OUTPUT_NAMES,
    SOURCE_NAMES,
    _record,
    augment_binding,
    validate_failed_capture,
    validate_probe,
    validate_source_package,
)
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args


def _require(value, failures, label):
    if not value:
        failures.append(label)


def audit(root):
    root = Path(root).resolve(strict=True)
    failures = []
    try:
        _require({path.name for path in root.iterdir()} == OUTPUT_NAMES, failures, "output members")
        manifest = read_declaration(root / "study-manifest.json")
        contract = read_declaration(root / "physical-refusal-contract.json")
        binding = read_declaration(root / "runtime-binding-v3.json")
        execution = read_declaration(root / "execution-contract.json")
    except Exception as exc:
        failures.append("read:" + repr(exc))
        manifest, contract, binding, execution = {}, {}, {}, {}

    _require(manifest.get("schema") == "estimator-physical-refusal-preflight-v1", failures, "manifest schema")
    _require(manifest.get("prepare_only") is True, failures, "prepare only")
    _require(contract.get("schema") == "estimator-physical-refusal-contract-v1", failures, "contract schema")
    _require(contract.get("timestamp_contract", {}).get("max_source_sim_lead_ns") == MAX_SOURCE_SIM_LEAD_NS,
             failures, "timestamp lead")
    _require(contract.get("mesa_shader_cache_disabled") is True, failures, "Mesa cache declaration")
    _require(not (root / "capture-v1").exists(), failures, "capture destination exists")
    for key in FALSE_CLAIMS:
        _require(manifest.get(key) is False and contract.get(key) is False, failures, "overclaim:" + key)

    try:
        source, source_binding, source_execution = validate_source_package(
            manifest["source_study"], contract["source_audit"]["requested"],
            contract["source_archive"]["requested"],
        )
        failed_capture = Path(contract["failed_capture"]["requested"]).parent
        validate_failed_capture(failed_capture)
        probe_root = Path(contract["renderer_probe"]["requested"]).parent
        probe_audit = contract["renderer_probe_audit"]["requested"]
        _, probe_result, _ = validate_probe(probe_root, probe_audit)
        evidence_paths = [
            failed_capture / "result.json", failed_capture / "runtime-maps-postfirststep.json",
            failed_capture / "runtime-maps-postfirststep.txt", failed_capture / "runtime-binding-pre.json",
            failed_capture.with_name(failed_capture.name + ".supervisor-events.jsonl"),
            probe_root / "result.json", probe_root / "maps-before.txt", probe_root / "maps-after.txt",
            probe_root / "supervisor.json", probe_root.with_name(probe_root.name + ".launch.json"),
            probe_root.with_name(probe_root.name + ".supervisor-environment.json"),
            probe_root.with_name(probe_root.name + ".supervisor-events.jsonl"), Path(probe_audit),
            Path(contract["source_audit"]["requested"]), Path(contract["source_archive"]["requested"]),
        ]
        expected_binding = augment_binding(
            source_binding, renderer_libraries=probe_result["mapping"]["historical_additions"],
            evidence_paths=evidence_paths, contract_path=root / "physical-refusal-contract.json",
        )
        started = binding.get("baseline", {}).get("started_monotonic_ns")
        ended = binding.get("baseline", {}).get("ended_monotonic_ns")
        _require(type(started) is int and type(ended) is int and ended >= started,
                 failures, "binding snapshot clock")
        expected_binding["baseline"]["started_monotonic_ns"] = started
        expected_binding["baseline"]["ended_monotonic_ns"] = ended
        _require(_typed_equal(binding, expected_binding), failures, "binding recomputation")
        _require(_typed_equal(binding["baseline"]["files"], snapshot(binding["inventory"])["files"]),
                 failures, "fresh binding baseline")
        environment = derive_launch_environment(binding)
        _require(environment.get("MESA_SHADER_CACHE_DISABLE") == "true", failures, "Mesa launch environment")
        args = _study_args(
            root / "capture-v1", source_execution, root / "trajectory-gauge-policy.json",
            root / "runtime-binding-v3.json", root / "execution-contract.json",
        )
        expected_execution = execution_contract(args, environment)
        _require(_typed_equal(execution, expected_execution), failures, "execution recomputation")
        for key in (
            "wall_budget_s", "supervisor_s", "simulation_duration_ns", "physics_step_ns",
            "imu_hz", "rgbd_hz", "rgbd_size", "estimator_run", "profiles", "inputs", "reference_sha256",
        ):
            _require(_typed_equal(execution.get(key), source_execution.get(key)), failures,
                     "execution changed:" + key)
        _require(
            {**source_execution["launch_environment"], "MESA_SHADER_CACHE_DISABLE": "true"}
            == execution["launch_environment"], failures, "unexpected launch environment change",
        )
        expected_command = declared_command(args, manifest["command"][0], manifest["command"][1], environment)
        _require(_typed_equal(manifest.get("command"), expected_command), failures, "command recomputation")
        _require(manifest.get("future_destination") == str((root / "capture-v1").resolve()),
                 failures, "future destination")
        _require(_typed_equal(manifest.get("execution_contract"), execution), failures, "manifest execution")
        _require(_typed_equal(manifest.get("physical_refusal_contract"),
                              _record(root / "physical-refusal-contract.json")), failures, "contract record")
        _require(_typed_equal(manifest.get("source_records"),
                              [_record(source / name) for name in sorted(SOURCE_NAMES)]), failures, "source records")
    except Exception as exc:
        failures.append("derived:" + repr(exc))

    return {
        "schema": "estimator-physical-refusal-preflight-audit-v1",
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
