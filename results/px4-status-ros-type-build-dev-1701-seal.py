"""Seal one PX4 status ROS type build without copying its whole workspace."""

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/px4-status-ros-type-build-dev-1701"
OUTPUT = ROOT / "evidence/px4-status-ros-type-build-dev-1701.zip"
PARENT = ROOT / "evidence/px4-status-ros-overlay-dev-1701.zip"
PARENT_SHA = "7b822673e8753657bd1aac6d522cfb1a8c99e4abf51069678c9240435f6006c0"
SOURCE_PROFILE_SHA = "fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654"
STATUS_SHA = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
PARENT_PROFILE_SHA = "38746117fe011b1eb2179c163db0be2b01134bacbab8b4b3abd9079b9702e372"
PINNED_COMMIT = "148bdb4b8214a4d8de83029777fe8d334c74db6f"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
COMMAND = ("MAKEFLAGS=-j1 colcon build --base-paths src --packages-select px4_msgs "
           "flydrones_px4_ros2_source --executor sequential --parallel-workers 1 "
           "--event-handlers console_direct+")
PARENT_PREFIX = "results/px4-status-ros-overlay-dev-1701/source-v2/"

REQUIRED = (
    "run-profile.json", "source-verify-before-copy.json",
    "copy-verify-before-build.json", "preflight.json", "launch.json",
    "docker-colcon.log", "result.json",
    "workspace-v1/src/px4_msgs/msg/EstimatorStatus.msg",
    "workspace-v1/build-source-profile.json",
    "workspace-v1/build-source-profile.sha256",
    "workspace-v1/parent-build-source-profile.json",
    "workspace-v1/install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.msg",
    "workspace-v1/install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.idl",
    "workspace-v1/install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__struct.hpp",
    "workspace-v1/install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__type_support.hpp",
    "workspace-v1/install/px4_msgs/lib/libpx4_msgs__rosidl_typesupport_cpp.so",
)
RESULT_HASH_FIELDS = {
    "installed_status_sha256": REQUIRED[11],
    "generated_idl_sha256": REQUIRED[12],
    "generated_struct_sha256": REQUIRED[13],
    "generated_type_support_sha256": REQUIRED[14],
    "generated_type_support_library_sha256": REQUIRED[15],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_file(path: Path) -> bool:
    """Reject linked/junction ancestors, including links pointing outside the run."""
    path.relative_to(RUN)
    current = path
    while True:
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"linked evidence path: {current}")
        if current == RUN:
            break
        current = current.parent
    if path.exists() and not path.is_file():
        raise ValueError(f"non-file evidence path: {path}")
    return path.is_file()


def _json(relative: str) -> dict:
    path = RUN / relative
    if not _safe_file(path):
        raise FileNotFoundError(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"non-object evidence: {relative}")
    return value


def _reported_success(result: dict) -> bool:
    hashes = (result.get(key) for key in RESULT_HASH_FIELDS)
    return bool(
        result.get("build_started") is True
        and type(result.get("docker_exit")) is int and result["docker_exit"] == 0
        and result.get("timed_out") is False
        and result.get("launch_error") is None
        and result.get("source_after_verified") is True
        and result.get("postflight_error") is None
        and result.get("installed_status_sha256") == STATUS_SHA
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in hashes)
        and result.get("owned_container_remaining") == ""
        and result.get("container_inspection_error") is None
        and isinstance(result.get("daemon_id_before"), str)
        and bool(result["daemon_id_before"])
        and result.get("daemon_id_after") == result["daemon_id_before"]
    )


