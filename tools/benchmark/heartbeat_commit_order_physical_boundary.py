"""Build a fail-closed one-shot physical boundary for study-v21."""

from __future__ import annotations

import hashlib
import json
import string
import subprocess
import zipfile
from pathlib import Path

from tools.benchmark.audit_capture_startup_preflight import audit as audit_startup
from tools.benchmark.audit_heartbeat_commit_order_retry_preflight import audit as audit_retry_package
from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS

ARCHIVE_NAME = "heartbeat-commit-order-retry-preflight-dev-1701.zip"
ARCHIVE_SHA256 = "326f4fb4e1d113a3a8f0efe35bc96e700656e59e0a67395d46ee732a799904b5"
ARCHIVE_PREFIX = "heartbeat-commit-order-retry-preflight-dev-1701"
ARCHIVE_MANIFEST = f"{ARCHIVE_PREFIX}/manifest.json"
ARCHIVE_EVIDENCE = {
    "package_audit": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21-audit-v3-poststartup.json",
    "startup_audit": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-audit.json",
    "startup_dispatch": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-dispatch.json",
    "startup_completion": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/startup-preflight-v12-completion.json",
    "study_manifest": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21/study-manifest.json",
    "execution_contract": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21/execution-contract.json",
    "runtime_binding": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21/runtime-binding-v3.json",
    "startup_result": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21/startup-preflight-v1/result.json",
    "startup_supervisor": f"{ARCHIVE_PREFIX}/results/estimator-physical-refusal-diagnosis-dev-1701/study-v21/startup-preflight-v1/supervisor.json",
}
EXPECTED_EXECUTION = {
    "wall_budget_s": 300,
    "supervisor_s": 300,
    "simulation_duration_ns": 25_000_000_000,
    "physics_step_ns": 1_000_000,
    "imu_hz": 250,
    "rgbd_hz": 10,
    "rgbd_size": [160, 120],
    "estimator_run": True,
    "profiles": {
        "motion_profile": "supported-ready-v1",
        "physics_trace_profile": "substep-ready-v1",
        "reference_fault_profile": None,
        "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
    },
}


def _path_key(value):
    text = str(value).replace("\\", "/")
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        text = f"{text[5]}:/{text[7:]}"
    return str(Path(text).resolve()).replace("\\", "/").casefold()


def _record(path):
    return file_record(Path(path).resolve(strict=True))


def _head(path):
    value = Path(path).read_text(encoding="utf-8").strip()
    if len(value) != 40 or any(char not in string.hexdigits for char in value):
        raise ValueError("committed head format")
    return value.lower()


def current_git_head(root):
    root = Path(root).resolve(strict=True)
    commands = [["git", "rev-parse", "HEAD"]]
    if str(root).startswith("/mnt/"):
        drive = str(root)[5].upper()
        windows_root = drive + ":\\" + str(root)[7:].replace("/", "\\")
        commands.append(["/mnt/c/Program Files/Git/cmd/git.exe", "-C", windows_root, "rev-parse", "HEAD"])
    errors = []
    for command in commands:
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(repr(exc))
            continue
        value = result.stdout.strip().lower()
        if result.returncode == 0 and len(value) == 40 and all(char in string.hexdigits for char in value):
            return value
        errors.append(result.stderr.strip() or f"returncode={result.returncode}")
    raise ValueError("git head unavailable: " + "; ".join(errors))


def _verify_archive(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.name != ARCHIVE_NAME or digest != ARCHIVE_SHA256:
        raise ValueError("evidence archive identity")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if archive.testzip() is not None or len(names) != len(set(names)):
                raise ValueError("evidence archive integrity")
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST))
            members = manifest.get("members")
            if (
                manifest.get("schema") != "heartbeat-commit-order-retry-preflight-evidence-v1"
                or manifest.get("physical_run") is not False
                or manifest.get("qualified_package") != "study-v21"
                or manifest.get("startup_preflight_qualified") is not True
                or not isinstance(members, list)
                or set(names) != {item.get("path") for item in members} | {ARCHIVE_MANIFEST}
            ):
                raise ValueError("evidence archive manifest")
            for item in members:
                data = archive.read(item["path"])
                if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
                    raise ValueError("evidence archive member")
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError("evidence archive") from exc
    return {**_record(path), "sha256": digest}


def _verify_evidence_bytes(archive_path, *, study, package_audit, startup_audit, startup_dispatch, startup_completion):
    study = Path(study).resolve(strict=True)
    live = {
        "package_audit": Path(package_audit).resolve(strict=True),
        "startup_audit": Path(startup_audit).resolve(strict=True),
        "startup_dispatch": Path(startup_dispatch).resolve(strict=True),
        "startup_completion": Path(startup_completion).resolve(strict=True),
        "study_manifest": study / "study-manifest.json",
        "execution_contract": study / "execution-contract.json",
        "runtime_binding": study / "runtime-binding-v3.json",
        "startup_result": study / "startup-preflight-v1/result.json",
        "startup_supervisor": study / "startup-preflight-v1/supervisor.json",
    }
    with zipfile.ZipFile(archive_path) as archive:
        for key, archive_name in ARCHIVE_EVIDENCE.items():
            if archive.read(archive_name) != live[key].read_bytes():
                raise ValueError("evidence archive bytes:" + key)


