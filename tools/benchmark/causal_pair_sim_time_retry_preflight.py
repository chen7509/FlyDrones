"""Build, but never execute, a causal-pair simulation-time retry package."""

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

ARCHIVE_NAME = "causal-pair-sim-time-dev-1701.zip"
ARCHIVE_SHA256 = "1b063c7e502670f646984fa3dd64b963a4a77e1d46686f269e9bf353fcc15ef9"
ARCHIVE_MANIFEST = "results/causal-pair-sim-time-dev-1701/manifest.json"
ARCHIVE_AUDIT = "results/causal-pair-sim-time-dev-1701/study-v16-audit.json"
ARCHIVE_IMPLEMENTATION = "tools/benchmark/openvins_causal_input.py"
COPY_CONTRACTS = (
    "deadline-correction-authorization.json",
    "estimator-readiness-contract.json",
    "handoff-correction-authorization.json",
    "heartbeat-routing-authorization.json",
    "heartbeat-simulation-time-authorization.json",
    "lazy-runtime-contract.json",
    "pair-correction-authorization.json",
    "physical-refusal-contract.json",
    "startup-authorization-contract.json",
    "trajectory-gauge-policy.json",
)
OUTPUT_NAMES = set(COPY_CONTRACTS) | {
    "causal-pair-simulation-time-authorization.json",
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
    "tools/benchmark/causal_pair_sim_time_retry_preflight.py",
    "tools/benchmark/audit_causal_pair_sim_time_retry_preflight.py",
    "tools/benchmark/audit_causal_pair_sim_time_physical_attempt.py",
)


def record(path):
    return file_record(Path(path).resolve(strict=True))


def _path_key(value):
    text = str(value).replace("\\", "/")
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        text = f"{text[5]}:/{text[7:]}"
    return str(Path(text).resolve()).replace("\\", "/").casefold()


def validate_source(source, source_audit, completion):
    source = Path(source).resolve(strict=True)
    if {path.name for path in source.iterdir() if path.is_file()} != SOURCE_FILES:
        raise ValueError("source files differ")
    if {path.name for path in source.iterdir() if path.is_dir()} != {"capture-v1", "startup-preflight-v1"}:
        raise ValueError("source directories differ")
    manifest = read_declaration(source / "study-manifest.json")
    audit = read_declaration(source_audit)
    completed = read_declaration(completion)
    result = read_declaration(source / "capture-v1/result.json")
    shadow = result.get("shadow", {})
    motion = result.get("motion", {})
    if (
        manifest.get("schema") != "heartbeat-simulation-time-physical-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or _path_key(manifest.get("future_destination", "")) != _path_key(source / "capture-v1")
        or audit.get("schema") != "causal-pair-simulation-time-physical-attempt-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "camera-pair-wall-age-slow-simulation-refusal"
        or audit.get("pair_wall_age_ns") != 355_099_344
        or audit.get("idle_wall_age_ns") != 294_079_878
        or audit.get("pair_sim_age_ns") != 0
        or audit.get("fixed_replay_camera_released") is not True
        or audit.get("simulation_silence_refused") is not True
        or audit.get("physical_retry_performed") is not True
        or audit.get("fruit_fly_policy_failure") is not False
        or completed.get("physical_run") is not True
        or completed.get("returncode") != 2
        or completed.get("destination_exists") is not True
        or completed.get("resources_after") != []
        or _path_key(completed.get("destination", "")) != _path_key(source / "capture-v1")
        or result.get("status") != "capture_failed"
        or result.get("end_sim_ns") != 10_000_000
        or shadow.get("failure") != "ValueError('pending input exceeded wall wait')"
        or motion.get("anchor_ns") is not None
        or motion.get("support_steps") != 0
        or motion.get("recorded_commands") != 0
        or result.get("px4_ulogs") != []
        or result.get("eligible_for_px4_fusion") is not False
        or any(manifest.get(key) is not False for key in FALSE_CLAIMS)
        or audit.get("complete_physical_execution_qualified") is not False
        or audit.get("runtime_mapping_coverage_verified") is not False
        or audit.get("runtime_closure_qualified") is not False
        or audit.get("vio_accuracy_qualified") is not False
        or audit.get("estimator_health_qualified") is not False
        or audit.get("fusion_eligible") is not False
        or audit.get("flight_ready") is not False
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
        audit.get("schema") != "causal-pair-simulation-time-physical-attempt-audit-v1"
        or audit.get("failures") != []
        or audit.get("failure_evidence_qualified") is not True
        or audit.get("classification") != "camera-pair-wall-age-slow-simulation-refusal"
        or audit.get("pair_wall_age_ns") != 355_099_344
        or audit.get("idle_wall_age_ns") != 294_079_878
        or audit.get("pair_sim_age_ns") != 0
        or audit.get("fixed_replay_camera_released") is not True
        or audit.get("simulation_silence_refused") is not True
        or audit.get("physical_retry_performed") is not True
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
                manifest.get("schema") != "causal-pair-simulation-time-evidence-v1"
                or manifest.get("member_count_without_manifest") != len(members or [])
                or not isinstance(members, list)
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
    authorization_path = output / "causal-pair-simulation-time-authorization.json"
    authorization = {
        "schema": "causal-pair-simulation-time-authorization-v1",
        "source_manifest": record(source / "study-manifest.json"),
        "source_audit": record(source_audit),
        "completion": record(completion),
        "correction_audit": record(correction_audit),
        "correction_archive": {**record(correction_archive), "sha256": ARCHIVE_SHA256},
        "pair_wall_age_ns": source_result["pair_wall_age_ns"],
        "idle_wall_age_ns": source_result["idle_wall_age_ns"],
        "pair_sim_age_ns": source_result["pair_sim_age_ns"],
        "fixed_replay_camera_released": correction["fixed_replay_camera_released"],
        "simulation_silence_refused": correction["simulation_silence_refused"],
        "pair_sim_wait_ns": 250_000_000,
        "timeout_increased": False,
        "old_frame_repeated": False,
        "physical_run": False,
        **{key: False for key in FALSE_CLAIMS},
    }
    write_manifest(authorization_path, authorization)

    binding = copy.deepcopy(source_binding)
    _add_missing(binding["inventory"], "runtime:causal-pair-sim-time-code", [str((root / name).resolve(strict=True)) for name in CODE_NAMES])
    _add_missing(binding["inventory"], "runtime:causal-pair-sim-time-authorization", [authorization_path])
    _add_missing(binding["inventory"], "evidence:causal-pair-sim-time-correction", [source_audit, completion, correction_audit, correction_archive])
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
        "schema": "causal-pair-simulation-time-physical-retry-preflight-v1",
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