def _source_seals() -> None:
    with zipfile.ZipFile(PARENT) as parent:
        if parent.testzip() is not None:
            raise ValueError("parent overlay CRC failure")
        for relative, expected in (
                ("build-source-profile.json", SOURCE_PROFILE_SHA),
                ("src/px4_msgs/msg/EstimatorStatus.msg", STATUS_SHA)):
            data = parent.read(PARENT_PREFIX + relative)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"parent overlay member changed: {relative}")
            copied = RUN / "workspace-v1" / relative
            if not _safe_file(copied) or copied.read_bytes() != data:
                raise ValueError(f"workspace source differs from parent: {relative}")
        for relative in ("build-source-profile.sha256", "parent-build-source-profile.json"):
            copied = RUN / "workspace-v1" / relative
            if not _safe_file(copied) or copied.read_bytes() != parent.read(PARENT_PREFIX + relative):
                raise ValueError(f"workspace source seal differs from parent: {relative}")
        profile = json.loads(parent.read(PARENT_PREFIX + "build-source-profile.json"))
        source_files = profile.get("files")
        if (not isinstance(source_files, dict) or len(source_files) != 260
                or profile.get("git_commit") != PINNED_COMMIT
                or source_files.get("src/px4_msgs/msg/EstimatorStatus.msg") != STATUS_SHA):
            raise ValueError("parent source manifest differs from fixed overlay")
        source_root = RUN / "workspace-v1/src"
        actual = set()
        for directory, subdirs, files in os.walk(source_root, followlinks=False):
            for name in (*subdirs, *files):
                entry = Path(directory) / name
                if entry.is_symlink() or entry.is_junction():
                    raise ValueError(f"linked workspace source: {entry}")
            for name in files:
                actual.add((Path(directory) / name).relative_to(RUN / "workspace-v1").as_posix())
        if actual != set(source_files):
            raise ValueError("workspace source file set changed")
        for relative, expected in source_files.items():
            path = RUN / "workspace-v1" / relative
            if not _safe_file(path) or sha256(path) != expected:
                raise ValueError(f"workspace source changed: {relative}")


def _check_success(result: dict) -> None:
    if not _reported_success(result):
        raise ValueError("success label contradicts runner qualification")
    profile = _json("run-profile.json")
    preflight = _json("preflight.json")
    launch = _json("launch.json")
    copied = _json("copy-verify-before-build.json")
    before = _json("source-verify-before-copy.json")
    expected_profile = {
        "schema": "flydrones.px4_status_ros_type_build.v1",
        "source": str(ROOT / "results/px4-status-ros-overlay-dev-1701/source-v2"),
        "destination": str(RUN / "workspace-v1"),
        "source_profile_sha256": SOURCE_PROFILE_SHA,
        "parent_source_profile_sha256": PARENT_PROFILE_SHA,
        "image_id": IMAGE_ID,
        "command": COMMAND,
        "cpus": 1,
        "memory_mib": 768,
        "memory_swap_mib": 768,
        "pids_limit": 128,
        "network": "none",
        "minimum_host_free_kib": 900_000,
        "timeout_seconds": 3600,
        "run_count_limit": 1,
        "firmware_compiled_verified": False,
        "live_source_authenticated": False,
        "training_eligible": False,
    }
    if profile != expected_profile:
        raise ValueError("run profile differs from fixed command/resource pin")
    if (preflight.get("image_id") != IMAGE_ID
            or preflight.get("source_profile_sha256") != SOURCE_PROFILE_SHA
            or preflight.get("daemon_id") != result["daemon_id_before"]
            or preflight.get("running_containers") != []
            or preflight.get("existing_owned_container") != ""
            or preflight.get("competing_processes") != []
            or preflight.get("wsl_competing_processes") != []
            or preflight.get("process_observation_errors") != []
            or type(preflight.get("free_kib")) is not int
            or preflight["free_kib"] < 900_000):
        raise ValueError("preflight differs from fixed resource gate")
    command = launch.get("arguments")
    if (not isinstance(command, list) or command[:3] != ["docker", "run", "--rm"]
            or command[3:] != ["--name", "flydrones-px4-status-typebuild-v1",
                               "--cpus", "1", "--memory", "768m", "--memory-swap", "768m",
                               "--pids-limit", "128", "--network", "none", "--mount",
                               f"type=bind,source={RUN / 'workspace-v1'},target=/workspace",
                               IMAGE_ID, "bash", "-lc",
                               f"source /opt/ros/humble/setup.bash && cd /workspace && {COMMAND}"]):
        raise ValueError("launch differs from fixed Docker command")
    expected_verification = {"file_count": 260, "git_commit": PINNED_COMMIT,
                             "verified": True}
    if (before != expected_verification or copied != expected_verification
            or result.get("source_after") != expected_verification):
        raise ValueError("source verification phases disagree")
    _source_seals()
    for field, relative in RESULT_HASH_FIELDS.items():
        path = RUN / relative
        if not _safe_file(path) or sha256(path) != result.get(field):
            raise ValueError(f"post-build artifact changed: {field}")


