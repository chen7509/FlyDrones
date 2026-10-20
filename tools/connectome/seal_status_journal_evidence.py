"""Seal the bounded offline EstimatorStatus collector and synthetic fault trial.

This does not build, publish a ROS topic, or start Docker. The archive is a
one-shot copy of selected evidence; the 263-file source remains in its pinned
parent result and is rehashed before sealing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from flydrones.connectome_training.px4_status_journal_source import verify_source  # noqa: E402
from tools.connectome.run_status_journal_build import _qualifies as _build_qualifies  # noqa: E402
from tools.connectome.run_status_journal_synthetic import (  # noqa: E402
    _audit_case,
    _qualifies,
)

BUILD = ROOT / "results/px4-status-journal-build-dev-1701-v2"
SYNTH = ROOT / "results/px4-status-journal-synthetic-dev-1701-v2"
PRIOR = ROOT / "results/px4-status-journal-synthetic-dev-1701"
PRELAUNCH = ROOT / "results/px4-status-journal-synthetic-prelaunch-dev-1701"
FINAL = ROOT / "results/px4-status-journal-final-dev-1701"
OUTPUT = ROOT / "evidence/px4-estimator-status-journal-dev-1701.zip"
PROFILE_SHA = "9b09019edaba29bee1364e67f3d2f7d31820936a1a12e6b7bc470b19c5cc3572"
MESSAGE_SHA = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
IDL_SHA = "fdbb54522edb813fc14ec656ce80362f4ec1e11a6b62c5f4a93a01036346693a"
EXPECTED_JOURNAL_SHA = {
    "normal": "c51acb744e31e3d4f210f2b3f48253e9b47e52019421327415da22913c1e2ad1",
    "fsync_eio": "13be74cea6bd730c0b245fce666fa70c229077e631b46d58ad4ceb354d59b897",
    "close_eio": "f9906ba258740e9ecb159432fc5455044724a47379db6dd50bc5c5ed6ad5f684",
    "partial_then_eio": "e0aa604ccd598e94ff80b25f27940e985feb3281b913951a2f7d36f1c5acbec7",
}
CDR_PARITY_SHA = "6648b68b101d19242c9c62adb3fdd36dbba5a7b3ab278ede5a90ade13431bc87"

BUILD_FILES = (
    "run-profile.json", "source-verify-before-copy.json",
    "copy-verify-before-build.json", "preflight.json", "launch.json",
    "docker-colcon.log", "result.json", "workspace-v1/source-profile.json",
    "workspace-v1/source-profile.sha256", "workspace-v1/parent-source-profile.json",
    "workspace-v1/src/px4_msgs/msg/EstimatorStatus.msg",
    "workspace-v1/src/flydrones_px4_status_ros2_source/CMakeLists.txt",
    "workspace-v1/src/flydrones_px4_status_ros2_source/package.xml",
    "workspace-v1/src/flydrones_px4_status_ros2_source/px4_estimator_status_source.cpp",
    "workspace-v1/install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.msg",
    "workspace-v1/install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.idl",
    "workspace-v1/install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__struct.hpp",
    "workspace-v1/install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__type_support.hpp",
    "workspace-v1/install/px4_msgs/lib/libpx4_msgs__rosidl_typesupport_cpp.so",
    "workspace-v1/install/flydrones_px4_status_ros2_source/lib/flydrones_px4_status_ros2_source/px4_estimator_status_source",
)
SYNTH_FILES = (
    "run-profile.json", "preflight.json", "launch.json", "container.log",
    "result.json", "shim.sha256", "subscriber.sha256",
    "libstatus_journal_fault.so", "tools/status_synthetic_pub.py",
    "tools/status_synthetic_cdr_check.py", "tools/status_journal_fault.c",
    "tools/status_journal_synthetic_run.sh",
)
CASE_FILES = ("publisher.exit", "publisher.log", "subscriber.exit",
              "subscriber.log", "source.jsonl")
FINAL_FILES = ("targeted-tests.txt", "targeted-final-v3.txt", "full-tests.txt", "review-red.txt",
               "review-green.txt", "full-tests-postfix.txt", "transport-isolated.txt",
               "full-tests-final.txt", "seal-red.txt", "seal-green.txt",
               "seal-integrity-red.txt", "seal-integrity-green.txt", "ruff-final.txt",
               "ruff-final-v2.txt", "ruff-final-v3.txt", "ruff-final-v4.txt",
               "diff-check.txt", "diff-check-v3.txt", "diff-check-v3-staged.txt",
               "recorded-reaudit.txt", "review-note.json")
DOCUMENTS = (
    "docs/PX4_ESTIMATOR_STATUS_JOURNAL_RESEARCH.md",
    "docs/PX4_STATUS_SOURCE_JOURNAL_SCHEMA.md",
    "docs/PX4_ESTIMATOR_STATUS_JOURNAL_REPORT.md",
    "docs/superpowers/specs/2026-10-12-px4-estimator-status-journal-design.md",
    "docs/superpowers/plans/2026-10-12-px4-estimator-status-journal.md",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file(path: Path) -> bytes:
    path.relative_to(ROOT)
    current = path
    while current != ROOT:
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"linked evidence path: {current}")
        current = current.parent
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_bytes()


def _json(path: Path) -> dict:
    value = json.loads(_file(path))
    if not isinstance(value, dict):
        raise ValueError(f"non-object evidence: {path}")
    return value


def _check_synthetic_raw(synthetic: dict) -> None:
    cases = synthetic.get("cases")
    if not isinstance(cases, dict) or set(cases) != set(EXPECTED_JOURNAL_SHA):
        raise ValueError("raw synthetic case set differs")
    for name, expected_sha in EXPECTED_JOURNAL_SHA.items():
        observed = _audit_case(name)
        if observed != cases[name] or observed.get("journal_sha256") != expected_sha:
            raise ValueError(f"raw synthetic case differs: {name}")
    parity_path = SYNTH / "normal/cdr-parity.json"
    if (_sha(_file(parity_path)) != CDR_PARITY_SHA
            or _json(parity_path) != synthetic.get("cdr_parity")
            or synthetic["cdr_parity"] != {
                "independent_cdr_parity": True, "samples": 3,
                "unavailable_ratios": ["vel_test_ratio"]}):
        raise ValueError("raw CDR parity result differs")


def _check_runs() -> None:
    build = _json(BUILD / "result.json")
    synthetic = _json(SYNTH / "result.json")
    preflight = _json(SYNTH / "preflight.json")
    verified = verify_source(BUILD / "workspace-v1", allow_build_output=True)
    if (verified != {"file_count": 263, "profile_sha256": PROFILE_SHA,
                     "verified": True}
            or build.get("source_after") != verified
            or build.get("status") != "compiled_offline_status_collector"
            or build.get("compiled_collector") is not True
            or not _build_qualifies(build)
            or preflight.get("source") != verified
            or preflight.get("build_status") != build["status"]
            or preflight.get("message_sha256") != MESSAGE_SHA
            or synthetic.get("status") != "synthetic_callback_and_faults_verified"
            or synthetic.get("qualified") is not True
            or not _qualifies(synthetic, preflight)):
        raise ValueError("build or synthetic result is not qualified")
    _check_synthetic_raw(synthetic)
    workspace = BUILD / "workspace-v1"
    artifacts = {
        "collector_binary_sha256": BUILD_FILES[19],
        "installed_status_sha256": BUILD_FILES[14],
        "generated_struct_sha256": BUILD_FILES[16],
        "generated_type_support_sha256": BUILD_FILES[17],
        "generated_type_support_library_sha256": BUILD_FILES[18],
    }
    for field, relative in artifacts.items():
        if _sha(_file(BUILD / relative)) != build.get(field):
            raise ValueError(f"built artifact changed: {field}")
    if (_sha(_file(BUILD / BUILD_FILES[10])) != MESSAGE_SHA
            or _sha(_file(BUILD / BUILD_FILES[15])) != IDL_SHA
            or preflight.get("binary_sha256") != build["collector_binary_sha256"]
            or _file(workspace / "source-profile.sha256").strip().decode("ascii") != PROFILE_SHA):
        raise ValueError("source or synthetic preflight identity changed")
    if _json(PRIOR / "result.json") != {
            "status": "preflight_failed", "started": False,
            "error": "RuntimeError('status synthetic preflight refused')"}:
        raise ValueError("prior synthetic refusal changed")
    if not _json(PRELAUNCH / "import-failure.json"):
        raise ValueError("prelaunch import failure missing")
    suite = _file(FINAL / "full-tests-final.txt").decode("utf-8")
    if ("FAILED " in suite or "ERROR " in suite
            or not re.search(r"\b\d+ passed, \d+ skipped(?:, \d+ warnings)? in ", suite)):
        raise ValueError("final full regression is not green")
    if "45 passed" not in _file(FINAL / "targeted-final-v3.txt").decode("utf-8"):
        raise ValueError("final targeted regression is not green")
    if "All checks passed!" not in _file(FINAL / "ruff-final-v4.txt").decode("utf-8"):
        raise ValueError("changed-file Ruff result missing")
    if (_file(FINAL / "diff-check.txt") or _file(FINAL / "diff-check-v3.txt")
            or _file(FINAL / "diff-check-v3-staged.txt")):
        raise ValueError("git diff --check output is not empty")


def _members() -> dict[str, bytes]:
    selected: list[Path] = []
    selected += [BUILD / name for name in BUILD_FILES]
    selected += [SYNTH / name for name in SYNTH_FILES]
    for mode in ("normal", "fsync_eio", "close_eio", "partial_then_eio"):
        selected += [SYNTH / mode / name for name in CASE_FILES]
    selected.append(SYNTH / "normal/cdr-parity.json")
    selected += [PRIOR / name for name in (
        "run-profile.json", "preflight.json", "result.json")]
    selected.append(PRELAUNCH / "import-failure.json")
    selected += [FINAL / name for name in FINAL_FILES]
    selected += [ROOT / name for name in DOCUMENTS]
    selected.append(Path(__file__).resolve())
    return {path.relative_to(ROOT).as_posix(): _file(path) for path in selected}


def _validate_output_parent(path: Path) -> None:
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("output is outside workspace") from exc
    current = path.parent
    while True:
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"linked output directory: {current}")
        if current == ROOT:
            break
        parent = current.parent
        if parent == current:
            raise ValueError("output parent does not reach workspace")
        current = parent
    if not path.parent.is_dir():
        raise ValueError("output directory missing")


def main() -> str:
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError(OUTPUT)
    _validate_output_parent(OUTPUT)
    _check_runs()
    members = _members()
    manifest = {
        "schema": "flydrones.px4_estimator_status_journal_evidence.v1",
        "source_profile_sha256": PROFILE_SHA,
        "message_sha256": MESSAGE_SHA,
        "scope": "offline build and synthetic ROS callback/fault validation only",
        "live_px4_source_authenticated": False,
        "training_eligible": False,
        "members": {name: {"sha256": _sha(data), "size": len(data)}
                    for name, data in sorted(members.items())},
    }
    members["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, prefix=".status-journal-",
                                     suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(members.items()):
                archive.writestr(name, data)
        with zipfile.ZipFile(temporary_path) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(members):
                raise ValueError("archive member/CRC validation failed")
            for name, data in members.items():
                if archive.read(name) != data:
                    raise ValueError(f"archive member changed: {name}")
        _validate_output_parent(OUTPUT)
        os.link(temporary_path, OUTPUT)
        return _sha(_file(OUTPUT))
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print(main())
