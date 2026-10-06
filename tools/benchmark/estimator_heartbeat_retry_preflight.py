"""Build, but never execute, an estimator-heartbeat-corrected retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.causal_pair_retry_preflight import (
    COPY_CONTRACTS as PAIR_COPY_CONTRACTS,
)
from tools.benchmark.causal_pair_retry_preflight import (
    OUTPUT_NAMES as SOURCE_NAMES,
)
from tools.benchmark.causal_pair_retry_preflight import (
    record,
)
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

CORRECTION_ARCHIVE_NAME = "estimator-heartbeat-routing-dev-1701.zip"
CORRECTION_ARCHIVE_SHA256 = "e3a339d93bf7864919bd2733a890669ff85288d05941e6eb56ea2b3b50320017"
ARCHIVE_PREFIX = "estimator-heartbeat-routing-dev-1701/"
CORRECTION_AUDIT_MEMBER = "results/estimator-heartbeat-routing-dev-1701/study-v11-audit.json"
OUTPUT_NAMES = set(SOURCE_NAMES) | {"heartbeat-routing-authorization.json"}
COPY_CONTRACTS = (*PAIR_COPY_CONTRACTS, "pair-correction-authorization.json")
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/ready_shadow_fanout.py",
    "tools/benchmark/journaled_heartbeat_lane.py",
    "tools/benchmark/estimator_heartbeat_retry_preflight.py",
    "tools/benchmark/audit_estimator_heartbeat_retry_preflight.py",
)


def _same_destination(value, capture):
    if not isinstance(value, str):
        return False

    def canonical(text):
        normalized = str(text).replace("\\", "/")
        if normalized.startswith("/mnt/") and len(normalized) > 6:
            normalized = normalized[5] + ":" + normalized[6:]
        return normalized.lower()

    return canonical(value) == canonical(Path(capture).resolve())


def validate_source_audit(path):
    audit = read_declaration(path)
    if (
        audit.get("schema") != "causal-pair-physical-retry-audit-v1"
        or audit.get("failures") != []
        or audit.get("prepare_qualified") is not True
        or any(audit.get(key) is not False for key in FALSE_CLAIMS)
    ):
        raise ValueError("source package audit failed")
    return audit


def validate_failed_attempt(capture, attempt_audit, completion):
    capture = Path(capture).resolve(strict=True)
    result = read_declaration(capture / "result.json")
    audit = read_declaration(attempt_audit)
    completed = read_declaration(completion)
    fanout = result.get("source_fanout", {})
    last = fanout.get("last_disposition", {})
    heartbeat = fanout.get("heartbeat", {})
    motion = result.get("motion", {})
    ulogs = result.get("px4_ulogs")
    claims = audit.get("claims", {})
    if (
        result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 1_520_000_000
        or result.get("source_fanout_profile") != "ready-shadow-heartbeat-estimator-v1"
        or "invalid source sample" not in str(fanout.get("failure"))
        or last.get("source_sequence") != 426
        or last.get("dispositions") != {"shadow": "attempted", "readiness": "not_attempted"}
        or heartbeat.get("observed") != 1
        or heartbeat.get("reconciled") != 0
        or motion.get("anchor_ns") is not None
        or motion.get("active_steps") != 0
        or motion.get("support_steps") != 0
        or motion.get("recorded_commands") != 0
        or result.get("eligible_for_vio_input") is not False
        or result.get("eligible_for_px4_fusion") is not False
        or result.get("px4_exit_code") != 0
        or not isinstance(ulogs, list)
        or len(ulogs) != 1
        or ulogs[0].get("valid_header") is not True
        or not isinstance(ulogs[0].get("bytes"), int)
        or ulogs[0]["bytes"] <= 0
        or audit.get("schema") != "estimator-heartbeat-routing-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_classification_qualified") is not True
        or audit.get("classification") != "estimator-ack-routing-heartbeat-without-sample-refusal"
        or any(
            claims.get(key) is not False
            for key in (
                "fruit_fly_learning_failure",
                "training_failure",
                "vio_accuracy_evaluated",
                "physical_retry_performed",
                "fusion_eligible",
            )
        )
        or not _same_destination(completed.get("destination"), capture)
        or completed.get("physical_run") is not True
        or completed.get("returncode") != 2
        or completed.get("resources_after") != []
    ):
        raise ValueError("failed heartbeat attempt not qualified")
    return result, audit


def _validated_archive_manifest(package):
    names = package.namelist()
    manifest_name = ARCHIVE_PREFIX + "manifest.json"
    if len(names) != len(set(names)) or package.testzip() is not None or manifest_name not in names:
        raise ValueError("heartbeat correction not qualified")
    manifest = json.loads(package.read(manifest_name))
    members = manifest.get("members")
    if (
        manifest.get("schema") != "flydrones-evidence-manifest-v1"
        or manifest.get("stage") != "estimator-heartbeat-routing-dev-1701"
        or not isinstance(members, list)
        or manifest.get("member_count") != len(members)
        or set(names) != {ARCHIVE_PREFIX + item.get("path", "") for item in members} | {manifest_name}
    ):
        raise ValueError("heartbeat correction not qualified")
    for item in members:
        path = item.get("path")
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
            raise ValueError("heartbeat correction not qualified")
        payload = package.read(ARCHIVE_PREFIX + path)
        if len(payload) != item.get("bytes") or hashlib.sha256(payload).hexdigest() != item.get("sha256"):
            raise ValueError("heartbeat correction not qualified")
    return manifest


def validate_correction(correction_audit, correction_archive, *, expected_archive_sha256=CORRECTION_ARCHIVE_SHA256):
    audit_path = Path(correction_audit).resolve(strict=True)
    archive = Path(correction_archive).resolve(strict=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive.name != CORRECTION_ARCHIVE_NAME or digest != expected_archive_sha256:
        raise ValueError("heartbeat correction not qualified")
    audit = read_declaration(audit_path)
    claims = audit.get("claims", {})
    if (
        audit.get("schema") != "estimator-heartbeat-routing-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_classification_qualified") is not True
        or audit.get("classification") != "estimator-ack-routing-heartbeat-without-sample-refusal"
        or any(value is not False for value in claims.values())
    ):
        raise ValueError("heartbeat correction not qualified")
    try:
        with zipfile.ZipFile(archive) as package:
            _validated_archive_manifest(package)
            if package.read(ARCHIVE_PREFIX + CORRECTION_AUDIT_MEMBER) != audit_path.read_bytes():
                raise ValueError("heartbeat correction not qualified")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("heartbeat correction not qualified") from exc
    return audit, digest


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
    validate_source_audit(source_audit)
    failed_capture = Path(failed_capture).resolve(strict=True)
    if failed_capture != (source / "capture-v1").resolve():
        raise ValueError("failed capture is not source destination")
    validate_failed_attempt(failed_capture, attempt_audit, completion)
    correction, correction_sha = validate_correction(correction_audit, correction_archive)
    source_manifest = read_declaration(source / "study-manifest.json")
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")
    if source_manifest.get("prepare_only") is not True or not _same_destination(
        source_manifest.get("future_destination"), failed_capture
    ):
        raise ValueError("source manifest does not identify failed capture")

    output.mkdir(parents=True)
    for name in COPY_CONTRACTS:
        shutil.copy2(source / name, output / name)
    contract_path = output / "heartbeat-routing-authorization.json"
    contract = {
        "schema": "estimator-heartbeat-routing-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "failed_result": record(failed_capture / "result.json"),
        "attempt_audit": record(attempt_audit),
        "completion": record(completion),
        "correction_audit": record(correction_audit),
        "correction_archive": {**record(correction_archive), "sha256": correction_sha},
        "failure_classification_qualified": correction["failure_classification_qualified"],
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(contract_path, contract)

    binding = copy.deepcopy(source_binding)
    root = Path(__file__).resolve().parents[2]
    _add_missing(binding["inventory"], "runtime:estimator-heartbeat-retry-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:estimator-heartbeat-authorization", [contract_path])
    _add_missing(
        binding["inventory"],
        "evidence:estimator-heartbeat-correction",
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
        "schema": "estimator-heartbeat-physical-retry-preflight-v1",
        "prepare_only": True,
        "source": str(source),
        "source_manifest": record(source / "study-manifest.json"),
        "heartbeat_authorization": record(contract_path),
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