def _selected(result: dict, success: bool) -> list[Path]:
    required = {REQUIRED[0], REQUIRED[6]}
    # A launched build must preserve its preflight, launch and actual Docker log.
    if success or result.get("build_started") is True or _safe_file(RUN / REQUIRED[4]):
        required.update(REQUIRED[:7])
    elif _safe_file(RUN / REQUIRED[3]):
        required.update(REQUIRED[:4])
    elif _safe_file(RUN / REQUIRED[2]):
        required.update(REQUIRED[:3])
    elif _safe_file(RUN / REQUIRED[1]):
        required.update(REQUIRED[:2])
    if success:
        required.update(REQUIRED)
    selected = []
    for relative in REQUIRED:
        path = RUN / relative
        present = _safe_file(path)
        if relative in required and not present:
            raise FileNotFoundError(path)
        if present:
            selected.append(path)
    return selected


def main() -> None:
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError(OUTPUT)
    if sha256(PARENT) != PARENT_SHA:
        raise ValueError("parent overlay evidence changed")
    result = _json("result.json")
    success = result.get("status") == "compiled_ros_status_type"
    if success != (result.get("compiled_status_type") is True):
        raise ValueError("status and compiled flag disagree")
    if success:
        _check_success(result)
    selected = _selected(result, success)
    selected.append(Path(__file__).resolve())
    manifest = {
        "schema": "flydrones.px4_status_ros_type_build_evidence.v1",
        "parent_overlay_zip_sha256": PARENT_SHA,
        "reported_status": result.get("status"),
        "reported_compiled_status_type": success,
        "members": {},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=OUTPUT.name + ".", suffix=".tmp",
                                         dir=OUTPUT.parent, delete=False) as temp:
            temp_name = Path(temp.name)
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for path in selected:
                relative = path.relative_to(ROOT).as_posix()
                if relative in manifest["members"]:
                    raise ValueError("duplicate evidence member")
                data = path.read_bytes()
                manifest["members"][relative] = {
                    "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                }
                archive.writestr(relative, data)
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
        with zipfile.ZipFile(temp_name) as archive:
            if archive.testzip() is not None:
                raise ValueError("evidence CRC verification failed")
            if set(archive.namelist()) != set(manifest["members"]) | {"manifest.json"}:
                raise ValueError("evidence member set changed")
            for relative, sealed in manifest["members"].items():
                data = archive.read(relative)
                if len(data) != sealed["size"] or hashlib.sha256(data).hexdigest() != sealed["sha256"]:
                    raise ValueError(f"evidence member changed: {relative}")
        # Exclusive hard-link publication avoids replacing another task's one-shot seal.
        os.link(temp_name, OUTPUT)
    finally:
        if temp_name is not None:
            temp_name.unlink(missing_ok=True)
    print(json.dumps({"zip": str(OUTPUT), "sha256": sha256(OUTPUT),
                      "members": len(manifest["members"]) + 1,
                      "reported_compiled_status_type": success}, sort_keys=True))


if __name__ == "__main__":
    main()