def _require_audits(study, package_audit, startup_audit, startup_dispatch, startup_completion):
    saved_package = read_declaration(package_audit)
    live_package = audit_retry_package(study, after_startup_preflight=True)
    if (
        saved_package.get("schema") != "heartbeat-commit-order-retry-audit-v1"
        or saved_package.get("failures") != []
        or saved_package.get("prepare_qualified") is not True
        or not _typed_equal(saved_package, live_package)
    ):
        raise ValueError("live package audit")
    saved_startup = read_declaration(startup_audit)
    live_startup = audit_startup(
        Path(study) / "startup-preflight-v1",
        startup_dispatch,
        startup_completion,
        expected_head=saved_startup.get("head", ""),
    )
    if (
        saved_startup.get("schema") != "capture-startup-preflight-audit-v3"
        or saved_startup.get("failures") != []
        or saved_startup.get("startup_preflight_qualified") is not True
        or saved_startup.get("physical_execution_qualified") is not False
        or not _typed_equal(saved_startup, live_startup)
    ):
        raise ValueError("live startup audit")
    return saved_package, saved_startup


def build_boundary(
    *,
    study,
    package_audit,
    startup_audit,
    startup_dispatch,
    startup_completion,
    evidence_archive,
    expected_head,
    head_file,
    observed_git_head,
    dispatch,
    completion,
    output,
    resources,
    verify_archive_evidence=True,
):
    if resources:
        raise ValueError("competing resources")
    actual_head = _head(head_file)
    if actual_head != str(expected_head).lower() or actual_head != str(observed_git_head).lower():
        raise ValueError("committed head")
    study = Path(study).resolve(strict=True)
    destination = study / "capture-v1"
    dispatch, completion, output = (Path(path).resolve() for path in (dispatch, completion, output))
    existing = [path for path in (destination, dispatch, completion, output) if path.exists()]
    if existing:
        raise FileExistsError("one-shot output exists: " + ", ".join(map(str, existing)))
    package, startup = _require_audits(study, package_audit, startup_audit, startup_dispatch, startup_completion)
    archive = _verify_archive(evidence_archive)
    if verify_archive_evidence:
        _verify_evidence_bytes(
            evidence_archive,
            study=study,
            package_audit=package_audit,
            startup_audit=startup_audit,
            startup_dispatch=startup_dispatch,
            startup_completion=startup_completion,
        )
    manifest = read_declaration(study / "study-manifest.json")
    execution = read_declaration(study / "execution-contract.json")
    authorization = read_declaration(study / "heartbeat-commit-order-authorization.json")
    command = manifest.get("command")
    if (
        manifest.get("schema") != "heartbeat-commit-order-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or not isinstance(command, list)
        or not command
        or not all(type(item) is str and item for item in command)
        or "--output" not in command
        or _path_key(command[command.index("--output") + 1]) != _path_key(destination)
        or "--startup-preflight" in command
        or _path_key(manifest.get("future_destination", "")) != _path_key(destination)
        or not _typed_equal(manifest.get("execution_contract"), execution)
    ):
        raise ValueError("physical manifest command")
    for key, value in EXPECTED_EXECUTION.items():
        if not _typed_equal(execution.get(key), value):
            raise ValueError("execution contract:" + key)
    if (
        authorization.get("startup_timeout_ns") != 10_000_000_000
        or authorization.get("operational_timeout_ns") != 2_000_000_000
        or authorization.get("timeout_increased") is not False
        or authorization.get("old_frame_repeated") is not False
    ):
        raise ValueError("readiness limits")
    if any(manifest.get(key) is not False for key in FALSE_CLAIMS):
        raise ValueError("package overclaim")
    return {
        "schema": "heartbeat-commit-order-physical-boundary-v1",
        "study": study.as_posix(),
        "destination": destination.as_posix(),
        "command": command,
        "head": actual_head,
        "git_head_observed": str(observed_git_head).lower(),
        "head_file": _record(head_file),
        "package_audit": _record(package_audit),
        "startup_audit": _record(startup_audit),
        "startup_dispatch": _record(startup_dispatch),
        "startup_completion": _record(startup_completion),
        "evidence_archive": archive,
        "study_manifest": _record(study / "study-manifest.json"),
        "execution_contract": _record(study / "execution-contract.json"),
        "runtime_binding": _record(study / "runtime-binding-v3.json"),
        "dispatch": dispatch.as_posix(),
        "completion": completion.as_posix(),
        "output": output.as_posix(),
        "resources_before": [],
        "single_actual_attempt": True,
        "physical_run": True,
        "prepare_qualified": package["prepare_qualified"],
        "startup_preflight_qualified": startup["startup_preflight_qualified"],
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "study",
        "package-audit",
        "startup-audit",
        "startup-dispatch",
        "startup-completion",
        "evidence-archive",
        "head-file",
        "dispatch",
        "completion",
        "output",
        "boundary",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    args = vars(parser.parse_args(argv))
    boundary_path = args.pop("boundary")
    value = build_boundary(
        **args,
        observed_git_head=current_git_head(Path(__file__).resolve().parents[2]),
        resources=active_resources(),
    )
    if boundary_path.exists():
        raise FileExistsError(boundary_path)
    write_manifest(boundary_path, value)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
