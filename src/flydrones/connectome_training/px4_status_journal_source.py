"""Derive an isolated, pinned PX4 EstimatorStatus journal ROS source tree."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .px4_ros2_build_source import (
    _has_linked_ancestor,
    _is_link,
)
from .px4_ros2_build_source import (
    verify_workspace as verify_parent_workspace,
)

PARENT_SCHEMA = "flydrones.px4_ros2_build_source.status_overlay.v1"
PX4_MSGS_COMMIT = "148bdb4b8214a4d8de83029777fe8d334c74db6f"
PARENT_PROFILE_SHA256 = "fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654"
PARENT_FILE_COUNT = 260
PX4_STATUS_SHA256 = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
COLLECTOR_FILES = ("CMakeLists.txt", "package.xml", "px4_estimator_status_source.cpp")
COLLECTOR_COMMIT = "2a475426238e06da57f34ae47cb5dd33ad00d544"
COLLECTOR_SHA256 = {
    "CMakeLists.txt": "af4a141c30495f39ba8c7051d71b31c114d187c54565e7956183fa063456faa7",
    "package.xml": "0f35c46fd75ca6039074b58ea7446b4e89d90250ec8d3d842c425e5f1de86283",
    "px4_estimator_status_source.cpp": "f52226681d1a96f88024dc654775822720f6b33f091fb8053c5f810fb458a33f",
}
SCHEMA = "flydrones.px4_status_journal_source.v1"
PACKAGE = "flydrones_px4_status_ros2_source"
BUILD_COMMAND = (
    "MAKEFLAGS=-j1 colcon build --base-paths src --packages-select px4_msgs "
    "flydrones_px4_status_ros2_source --executor sequential --parallel-workers 1 "
    "--event-handlers console_direct+"
)
STATUS_RELATIVE = "src/px4_msgs/msg/EstimatorStatus.msg"
ROOT_ENTRIES = frozenset({
    "src", "source-profile.json", "source-profile.sha256", "parent-source-profile.json",
})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob(repo: Path, name: str) -> bytes:
    """Read fixed collector Git blob bytes, independent of checkout line endings."""
    if name not in COLLECTOR_FILES:
        raise ValueError("unlisted collector file")
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob",
         f"{COLLECTOR_COMMIT}:tools/connectome/px4_status_ros2_source/{name}"],
        capture_output=True, check=True, timeout=15,
    ).stdout


def _parent(parent: Path) -> tuple[bytes, dict]:
    if _has_linked_ancestor(parent):
        raise ValueError("linked parent source path")
    observed = verify_parent_workspace(parent)
    raw = (parent / "build-source-profile.json").read_bytes()
    if _sha(raw) != PARENT_PROFILE_SHA256:
        raise ValueError("pinned status overlay profile mismatch")
    profile = json.loads(raw)
    if (profile.get("schema") != PARENT_SCHEMA
            or profile.get("git_commit") != PX4_MSGS_COMMIT
            or profile.get("build_started") is not False
            or not isinstance(profile.get("files"), dict)
            or len(profile["files"]) != PARENT_FILE_COUNT
            or profile["files"].get(STATUS_RELATIVE) != PX4_STATUS_SHA256
            or observed.get("file_count") != PARENT_FILE_COUNT):
        raise ValueError("pinned status overlay source mismatch")
    return raw, profile


def _profile(parent: dict, added: dict[str, str]) -> dict:
    expected = dict(parent["files"])
    expected.update({f"src/{PACKAGE}/{name}": digest for name, digest in added.items()})
    return {
        "schema": SCHEMA,
        "parent_source_profile_sha256": PARENT_PROFILE_SHA256,
        "px4_msgs_commit": PX4_MSGS_COMMIT,
        "collector_commit": COLLECTOR_COMMIT,
        "collector_sha256": dict(sorted(added.items())),
        "build_command": BUILD_COMMAND,
        "build_started": False,
        "files": dict(sorted(expected.items())),
        "status_message_sha256": PX4_STATUS_SHA256,
        "firmware_compiled_verified": False,
        "live_source_authenticated": False,
        "training_eligible": False,
    }


def _source_files(root: Path) -> dict[str, Path]:
    source = root / "src"
    if not source.is_dir() or _is_link(source):
        raise ValueError("status source root missing or linked")
    found = {}
    for path in source.rglob("*"):
        if _is_link(path):
            raise ValueError("linked status source member")
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path
    return found


def derive_source(parent, repo, destination):
    """Copy a verified unbuilt overlay and only three fixed Git collector blobs."""
    parent, repo, destination = Path(parent), Path(repo), Path(destination)
    if destination.exists() or _is_link(destination):
        raise FileExistsError(destination)
    if _has_linked_ancestor(destination) or _has_linked_ancestor(repo):
        raise ValueError("linked destination or repository")
    parent_bytes, parent_profile = _parent(parent)
    added = {}
    payloads = {}
    for name in COLLECTOR_FILES:
        payload = _git_blob(repo, name)
        if not payload or len(payload) > 10_000_000 or _sha(payload) != COLLECTOR_SHA256[name]:
            raise ValueError(f"fixed collector Git bytes mismatch: {name}")
        payloads[name] = payload
        added[name] = _sha(payload)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(parent / "src", destination / "src", symlinks=True)
    copied = _source_files(destination)
    if set(copied) != set(parent_profile["files"]):
        raise ValueError("copied parent source file set changed")
    for relative, expected in parent_profile["files"].items():
        if _sha(copied[relative].read_bytes()) != expected:
            raise ValueError(f"copied parent source changed: {relative}")
    package = destination / "src" / PACKAGE
    package.mkdir()
    for name, payload in payloads.items():
        (package / name).write_bytes(payload)
    profile = _profile(parent_profile, added)
    raw = (json.dumps(profile, sort_keys=True, indent=2) + "\n").encode()
    (destination / "parent-source-profile.json").write_bytes(parent_bytes)
    (destination / "source-profile.json").write_bytes(raw)
    (destination / "source-profile.sha256").write_text(_sha(raw) + "\n", encoding="ascii")
    verify_source(destination)
    return profile


def verify_source(root, *, allow_build_output: bool = False):
    """Reject changed, linked, omitted, extra or prebuilt source/output."""
    root = Path(root)
    names = {entry.name for entry in root.iterdir()} if root.is_dir() else set()
    allowed = ROOT_ENTRIES | ({"build", "install", "log"} if allow_build_output else set())
    if (_has_linked_ancestor(root) or not root.is_dir()
            or not ROOT_ENTRIES.issubset(names) or names - allowed):
        raise ValueError("status source root layout invalid")
    if any(not (root / name).is_dir() or _is_link(root / name)
           for name in names - ROOT_ENTRIES):
        raise ValueError("status build output linked or malformed")
    for name in ROOT_ENTRIES - {"src"}:
        path = root / name
        if not path.is_file() or _is_link(path):
            raise ValueError("status source profile missing or linked")
    raw = (root / "source-profile.json").read_bytes()
    if (root / "source-profile.sha256").read_text(encoding="ascii").strip() != _sha(raw):
        raise ValueError("status source profile seal changed")
    profile = json.loads(raw)
    parent_raw = (root / "parent-source-profile.json").read_bytes()
    if _sha(parent_raw) != PARENT_PROFILE_SHA256:
        raise ValueError("status source parent manifest changed")
    parent = json.loads(parent_raw)
    if (parent.get("schema") != PARENT_SCHEMA
            or parent.get("git_commit") != PX4_MSGS_COMMIT
            or parent.get("build_started") is not False
            or not isinstance(parent.get("files"), dict)
            or len(parent["files"]) != PARENT_FILE_COUNT
            or parent["files"].get(STATUS_RELATIVE) != PX4_STATUS_SHA256):
        raise ValueError("status source parent identity invalid")
    added = {name: COLLECTOR_SHA256[name] for name in COLLECTOR_FILES}
    if profile != _profile(parent, added):
        raise ValueError("status source manifest differs from fixed derivation")
    found = _source_files(root)
    if set(found) != set(profile["files"]):
        raise ValueError("status source file set changed")
    for relative, expected in profile["files"].items():
        path = found[relative]
        if path.stat().st_size > 10_000_000 or _sha(path.read_bytes()) != expected:
            raise ValueError(f"status source bytes changed: {relative}")
    return {"file_count": len(found), "profile_sha256": _sha(raw), "verified": True}
