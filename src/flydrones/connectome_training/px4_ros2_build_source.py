"""Prepare and verify the exact source tree consumed by a bounded ROS build.

This module never runs colcon, Docker, PX4, or a flight controller.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

PINNED_COMMIT = "148bdb4b8214a4d8de83029777fe8d334c74db6f"
PINNED_MESSAGE_SHA256 = "a528b3d0b4c1a9083a71b32c367bad71a900e959efd82b9d03a9eb0e99fe6017"
BUILD_COMMAND = (
    "colcon build --base-paths src --packages-select px4_msgs "
    "flydrones_px4_ros2_source --executor sequential --parallel-workers 1 "
    "--event-handlers console_direct+"
)
COLLECTOR_FILES = ("CMakeLists.txt", "package.xml", "px4_odometry_source.cpp", "README.md")
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
) -> dict:
    """Copy Git blob bytes, not checkout bytes, to the colcon-selected src tree."""
    repo, collector, destination = Path(repo), Path(collector), Path(destination)
    if os.name == "nt" and not hasattr(Path, "is_junction"):
        raise RuntimeError("Windows source preparation requires Python 3.12 junction detection")
    if destination.exists():
        raise FileExistsError(destination)
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
    for name in COLLECTOR_FILES:
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
    for name in COLLECTOR_FILES:
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
        "schema": "flydrones.px4_ros2_build_source.v1",
        "git_commit": commit,
        "git_tree": _git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip(),
        "source_root": "src",
        "build_command": BUILD_COMMAND,
        "files": dict(sorted(files.items())),
        "vehicle_odometry_sha256": files[message_path],
        "build_started": False,
    }
    profile_bytes = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (destination / "build-source-profile.json").write_bytes(profile_bytes)
    (destination / "build-source-profile.sha256").write_text(_sha256(profile_bytes) + "\n", encoding="ascii")
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
    if (profile.get("schema") != "flydrones.px4_ros2_build_source.v1"
            or profile.get("source_root") != "src"
            or profile.get("build_command") != BUILD_COMMAND):
        raise ValueError("build source profile invalid")
    expected = profile.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("build source file list invalid")
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
    verify = subparsers.add_parser("verify")
    verify.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_workspace(
            args.repo, PINNED_COMMIT, args.collector, args.destination,
            expected_message_sha256=PINNED_MESSAGE_SHA256,
        )
        print(json.dumps({"git_commit": result["git_commit"], "files": len(result["files"])}))
    else:
        result = verify_workspace(args.destination)
        if result["git_commit"] != PINNED_COMMIT:
            raise ValueError("prepared workspace has wrong commit")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
