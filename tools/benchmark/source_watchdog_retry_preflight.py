"""Build, but never execute, a source-watchdog-corrected retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.causal_pair_sim_time_retry_preflight import COPY_CONTRACTS as PRIOR_CONTRACTS
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

ARCHIVE_NAME = "source-watchdog-startup-cohort-dev-1701.zip"
ARCHIVE_SHA256 = "9899cf5d0908cfa07eb6bcacde334292b67760ee842b7e481051c66b1cf63d98"
ARCHIVE_MANIFEST = "results/causal-pair-sim-time-physical-boundary-dev-1701/manifest.json"
ARCHIVE_AUDIT = "results/causal-pair-sim-time-physical-boundary-dev-1701/startup-cohort-audit.json"
ARCHIVE_IMPLEMENTATION = "tools/benchmark/openvins_online_shadow.py"
COPY_CONTRACTS = PRIOR_CONTRACTS + ("causal-pair-simulation-time-authorization.json",)
OUTPUT_NAMES = set(COPY_CONTRACTS) | {
    "source-watchdog-startup-cohort-authorization.json",
    "runtime-binding-v3.json",
    "execution-contract.json",
    "study-manifest.json",
}
SOURCE_FILES = set(COPY_CONTRACTS) | {
    "runtime-binding-v3.json",
    "execution-contract.json",
    "study-manifest.json",
    "capture-v1.supervisor-environment.json",
    "capture-v1.supervisor-events.jsonl",
    "startup-preflight-v1.supervisor-environment.json",
    "startup-preflight-v1.supervisor-events.jsonl",
}
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/openvins_causal_input.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/readiness_anchor.py",
    "tools/benchmark/journaled_heartbeat_lane.py",
    "tools/benchmark/source_watchdog_retry_preflight.py",
    "tools/benchmark/audit_source_watchdog_retry_preflight.py",
    "tools/benchmark/audit_source_watchdog_startup_cohort.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def _path_key(value):
    text = str(value).replace("\\", "/")
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        text = f"{text[5]}:/{text[7:]}"
    return str(Path(text).resolve()).replace("\\", "/").casefold()


def validate_source(source, source_audit, completion, boundary_audit):
    source = Path(source).resolve(strict=True)
    if {path.name for path in source.iterdir() if path.is_file()} != SOURCE_FILES:
        raise ValueError("source files differ")
    if {path.name for path in source.iterdir() if path.is_dir()} != {"capture-v1", "startup-preflight-v1"}:
        raise ValueError("source directories differ")
    manifest = read_declaration(source / "study-manifest.json")
    audit = read_declaration(source_audit)
    completed = read_declaration(completion)
    boundary = read_declaration(boundary_audit)
    result = read_declaration(source / "capture-v1/result.json")
    health = result.get("source_health", {})
    motion = result.get("motion", {})
    if (
        manifest.get("schema") != "causal-pair-simulation-time-physical-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or _path_key(manifest.get("future_destination", "")) != _path_key(source / "capture-v1")
        or audit.get("schema") != "source-watchdog-startup-cohort-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "startup-readiness-before-fresh-source-cohort"
        or audit.get("imu_age_at_failure_ns") != 2_079_562_030
        or audit.get("failure_after_ready_ns") != 254_629
        or audit.get("next_imu_after_failure_ns") != 713_794
        or audit.get("next_fresh_cohort_span_ns") != 265_527_095
        or audit.get("candidate_fresh_cohort_qualified") is not True
        or audit.get("physical_retry_performed") is not True
        or audit.get("fruit_fly_policy_failure") is not False
        or completed.get("schema") != "causal-pair-sim-time-physical-completion-v1"
        or completed.get("physical_run") is not True
        or completed.get("command_returncode") != 2
        or completed.get("launcher_returncode") != 2
        or completed.get("destination_exists") is not True
        or completed.get("resources_after") != []
        or _path_key(completed.get("destination", "")) != _path_key(source / "capture-v1")
        or boundary.get("schema") != "causal-pair-sim-time-physical-boundary-audit-v1"
        or boundary.get("failures") != []
        or boundary.get("boundary_qualified") is not True
        or result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 10_000_000
        or result.get("source_fanout", {}).get("failure") != "TimeoutError('source silence: imu')"
        or health.get("startup_timeout_ns") != 10_000_000_000
        or health.get("operational_timeout_ns") != 2_000_000_000
        or motion.get("anchor_ns") is not None
        or motion.get("support_steps") != 0
        or motion.get("recorded_commands") != 0
        or result.get("px4_ulogs") != []
        or result.get("eligible_for_px4_fusion") is not False
        or any(manifest.get(key) is not False for key in FALSE_CLAIMS)
        or audit.get("complete_physical_execution_qualified") is not False
        or any(audit.get(key) is not False for key in FALSE_CLAIMS if key != "physical_execution_qualified")
        or any(boundary.get(key) is not False for key in FALSE_CLAIMS)
    ):
        raise ValueError("source failure is not qualified")
    return source, manifest, audit


def validate_correction(correction_audit, correction_archive, implementation):
    audit_path = Path(correction_audit).resolve(strict=True)
    archive = Path(correction_archive).resolve(strict=True)
    implementation = Path(implementation).resolve(strict=True)
    if archive.name != ARCHIVE_NAME or hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("correction archive identity")
    audit = read_declaration(audit_path)
    if (
        audit.get("schema") != "source-watchdog-startup-cohort-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "startup-readiness-before-fresh-source-cohort"
        or audit.get("candidate_fresh_cohort_qualified") is not True
        or audit.get("fruit_fly_policy_failure") is not False
        or audit.get("fusion_eligible") is not False
    ):
        raise ValueError("correction audit")
    try:
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            if package.testzip() is not None or len(names) != len(set(names)):
                raise ValueError("correction archive integrity")
            manifest = json.loads(package.read(ARCHIVE_MANIFEST))
            members = manifest.get("members")
            if (
                manifest.get("schema") != "source-watchdog-startup-cohort-evidence-v1"
                or not isinstance(members, list)
                or manifest.get("member_count_without_manifest") != len(members)
                or set(names) != {item.get("path") for item in members} | {ARCHIVE_MANIFEST}
            ):
                raise ValueError("correction archive manifest")
            for item in members:
                data = package.read(item["path"])
                if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
                    raise ValueError("correction archive member")
            if package.read(ARCHIVE_AUDIT) != audit_path.read_bytes():
                raise ValueError("correction audit bytes")
            if package.read(ARCHIVE_IMPLEMENTATION) != implementation.read_bytes():
                raise ValueError("correction implementation bytes")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("correction archive") from exc
    return audit


def prepare(
    output,
    *,
    source,
    source_audit,
    completion,
    boundary_audit,
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
    source, _, source_result = validate_source(source, source_audit, completion, boundary_audit)
    root = Path(__file__).resolve().parents[2]
    validate_correction(source_audit, correction_archive, root / ARCHIVE_IMPLEMENTATION)
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")

    output.mkdir(parents=True)
    for name in COPY_CONTRACTS:
        shutil.copy2(source / name, output / name)
    authorization_path = output / "source-watchdog-startup-cohort-authorization.json"
    authorization = {
        "schema": "source-watchdog-startup-cohort-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "completion": record(completion),
        "boundary_audit": record(boundary_audit),
        "correction_archive": {**record(correction_archive), "sha256": ARCHIVE_SHA256},
        "imu_age_at_failure_ns": source_result["imu_age_at_failure_ns"],
        "failure_after_ready_ns": source_result["failure_after_ready_ns"],
        "next_imu_after_failure_ns": source_result["next_imu_after_failure_ns"],
        "next_fresh_cohort_span_ns": source_result["next_fresh_cohort_span_ns"],
        "startup_timeout_ns": 10_000_000_000,
        "operational_timeout_ns": 2_000_000_000,
        "timeout_increased": False,
        "old_frame_repeated": False,
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(authorization_path, authorization)

    binding = copy.deepcopy(source_binding)
    _add_missing(binding["inventory"], "runtime:source-watchdog-retry-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:source-watchdog-startup-cohort-authorization", [authorization_path])
    _add_missing(binding["inventory"], "evidence:source-watchdog-startup-cohort", [source_audit, completion, boundary_audit, correction_archive])
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
        "schema": "source-watchdog-startup-cohort-retry-preflight-v1",
        "prepare_only": True,
        "source": str(source),
        "source_manifest": record(source / "study-manifest.json"),
        "authorization": record(authorization_path),
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
        "completion",
        "boundary-audit",
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
