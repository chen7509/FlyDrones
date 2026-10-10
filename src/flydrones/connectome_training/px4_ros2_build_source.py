"""Prepare and verify the exact source tree consumed by a bounded ROS build.

This module never runs colcon, Docker, PX4, or a flight controller.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

PINNED_COMMIT = "148bdb4b8214a4d8de83029777fe8d334c74db6f"
PINNED_MESSAGE_SHA256 = "a528b3d0b4c1a9083a71b32c367bad71a900e959efd82b9d03a9eb0e99fe6017"
BUILD_COMMAND = (
    "colcon build --base-paths src --packages-select px4_msgs "
    "flydrones_px4_ros2_source --executor sequential --parallel-workers 1 "
    "--event-handlers console_direct+"
)
BUILD_COMMAND_V2 = "MAKEFLAGS=-j1 " + BUILD_COMMAND
COLLECTOR_FILES = ("CMakeLists.txt", "package.xml", "px4_odometry_source.cpp", "README.md")
FULL_COLLECTOR_FILES = COLLECTOR_FILES + ("full_odometry_fields.hpp",)
MAX_FILES = 2000
MAX_FILE_BYTES = 10_000_000


def _git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if os.name == "nt" and is_junction is None:
        raise RuntimeError("Windows source verification requires Python 3.12 junction detection")
    return path.is_symlink() or (is_junction is not None and is_junction())


def _safe_git_path(raw: bytes) -> PurePosixPath:
    name = raw.decode("utf-8")
    path = PurePosixPath(name)
    if (not name or name.startswith("/") or "\\" in name or ":" in name
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("unsafe git path")
    return path


def prepare_workspace(
    repo: Path,
    commit: str,
    collector: Path,
    destination: Path,
    *,
    expected_message_sha256: str | None = None,
    collector_files: tuple[str, ...] = COLLECTOR_FILES,
) -> dict:
    """Copy Git blob bytes, not checkout bytes, to the colcon-selected src tree."""
    repo, collector, destination = Path(repo), Path(collector), Path(destination)
    if os.name == "nt" and not hasattr(Path, "is_junction"):
        raise RuntimeError("Windows source preparation requires Python 3.12 junction detection")
    if destination.exists():
        raise FileExistsError(destination)
    if collector_files not in (COLLECTOR_FILES, FULL_COLLECTOR_FILES):
        raise ValueError("unsupported collector file set")
    if (collector_files == COLLECTOR_FILES
            and (collector / "px4_odometry_source.cpp").is_file()
            and b'#include "full_odometry_fields.hpp"' in
            (collector / "px4_odometry_source.cpp").read_bytes()):
        raise ValueError("full-state header requires v2 source profile")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full Git object id")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != commit:
        raise ValueError("HEAD does not match fixed commit")
    if _git(repo, "cat-file", "-t", commit).decode().strip() != "commit":
        raise ValueError("fixed object is not a commit")

    tree = _git(repo, "ls-tree", "-rz", "--full-tree", commit)
    entries: list[tuple[PurePosixPath, bytes]] = []
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        metadata, separator, name = raw.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("malformed git tree entry")
        mode, kind, object_id = fields
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("unsupported git mode or object type")
        entries.append((_safe_git_path(name), object_id))
    if not entries or len(entries) > MAX_FILES or len({p for p, _ in entries}) != len(entries):
        raise ValueError("git tree file count invalid")
    for name in collector_files:
        source = collector / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"collector file missing or linked: {name}")

    destination.mkdir(parents=True, exist_ok=False)
    files: dict[str, str] = {}
    for git_path, object_id in entries:
        object_name = object_id.decode("ascii")
        if int(_git(repo, "cat-file", "-s", object_name)) > MAX_FILE_BYTES:
            raise ValueError("git blob exceeds bound")
        contents = _git(repo, "cat-file", "blob", object_name)
        target = destination / "src" / "px4_msgs" / Path(*git_path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        files[target.relative_to(destination).as_posix()] = _sha256(contents)
    for name in collector_files:
        contents = (collector / name).read_bytes()
        if len(contents) > MAX_FILE_BYTES:
            raise ValueError("collector file exceeds bound")
        target = destination / "src" / "flydrones_px4_ros2_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        files[target.relative_to(destination).as_posix()] = _sha256(contents)

    message_path = "src/px4_msgs/msg/VehicleOdometry.msg"
    if message_path not in files:
        raise ValueError("VehicleOdometry source absent")
    if expected_message_sha256 is not None and files[message_path] != expected_message_sha256:
        raise ValueError("VehicleOdometry raw Git bytes differ from pin")
    profile = {
        "schema": ("flydrones.px4_ros2_build_source.v1"
                   if collector_files == COLLECTOR_FILES else "flydrones.px4_ros2_build_source.v2"),
        "git_commit": commit,
        "git_tree": _git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip(),
        "source_root": "src",
        "build_command": BUILD_COMMAND if collector_files == COLLECTOR_FILES else BUILD_COMMAND_V2,
        "files": dict(sorted(files.items())),
        "vehicle_odometry_sha256": files[message_path],
        "build_started": False,
    }
    profile_bytes = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (destination / "build-source-profile.json").write_bytes(profile_bytes)
    (destination / "build-source-profile.sha256").write_text(_sha256(profile_bytes) + "\n", encoding="ascii")
    verify_workspace(destination)
    return profile


def derive_full_state_workspace(legacy: Path, collector: Path, destination: Path) -> dict:
    """Replace only collector bytes in a verified Git-blob source snapshot."""
    legacy, collector, destination = Path(legacy), Path(collector), Path(destination)
    verify_workspace(legacy)
    parent_bytes = (legacy / "build-source-profile.json").read_bytes()
    parent = json.loads(parent_bytes)
    if (parent.get("schema") != "flydrones.px4_ros2_build_source.v1"
            or parent.get("build_started") is not False):
        raise ValueError("legacy source profile required")
    if destination.exists():
        raise FileExistsError(destination)
    for name in FULL_COLLECTOR_FILES:
        path = collector / name
        if not path.is_file() or _is_link(path) or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"collector file missing, linked or oversized: {name}")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(legacy / "src/px4_msgs", destination / "src/px4_msgs")
    collector_target = destination / "src/flydrones_px4_ros2_source"
    collector_target.mkdir()
    files = {}
    for relative, expected_hash in parent["files"].items():
        if not relative.startswith("src/px4_msgs/"):
            continue
        copied = destination / relative
        if not copied.is_file() or _is_link(copied) or _sha256(copied.read_bytes()) != expected_hash:
            raise ValueError(f"copied Git blob changed: {relative}")
        files[relative] = expected_hash
    for name in FULL_COLLECTOR_FILES:
        contents = (collector / name).read_bytes()
        if len(contents) > MAX_FILE_BYTES:
            raise ValueError(f"collector file exceeds bound: {name}")
        target = collector_target / name
        target.write_bytes(contents)
        files[target.relative_to(destination).as_posix()] = _sha256(contents)
    message_path = "src/px4_msgs/msg/VehicleOdometry.msg"
    if files.get(message_path) != parent.get("vehicle_odometry_sha256"):
        raise ValueError("parent PX4 message pin changed")
    profile = {
        "schema": "flydrones.px4_ros2_build_source.v2",
        "git_commit": parent["git_commit"],
        "git_tree": parent["git_tree"],
        "parent_source_profile_sha256": _sha256(parent_bytes),
        "source_root": "src",
        "build_command": BUILD_COMMAND_V2,
        "files": dict(sorted(files.items())),
        "vehicle_odometry_sha256": files[message_path],
        "build_started": False,
    }
    profile_bytes = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (destination / "build-source-profile.json").write_bytes(profile_bytes)
    (destination / "build-source-profile.sha256").write_text(
        _sha256(profile_bytes) + "\n", encoding="ascii")
    verify_workspace(destination)
    return profile


def verify_workspace(destination: Path) -> dict:
    """Fail if a byte or path under the actual build src differs from its seal."""
    destination = Path(destination)
    profile_bytes = (destination / "build-source-profile.json").read_bytes()
    sealed_hash = (destination / "build-source-profile.sha256").read_text(encoding="ascii").strip()
    if _sha256(profile_bytes) != sealed_hash:
        raise ValueError("profile changed")
    profile = json.loads(profile_bytes)
    if (profile.get("schema") not in ("flydrones.px4_ros2_build_source.v1",
                                      "flydrones.px4_ros2_build_source.v2")
            or profile.get("source_root") != "src"
            or profile.get("build_command") != (
                BUILD_COMMAND if profile["schema"].endswith(".v1") else BUILD_COMMAND_V2)):
        raise ValueError("build source profile invalid")
    expected = profile.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("build source file list invalid")
    collector_names = (COLLECTOR_FILES if profile["schema"].endswith(".v1")
                       else FULL_COLLECTOR_FILES)
    if {f"src/flydrones_px4_ros2_source/{name}" for name in collector_names} != {
        name for name in expected if name.startswith("src/flydrones_px4_ros2_source/")
    }:
        raise ValueError("collector file list invalid")
    source_root = destination / "src"
    if _is_link(destination) or _is_link(source_root):
        raise ValueError("source link found")
    if not source_root.is_dir():
        raise ValueError("source root missing")
    found: dict[str, Path] = {}
    for path in source_root.rglob("*"):
        if _is_link(path):
            raise ValueError("source link found")
        if path.is_file():
            found[path.relative_to(destination).as_posix()] = path
    if found.keys() != expected.keys():
        raise ValueError("file set changed")
    for name, path in found.items():
        if _sha256(path.read_bytes()) != expected[name]:
            raise ValueError(f"source bytes changed: {name}")
    return {"file_count": len(found), "git_commit": profile["git_commit"], "verified": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--collector", type=Path, required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    prepare.add_argument("--full-state-v2", action="store_true")
    derive = subparsers.add_parser("derive-full-state")
    derive.add_argument("--legacy", type=Path, required=True)
    derive.add_argument("--collector", type=Path, required=True)
    derive.add_argument("--destination", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_workspace(
            args.repo, PINNED_COMMIT, args.collector, args.destination,
            expected_message_sha256=PINNED_MESSAGE_SHA256,
            collector_files=FULL_COLLECTOR_FILES if args.full_state_v2 else COLLECTOR_FILES,
        )
        print(json.dumps({"git_commit": result["git_commit"], "files": len(result["files"])}))
    elif args.action == "derive-full-state":
        result = derive_full_state_workspace(args.legacy, args.collector, args.destination)
        if result["git_commit"] != PINNED_COMMIT:
            raise ValueError("derived workspace has wrong commit")
        if result["vehicle_odometry_sha256"] != PINNED_MESSAGE_SHA256:
            raise ValueError("derived workspace has wrong PX4 message")
        print(json.dumps({"git_commit": result["git_commit"], "files": len(result["files"])}))
    else:
        result = verify_workspace(args.destination)
        if result["git_commit"] != PINNED_COMMIT:
            raise ValueError("prepared workspace has wrong commit")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
