"""Build, but never execute, an OpenVINS-handoff-corrected retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.causal_pair_retry_preflight import record
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.estimator_heartbeat_retry_preflight import (
    COPY_CONTRACTS as HEARTBEAT_COPY_CONTRACTS,
)
from tools.benchmark.estimator_heartbeat_retry_preflight import (
    OUTPUT_NAMES as SOURCE_NAMES,
)
from tools.benchmark.estimator_heartbeat_retry_preflight import _same_destination
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

CORRECTION_ARCHIVE_NAME = "openvins-initializer-handoff-contract-dev-1701.zip"
CORRECTION_ARCHIVE_SHA256 = "7807e049a298de58c82e9073d73a8ded9fccdcaf35b5eba0527ded8f549dd5b9"
ARCHIVE_PREFIX = "openvins-initializer-handoff-contract-dev-1701/"
CORRECTION_AUDIT_MEMBER = "results/openvins-initializer-handoff-contract-dev-1701/physical-attempt-audit.json"
OUTPUT_NAMES = set(SOURCE_NAMES) | {"handoff-correction-authorization.json"}
COPY_CONTRACTS = (*HEARTBEAT_COPY_CONTRACTS, "heartbeat-routing-authorization.json")
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/ready_shadow_fanout.py",
    "tools/benchmark/journaled_heartbeat_lane.py",
    "tools/benchmark/openvins_handoff_retry_preflight.py",
    "tools/benchmark/audit_openvins_handoff_retry_preflight.py",
    "tools/benchmark/audit_estimator_handoff_physical_attempt.py",
)
ATTEMPT_FALSE_CLAIMS = (
    "complete_physical_execution_qualified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "ekf2_injection_qualified",
    "flight_ready",
    "fruit_fly_policy_failure",
)
ARCHIVE_CLAIMS = {
    "physical_attempt_immutable": True,
    "physical_retry_during_correction": False,
    "failure_evidence_qualified": True,
    "heartbeat_correction_physically_verified": True,
    "complete_physical_execution_qualified": False,
    "vio_accuracy_qualified": False,
    "fusion_eligible": False,
    "flight_ready": False,
}


def _authorization_claims(*, source_runtime_mapping_coverage_verified):
    return {
        "source_runtime_mapping_coverage_verified": source_runtime_mapping_coverage_verified,
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }


def _pending_ack_valid(value):
    expected = {
        "sequence": 600,
        "kind": "C",
        "sample_ns": 2_300_000_000,
        "internal_initialized": False,
        "public_initialized": False,
        "initializer_time_s": 1.304,
        "state_time_s": 1.304,
        "last_regular_update_s": -1,
        "zupt_flag_latched": False,
        "has_moved_since_zupt": False,
        "imu_state": None,
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }
    return isinstance(value, dict) and all(value.get(key) == item for key, item in expected.items())


def validate_source_package(source):
    source = Path(source).resolve(strict=True)
    expected_files = set(SOURCE_NAMES) | {
        "capture-v1.supervisor-environment.json",
        "capture-v1.supervisor-events.jsonl",
        "startup-preflight-v1.supervisor-environment.json",
        "startup-preflight-v1.supervisor-events.jsonl",
    }
    if (
        {path.name for path in source.iterdir() if path.is_file()} != expected_files
        or {path.name for path in source.iterdir() if path.is_dir()} != {"capture-v1", "startup-preflight-v1"}
    ):
        raise ValueError("source package members differ")
    manifest = read_declaration(source / "study-manifest.json")
    if (
        manifest.get("schema") != "estimator-heartbeat-physical-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or not _same_destination(manifest.get("future_destination"), source / "capture-v1")
        or any(manifest.get(key) is not False for key in FALSE_CLAIMS)
    ):
        raise ValueError("source package not qualified")
    return source, manifest


def validate_failed_attempt(capture, attempt_audit, completion):
    capture = Path(capture).resolve(strict=True)
    result = read_declaration(capture / "result.json")
    audit = read_declaration(attempt_audit)
    completed = read_declaration(completion)
    fanout = result.get("source_fanout", {})
    last = fanout.get("last_disposition", {})
    heartbeat = fanout.get("heartbeat", {})
    motion = result.get("motion", {})
    runtime = result.get("runtime_binding", {})
    pending = result.get("shadow", {}).get("last_delivery_acks", [{}])[-1]
    ulogs = result.get("px4_ulogs")
    if (
        result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 2_320_000_000
        or result.get("source_fanout_profile") != "ready-shadow-heartbeat-estimator-v1"
        or fanout.get("failure") != "ValueError(\"ValueError('uninitialized acknowledgement has state')\")"
        or last.get("source_sequence") != 649
        or last.get("dispositions") != {"shadow": "attempted", "readiness": "not_attempted"}
        or heartbeat.get("observed") != 1
        or heartbeat.get("reconciled") != 1
        or heartbeat.get("pending") != []
        or heartbeat.get("failure") is not None
        or not _pending_ack_valid(pending)
        or result.get("readiness", {}).get("first_internal") is not None
        or result.get("readiness", {}).get("latest_internal") is not None
        or motion.get("anchor_ns") is not None
        or motion.get("active_steps") != 0
        or motion.get("support_steps") != 0
        or motion.get("recorded_commands") != 0
        or motion.get("absolute_impulse_ns") != 0.0
        or result.get("eligible_for_vio_input") is not False
        or result.get("eligible_for_px4_fusion") is not False
        or result.get("px4_exit_code") != 0
        or result.get("native", {}).get("exit") != 0
        or result.get("native", {}).get("failure") is not None
        or not isinstance(ulogs, list)
        or len(ulogs) != 1
        or ulogs[0].get("valid_header") is not True
        or not isinstance(ulogs[0].get("bytes"), int)
        or ulogs[0]["bytes"] <= 0
        or runtime.get("runtime_mapping_coverage_verified") is not True
        or runtime.get("runtime_closure_qualified") is not False
        or audit.get("schema") != "estimator-handoff-physical-attempt-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "openvins-synchronous-initializer-handoff-contract-refusal"
        or audit.get("heartbeat_correction_physically_verified") is not True
        or audit.get("pending_handoff") != {
            key: pending.get(key)
            for key in (
                "sequence",
                "sample_ns",
                "initializer_time_s",
                "state_time_s",
                "internal_initialized",
                "public_initialized",
                "last_regular_update_s",
                "imu_state",
            )
        }
        or any(audit.get(key) is not False for key in ATTEMPT_FALSE_CLAIMS)
        or not _same_destination(completed.get("destination"), capture)
        or completed.get("physical_run") is not True
        or completed.get("returncode") != 2
        or completed.get("resources_after") != []
    ):
        raise ValueError("failed handoff attempt not qualified")
    return result, audit


def _validated_archive_manifest(package):
    names = package.namelist()
    manifest_name = ARCHIVE_PREFIX + "manifest.json"
    if len(names) != len(set(names)) or package.testzip() is not None or manifest_name not in names:
        raise ValueError("handoff correction not qualified")
    manifest = json.loads(package.read(manifest_name))
    members = manifest.get("members")
    if (
        manifest.get("schema") != "openvins-initializer-handoff-contract-evidence-v1"
        or manifest.get("stage") != "openvins-initializer-handoff-contract-dev-1701"
        or manifest.get("claims") != ARCHIVE_CLAIMS
        or not isinstance(members, list)
        or manifest.get("member_count") != len(members)
        or set(names) != {ARCHIVE_PREFIX + item.get("path", "") for item in members} | {manifest_name}
    ):
        raise ValueError("handoff correction not qualified")
    for item in members:
        path = item.get("path")
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
            raise ValueError("handoff correction not qualified")
        payload = package.read(ARCHIVE_PREFIX + path)
        if len(payload) != item.get("bytes") or hashlib.sha256(payload).hexdigest() != item.get("sha256"):
            raise ValueError("handoff correction not qualified")
    return manifest


def validate_correction(correction_audit, correction_archive, *, expected_archive_sha256=CORRECTION_ARCHIVE_SHA256):
    audit_path = Path(correction_audit).resolve(strict=True)
    archive = Path(correction_archive).resolve(strict=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive.name != CORRECTION_ARCHIVE_NAME or digest != expected_archive_sha256:
        raise ValueError("handoff correction not qualified")
    audit = read_declaration(audit_path)
    if (
        audit.get("schema") != "estimator-handoff-physical-attempt-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "openvins-synchronous-initializer-handoff-contract-refusal"
        or audit.get("heartbeat_correction_physically_verified") is not True
        or any(audit.get(key) is not False for key in ATTEMPT_FALSE_CLAIMS)
    ):
        raise ValueError("handoff correction not qualified")
    try:
        with zipfile.ZipFile(archive) as package:
            _validated_archive_manifest(package)
            if package.read(ARCHIVE_PREFIX + CORRECTION_AUDIT_MEMBER) != audit_path.read_bytes():
                raise ValueError("handoff correction not qualified")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("handoff correction not qualified") from exc
    return audit, digest


def prepare(
    output,
    *,
    source,
    failed_capture,
    attempt_audit,
    completion,
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
    source, source_manifest = validate_source_package(source)
    failed_capture = Path(failed_capture).resolve(strict=True)
    if failed_capture != (source / "capture-v1").resolve():
        raise ValueError("failed capture is not source destination")
    result, correction = validate_failed_attempt(failed_capture, attempt_audit, completion)
    _, correction_sha = validate_correction(attempt_audit, correction_archive)
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")

    output.mkdir(parents=True)
    for name in COPY_CONTRACTS:
        shutil.copy2(source / name, output / name)
    contract_path = output / "handoff-correction-authorization.json"
    contract = {
        "schema": "openvins-initializer-handoff-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "failed_result": record(failed_capture / "result.json"),
        "attempt_audit": record(attempt_audit),
        "completion": record(completion),
        "correction_archive": {**record(correction_archive), "sha256": correction_sha},
        "failure_classification_qualified": correction["failure_evidence_qualified"],
        "heartbeat_correction_physically_verified": correction["heartbeat_correction_physically_verified"],
        **_authorization_claims(
            source_runtime_mapping_coverage_verified=result["runtime_binding"]["runtime_mapping_coverage_verified"]
        ),
    }
    write_manifest(contract_path, contract)

    binding = copy.deepcopy(source_binding)
    root = Path(__file__).resolve().parents[2]
    _add_missing(
        binding["inventory"],
        "runtime:openvins-handoff-retry-code",
        [str((root / name).resolve(strict=True)) for name in CODE_NAMES],
    )
    _add_missing(binding["inventory"], "runtime:openvins-handoff-authorization", [contract_path])
    _add_missing(
        binding["inventory"],
        "evidence:openvins-handoff-correction",
        [attempt_audit, completion, correction_archive],
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
        "schema": "openvins-handoff-physical-retry-preflight-v1",
        "prepare_only": True,
        "source": str(source),
        "source_manifest": record(source / "study-manifest.json"),
        "handoff_authorization": record(contract_path),
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
        "failed-capture",
        "attempt-audit",
        "completion",
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
