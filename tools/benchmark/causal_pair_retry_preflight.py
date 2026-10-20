"""Build, but never execute, a causal-pair-corrected retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.causal_deadline_retry_preflight import OUTPUT_NAMES as SOURCE_NAMES
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.physical_retry_preflight import COPY_NAMES
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

PAIR_ARCHIVE_NAME = "causal-pair-stage-dev-1701.zip"
PAIR_ARCHIVE_SHA256 = "e6cc10331d4a466365d6508440c008700d070d2f6f9d7c9982098364dbcf8d14"
PAIR_AUDIT_MEMBER = "results/causal-pair-stage-dev-1701/fixed-replay-audit-v2.json"
PAIR_FALSE_CLAIMS = (
    "physical_execution_qualified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "flight_ready",
)
OUTPUT_NAMES = set(SOURCE_NAMES) | {"pair-correction-authorization.json"}
COPY_CONTRACTS = (*COPY_NAMES, "startup-authorization-contract.json", "deadline-correction-authorization.json")
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/openvins_causal_input.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/ready_shadow_fanout.py",
    "tools/benchmark/causal_pair_retry_preflight.py",
    "tools/benchmark/audit_causal_pair_retry_preflight.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def validate_failed_attempt(capture, attempt_audit, completion):
    capture = Path(capture).resolve(strict=True)
    result = read_declaration(capture / "result.json")
    audit = read_declaration(attempt_audit)
    completed = read_declaration(completion)
    motion = result.get("motion", {})
    timing = audit.get("timing_ns", {})
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
        or audit.get("schema") != "causal-deadline-physical-attempt-audit-v2"
        or audit.get("failures") != []
        or audit.get("failure_classification_qualified") is not True
        or audit.get("classification") != "causal-input-same-stamp-pair-source-arrival-deadline-refusal"
        or audit.get("fruit_fly_policy_evaluated") is not False
        or timing.get("limit") != 250_000_000
        or timing.get("same_sample_pair_gap") != 258_765_752
        or timing.get("excess") != 8_765_752
        or any(audit.get(key) is not False for key in FALSE_CLAIMS)
        or completed.get("destination") != str(capture)
        or completed.get("physical_run") is not True
        or completed.get("returncode") != 2
        or completed.get("resources_after") != []
    ):
        raise ValueError("failed attempt evidence not qualified")
    return result, audit


def _validated_archive_manifest(package):
    names = package.namelist()
    if len(names) != len(set(names)) or package.testzip() is not None or "manifest.json" not in names:
        raise ValueError("pair correction not qualified")
    manifest = json.loads(package.read("manifest.json"))
    members = manifest.get("members")
    qualifications = manifest.get("qualifications", {})
    if (
        manifest.get("schema") != "causal-pair-stage-evidence-v1"
        or not isinstance(members, list)
        or manifest.get("member_count_without_manifest") != len(members)
        or set(names) != {item.get("path") for item in members} | {"manifest.json"}
        or qualifications.get("fixed_input_pair_stage") is not True
        or any(
            qualifications.get(key) is not False
            for key in ("physical_execution", "runtime_closure", "vio_accuracy", "estimator_health", "fusion_eligible", "flight_ready")
        )
    ):
        raise ValueError("pair correction not qualified")
    for item in members:
        path = item.get("path")
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
            raise ValueError("pair correction not qualified")
        payload = package.read(path)
        if len(payload) != item.get("bytes") or hashlib.sha256(payload).hexdigest() != item.get("sha256"):
            raise ValueError("pair correction not qualified")
    return manifest


def validate_pair_correction(pair_audit, pair_archive, *, expected_archive_sha256=PAIR_ARCHIVE_SHA256):
    audit_path = Path(pair_audit).resolve(strict=True)
    archive = Path(pair_archive).resolve(strict=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive.name != PAIR_ARCHIVE_NAME or digest != expected_archive_sha256:
        raise ValueError("pair correction not qualified")
    audit = read_declaration(audit_path)
    if (
        audit.get("schema") != "causal-pair-stage-fixed-replay-audit-v1"
        or audit.get("failures") != []
        or audit.get("fixed_replay_qualified") is not True
        or any(audit.get(key) is not False for key in PAIR_FALSE_CLAIMS)
    ):
        raise ValueError("pair correction not qualified")
    try:
        with zipfile.ZipFile(archive) as package:
            _validated_archive_manifest(package)
            if package.read(PAIR_AUDIT_MEMBER) != audit_path.read_bytes():
                raise ValueError("pair correction not qualified")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("pair correction not qualified") from exc
    return audit, digest


def prepare(
    output,
    *,
    source,
    source_audit,
    failed_capture,
    attempt_audit,
    completion,
    pair_audit,
    pair_archive,
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
    expected_files = set(SOURCE_NAMES) | {
        "capture-v1.supervisor-environment.json",
        "capture-v1.supervisor-events.jsonl",
        "startup-preflight-v1.supervisor-environment.json",
        "startup-preflight-v1.supervisor-events.jsonl",
    }
    if {path.name for path in source.iterdir() if path.is_file()} != expected_files or {
        path.name for path in source.iterdir() if path.is_dir()
    } != {"capture-v1", "startup-preflight-v1"}:
        raise ValueError("source package members differ")
    source_check = read_declaration(source_audit)
    if (
        source_check.get("schema") != "causal-deadline-physical-retry-audit-v1"
        or source_check.get("failures") != []
        or source_check.get("prepare_qualified") is not True
        or any(source_check.get(key) is not False for key in FALSE_CLAIMS)
    ):
        raise ValueError("source package audit failed")
    failed_capture = Path(failed_capture).resolve(strict=True)
    if failed_capture != (source / "capture-v1").resolve():
        raise ValueError("failed capture is not source destination")
    validate_failed_attempt(failed_capture, attempt_audit, completion)
    correction, correction_sha = validate_pair_correction(pair_audit, pair_archive)
    source_manifest = read_declaration(source / "study-manifest.json")
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")
    if source_manifest.get("prepare_only") is not True or source_manifest.get("future_destination") != str(failed_capture):
        raise ValueError("source manifest does not identify failed capture")

    output.mkdir(parents=True)
    for name in COPY_CONTRACTS:
        shutil.copy2(source / name, output / name)
    contract_path = output / "pair-correction-authorization.json"
    contract = {
        "schema": "causal-pair-correction-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "failed_result": record(failed_capture / "result.json"),
        "attempt_audit": record(attempt_audit),
        "completion": record(completion),
        "pair_audit": record(pair_audit),
        "pair_archive": {**record(pair_archive), "sha256": correction_sha},
        "fixed_replay_qualified": correction["fixed_replay_qualified"],
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(contract_path, contract)

    binding = copy.deepcopy(source_binding)
    root = Path(__file__).resolve().parents[2]
    _add_missing(binding["inventory"], "runtime:causal-pair-retry-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:causal-pair-authorization", [contract_path])
    _add_missing(binding["inventory"], "evidence:causal-pair-correction", [attempt_audit, completion, pair_audit, pair_archive])
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
        "schema": "causal-pair-physical-retry-preflight-v1",
        "prepare_only": True,
        "source": str(source),
        "source_manifest": record(source / "study-manifest.json"),
        "pair_authorization": record(contract_path),
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
        "pair-audit",
        "pair-archive",
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
