"""Build, but never execute, a causal-deadline-corrected physical retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.physical_retry_preflight import COPY_NAMES
from tools.benchmark.physical_retry_preflight import OUTPUT_NAMES as SOURCE_NAMES
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

OUTPUT_NAMES = set(SOURCE_NAMES) | {"deadline-correction-authorization.json"}
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/disarmed_sensor_provenance.py",
    "tools/benchmark/openvins_causal_input.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/ready_shadow_fanout.py",
    "tools/benchmark/causal_deadline_retry_preflight.py",
    "tools/benchmark/audit_causal_deadline_retry_preflight.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def validate_failed_attempt(capture, attempt_audit, completion):
    capture = Path(capture).resolve(strict=True)
    result = read_declaration(capture / "result.json")
    audit = read_declaration(attempt_audit)
    completed = read_declaration(completion)
    motion = result.get("motion", {})
    if (
        result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 10_000_000
        or "pending input exceeded wall wait" not in result.get("source_fanout", {}).get("failure", "")
        or motion.get("active_steps") != 0
        or motion.get("support_steps") != 0
        or motion.get("absolute_impulse_ns") != 0.0
        or result.get("eligible_for_vio_input") is not False
        or result.get("eligible_for_px4_fusion") is not False
        or result.get("px4_ulogs") != []
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "causal-input-wall-deadline-platform-scheduling-refusal"
        or audit.get("fruit_fly_policy_failure") is not False
        or completed.get("returncode") != 2
        or completed.get("resources_after") != []
    ):
        raise ValueError("failed attempt evidence not qualified")
    return result, audit


def validate_correction(correction_audit, correction_archive):
    audit = read_declaration(correction_audit)
    archive = Path(correction_archive).resolve(strict=True)
    if (
        audit.get("schema") != "causal-wall-deadline-audit-v3"
        or audit.get("failures") != []
        or audit.get("fixed_input_qualified") is not True
        or audit.get("limits_changed") is not False
        or audit.get("physical_run_performed") is not False
        or any(audit.get(key) is not False for key in FALSE_CLAIMS)
        or archive.stat().st_size <= 0
    ):
        raise ValueError("causal deadline correction not qualified")
    return audit, hashlib.sha256(archive.read_bytes()).hexdigest()


def prepare(
    output,
    *,
    source,
    source_audit,
    failed_capture,
    attempt_audit,
    completion,
    correction_audit,
    correction_archive,
    capture_script,
    python,
    resources,
):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    source = Path(source).resolve(strict=True)
    expected_files = set(SOURCE_NAMES) | {"capture-v1.supervisor-environment.json", "capture-v1.supervisor-events.jsonl"}
    if {p.name for p in source.iterdir() if p.is_file()} != expected_files or {p.name for p in source.iterdir() if p.is_dir()} != {
        "capture-v1"
    }:
        raise ValueError("source package members differ")
    source_check = read_declaration(source_audit)
    if source_check.get("failures") != [] or source_check.get("prepare_qualified") is not True:
        raise ValueError("source package audit failed")
    failed_capture = Path(failed_capture).resolve(strict=True)
    if failed_capture != (source / "capture-v1").resolve():
        raise ValueError("failed capture is not source destination")
    validate_failed_attempt(failed_capture, attempt_audit, completion)
    correction, correction_sha = validate_correction(correction_audit, correction_archive)
    source_manifest = read_declaration(source / "study-manifest.json")
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")
    if source_manifest.get("prepare_only") is not True or source_manifest.get("future_destination") != str(failed_capture):
        raise ValueError("source manifest does not identify failed capture")

    output.mkdir(parents=True)
    for name in (*COPY_NAMES, "startup-authorization-contract.json"):
        shutil.copy2(source / name, output / name)
    contract_path = output / "deadline-correction-authorization.json"
    contract = {
        "schema": "causal-deadline-correction-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "failed_result": record(failed_capture / "result.json"),
        "attempt_audit": record(attempt_audit),
        "completion": record(completion),
        "correction_audit": record(correction_audit),
        "correction_archive": {**record(correction_archive), "sha256": correction_sha},
        "fixed_input_qualified": correction["fixed_input_qualified"],
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(contract_path, contract)

    binding = copy.deepcopy(source_binding)
    root = Path(__file__).resolve().parents[2]
    _add_missing(binding["inventory"], "runtime:causal-deadline-retry-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:causal-deadline-authorization", [contract_path])
    _add_missing(
        binding["inventory"],
        "evidence:causal-deadline-correction",
        [attempt_audit, completion, correction_audit, correction_archive],
    )
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
        "schema": "causal-deadline-physical-retry-preflight-v1",
        "prepare_only": True,
        "source": str(source),
        "source_manifest": record(source / "study-manifest.json"),
        "deadline_authorization": record(contract_path),
        "execution_contract": execution,
        "runtime_binding": str(binding_path.resolve()),
        "future_destination": str((output / "capture-v1").resolve()),
        "command": declared_command(args, Path(python).absolute(), Path(capture_script).absolute(), environment),
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    import argparse

    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "output",
        "source",
        "source-audit",
        "failed-capture",
        "attempt-audit",
        "completion",
        "correction-audit",
        "correction-archive",
        "capture-script",
        "python",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    values = vars(parser.parse_args(argv))
    values.pop("prepare_only")
    print(json.dumps(prepare(**values, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
