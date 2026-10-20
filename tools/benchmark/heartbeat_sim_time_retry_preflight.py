"""Build, but never execute, a heartbeat-simulation-time retry package."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS, _add_missing
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

ARCHIVE_NAME = "heartbeat-simulation-time-readiness-dev-1701.zip"
ARCHIVE_SHA256 = "955c914bdc55884a804e532f839d369ee41a195ec3411cbd2a272ad359b27f9b"
ARCHIVE_MANIFEST = "results/heartbeat-simulation-time-readiness-dev-1701/manifest.json"
ARCHIVE_AUDIT = "results/heartbeat-simulation-time-readiness-dev-1701/fixed-evidence-audit.json"
ARCHIVE_SOURCE = "results/openvins-handoff-physical-attempt-dev-1701/physical-attempt-audit.json"
ARCHIVE_IMPLEMENTATION = "tools/benchmark/readiness_anchor.py"
COPY_CONTRACTS = (
    "deadline-correction-authorization.json",
    "estimator-readiness-contract.json",
    "handoff-correction-authorization.json",
    "heartbeat-routing-authorization.json",
    "lazy-runtime-contract.json",
    "pair-correction-authorization.json",
    "physical-refusal-contract.json",
    "startup-authorization-contract.json",
    "trajectory-gauge-policy.json",
)
OUTPUT_NAMES = set(COPY_CONTRACTS) | {
    "heartbeat-simulation-time-authorization.json",
    "runtime-binding-v3.json",
    "execution-contract.json",
    "study-manifest.json",
}
SOURCE_FILES = set(COPY_CONTRACTS) | {"runtime-binding-v3.json", "execution-contract.json", "study-manifest.json"} | {
    "capture-v1.supervisor-environment.json",
    "capture-v1.supervisor-events.jsonl",
    "startup-preflight-v1.supervisor-environment.json",
    "startup-preflight-v1.supervisor-events.jsonl",
}
CODE_NAMES = (
    "tools/benchmark/capture_contract.py",
    "tools/benchmark/capture_disarmed_sensors.py",
    "tools/benchmark/readiness_anchor.py",
    "tools/benchmark/journaled_heartbeat_lane.py",
    "tools/benchmark/estimator_aware_readiness.py",
    "tools/benchmark/heartbeat_sim_time_retry_preflight.py",
    "tools/benchmark/audit_heartbeat_sim_time_retry_preflight.py",
    "tools/benchmark/audit_heartbeat_sim_time_readiness.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def validate_source(source, source_audit, completion):
    source = Path(source).resolve(strict=True)
    if {p.name for p in source.iterdir() if p.is_file()} != SOURCE_FILES:
        raise ValueError("source files differ")
    if {p.name for p in source.iterdir() if p.is_dir()} != {"capture-v1", "startup-preflight-v1"}:
        raise ValueError("source directories differ")
    manifest = read_declaration(source / "study-manifest.json")
    audit = read_declaration(source_audit)
    completed = read_declaration(completion)
    capture = source / "capture-v1"
    if (
        manifest.get("schema") != "openvins-handoff-physical-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or Path(manifest.get("future_destination", "")).resolve() != capture.resolve()
        or audit.get("schema") != "openvins-handoff-physical-attempt-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "journaled-heartbeat-wall-age-slow-simulation-refusal"
        or audit.get("heartbeat_wall_age_ns") != 2_000_774_305
        or audit.get("heartbeat_sim_age_ns") != 968_000_000
        or completed.get("returncode") != 2
        or completed.get("destination_exists") is not True
        or completed.get("resources_after") != []
        or any(manifest.get(key) is not False for key in FALSE_CLAIMS)
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
        audit.get("schema") != "heartbeat-simulation-time-readiness-audit-v1"
        or audit.get("failures") != []
        or audit.get("qualified") is not True
        or audit.get("fixed_evidence_ready") is not True
        or audit.get("simulation_silence_refused") is not True
        or audit.get("timeout_increased") is not False
        or audit.get("physical_rerun") is not False
        or audit.get("vio_accuracy_qualified") is not False
        or audit.get("fusion_eligible") is not False
    ):
        raise ValueError("correction audit")
    try:
        with zipfile.ZipFile(archive) as package:
            if package.testzip() is not None or len(package.namelist()) != len(set(package.namelist())):
                raise ValueError("correction archive integrity")
            manifest = json.loads(package.read(ARCHIVE_MANIFEST))
            members = manifest.get("members")
            if (
                manifest.get("schema") != "heartbeat-simulation-time-readiness-evidence-v1"
                or manifest.get("physical_rerun") is not False
                or manifest.get("fusion_eligible") is not False
                or not isinstance(members, list)
                or set(package.namelist()) != {item.get("path") for item in members} | {ARCHIVE_MANIFEST}
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
            source_bytes = package.read(ARCHIVE_SOURCE)
            if hashlib.sha256(source_bytes).hexdigest() != audit.get("source_sha256"):
                raise ValueError("correction source audit bytes")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("correction archive") from exc
    return audit


def prepare(
    output,
    *,
    source,
    source_audit,
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
    source, source_manifest, source_result = validate_source(source, source_audit, completion)
    root = Path(__file__).resolve().parents[2]
    correction = validate_correction(correction_audit, correction_archive, root / ARCHIVE_IMPLEMENTATION)
    source_binding = read_declaration(source / "runtime-binding-v3.json")
    source_execution = read_declaration(source / "execution-contract.json")

    output.mkdir(parents=True)
    for name in COPY_CONTRACTS:
        shutil.copy2(source / name, output / name)
    authorization_path = output / "heartbeat-simulation-time-authorization.json"
    authorization = {
        "schema": "heartbeat-simulation-time-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "completion": record(completion),
        "correction_audit": record(correction_audit),
        "correction_archive": {**record(correction_archive), "sha256": ARCHIVE_SHA256},
        "wall_age_ns": source_result["heartbeat_wall_age_ns"],
        "simulation_age_ns": source_result["heartbeat_sim_age_ns"],
        "fixed_evidence_ready": correction["fixed_evidence_ready"],
        "simulation_silence_refused": correction["simulation_silence_refused"],
        "timeout_increased": False,
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(authorization_path, authorization)

    binding = copy.deepcopy(source_binding)
    _add_missing(binding["inventory"], "runtime:heartbeat-sim-time-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:heartbeat-sim-time-authorization", [authorization_path])
    _add_missing(binding["inventory"], "evidence:heartbeat-sim-time-correction", [source_audit, completion, correction_audit, correction_archive])
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
        "schema": "heartbeat-simulation-time-physical-retry-preflight-v1",
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
    for name in ("output", "source", "source-audit", "completion", "correction-audit", "correction-archive", "capture-script", "python"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    values = vars(parser.parse_args(argv))
    values.pop("prepare_only")
    print(json.dumps(prepare(**values, resources=active_resources()), indent=2))


if __name__ == "__main__":
    main()
