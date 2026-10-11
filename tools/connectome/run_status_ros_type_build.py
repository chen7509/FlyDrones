"""One bounded offline build of the pinned EstimatorStatus ROS source overlay.

No PX4, Gazebo, Agent, publisher, subscriber, trainer or flight is started.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from flydrones.connectome_training.px4_ros2_build_source import (  # noqa: E402
    BUILD_COMMAND_V2,
    PINNED_COMMIT,
    PINNED_PARENT_V2_PROFILE_SHA256,
    PX4_STATUS_SHA256,
    STATUS_OVERLAY_SCHEMA,
    verify_workspace,
)
from tools.connectome.run_byte_bound_ros_build import _docker_build_command  # noqa: E402

SOURCE = ROOT / "results/px4-status-ros-overlay-dev-1701/source-v2"
RESULT = ROOT / "results/px4-status-ros-type-build-dev-1701"
WORKSPACE = RESULT / "workspace-v1"
CONTAINER = "flydrones-px4-status-typebuild-v1"
IMAGE = "fly-ego-benchmark:humble"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
SOURCE_PROFILE_SHA256 = "fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654"
MIN_FREE_KIB = 900_000
TIMEOUT_SECONDS = 3_600

GENERATED = {
    "generated_idl_sha256": "install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.idl",
    "generated_struct_sha256": (
        "install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__struct.hpp"
    ),
    "generated_type_support_sha256": (
        "install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/estimator_status__type_support.hpp"
    ),
    "generated_type_support_library_sha256": (
        "install/px4_msgs/lib/libpx4_msgs__rosidl_typesupport_cpp.so"
    ),
}
SOURCE_ROOT_NAMES = frozenset({
    "src", "build-source-profile.json", "build-source-profile.sha256",
    "parent-build-source-profile.json",
})
_INACCESSIBLE = object()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(name: str, value: dict) -> None:
    with (RESULT / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def _profile() -> dict:
    return {
        "schema": "flydrones.px4_status_ros_type_build.v1",
        "source": str(SOURCE),
        "destination": str(WORKSPACE),
        "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "parent_source_profile_sha256": PINNED_PARENT_V2_PROFILE_SHA256,
        "image_id": IMAGE_ID,
        "command": BUILD_COMMAND_V2,
        "cpus": 1,
        "memory_mib": 768,
        "memory_swap_mib": 768,
        "pids_limit": 128,
        "network": "none",
        "minimum_host_free_kib": MIN_FREE_KIB,
        "timeout_seconds": TIMEOUT_SECONDS,
        "run_count_limit": 1,
        "firmware_compiled_verified": False,
        "live_source_authenticated": False,
        "training_eligible": False,
    }


def _docker_output(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()


def _source_layout(root: Path) -> None:
    entries = list(root.iterdir())
    if ({entry.name for entry in entries} != SOURCE_ROOT_NAMES
            or any(entry.is_symlink() for entry in entries)
            or not (root / "src").is_dir()
            or any(not (root / name).is_file()
                   for name in SOURCE_ROOT_NAMES - {"src"})):
        raise RuntimeError("source root layout includes missing or unsealed output")


def _is_competitor(name: str, command: str) -> bool:
    name = name.lower().removesuffix(".exe")
    command = command.lower()
    return bool(
        name in {"px4", "gz", "gzserver", "gazebo", "gz-sim-server",
                 "gz-sim-gui", "colcon"}
        or re.search(r"(?:^|[\s/])gz(?:\.exe)?\s+sim(?:\s|$)", command)
        or "openvins" in name
        or ("python" in name and any(
            token in command for token in ("pytest", "train", "openvins")
        ))
    )


def _command_sensitive_name(name: str) -> bool:
    normalized = name.lower().removesuffix(".exe")
    return bool(
        normalized.startswith("python")
        or normalized in {"pwsh", "powershell", "cmd", "bash", "sh", "wsl",
                          "docker", "node", "ruby", "perl", "uv", "pytest",
                          "colcon", "cmake", "make", "ninja", "gz"}
        or _is_competitor(name, "")
    )


def _wsl_competitors() -> list[dict]:
    listed = subprocess.run(
        ["wsl.exe", "--list", "--running", "--quiet"],
        capture_output=True, check=True, timeout=15,
    )
    distros = [name.strip("\ufeff \r\n") for name in
               listed.stdout.decode("utf-16-le").splitlines()]
    if any(not name or any(ord(char) < 32 for char in name) for name in distros):
        raise RuntimeError("WSL running distribution list is malformed")
    competitors = []
    for distro in distros:
        observed = subprocess.run(
            ["wsl.exe", "--distribution", distro, "--exec", "ps", "-eo",
             "pid=,comm=,args="], capture_output=True, check=True, timeout=15,
        )
        if len(observed.stdout) > 1_000_000:
            raise RuntimeError("WSL process list exceeds bounded observation")
        for line in observed.stdout.decode("utf-8").splitlines():
            match = re.fullmatch(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
            if match is None:
                raise RuntimeError("WSL process list is malformed")
            pid, name, command = match.groups()
            if _is_competitor(name, command):
                competitors.append({"distro": distro, "pid": int(pid),
                                    "name": name, "command": command[:500]})
    return competitors


def _windows_process_name(pid: int) -> str:
    if os.name != "nt":
        raise RuntimeError("host process name is inaccessible")
    observed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-Process -Id {pid} -ErrorAction Stop).ProcessName"],
        capture_output=True, text=True, check=True, timeout=5,
    )
    name = observed.stdout.strip()
    if not name or "\n" in name or "\r" in name:
        raise RuntimeError("host process name fallback is malformed")
    return name


def _preflight() -> dict:
    image_id = _docker_output("image", "inspect", IMAGE, "--format", "{{.Id}}")
    daemon_id = _docker_output("info", "--format", "{{.ID}}")
    containers = _docker_output("ps", "--format", "{{.ID}}").splitlines()
    owned = _docker_output("ps", "-a", "--filter", f"name=^{CONTAINER}$",
                           "--format", "{{.ID}}")
    competitors = []
    observation_errors = []
    opaque_nonlauncher_count = 0
    for process in psutil.process_iter(
            ["pid", "name", "cmdline"], ad_value=_INACCESSIBLE):
        if process.pid == os.getpid():
            continue
        try:
            raw_name = process.info["name"]
            raw_argv = process.info["cmdline"]
            if raw_name is _INACCESSIBLE or raw_name is None or not raw_name:
                try:
                    raw_name = _windows_process_name(process.pid)
                except Exception as exc:
                    observation_errors.append({"pid": process.pid,
                                               "reason": "inaccessible_process_name",
                                               "fallback_error": repr(exc)})
                    continue
            name = raw_name.lower()
            if raw_argv is _INACCESSIBLE or raw_argv is None:
                if _command_sensitive_name(name):
                    observation_errors.append({"pid": process.pid,
                                               "name": name,
                                               "reason": "inaccessible_launcher_command"})
                else:
                    opaque_nonlauncher_count += 1
                continue
            argv = raw_argv
            command = " ".join(argv).lower()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            observation_errors.append({"pid": process.pid, "reason": "access_denied"})
            continue
        if (_is_competitor(name, command)
                or (name in {"docker", "docker.exe"} and _docker_build_command(argv))
                ):
            competitors.append({"pid": process.pid, "name": name,
                                "command": command[:500]})
    wsl_competitors = _wsl_competitors()
    record = {
        "free_kib": psutil.virtual_memory().available // 1024,
        "minimum_free_kib": MIN_FREE_KIB,
        "image_id": image_id,
        "daemon_id": daemon_id,
        "running_containers": containers,
        "existing_owned_container": owned,
        "competing_processes": competitors,
        "process_observation_errors": observation_errors,
        "opaque_nonlauncher_process_count": opaque_nonlauncher_count,
        "wsl_competing_processes": wsl_competitors,
        "source_profile_sha256": _hash(SOURCE / "build-source-profile.json"),
    }
    _write("preflight.json", record)
    if (record["free_kib"] < MIN_FREE_KIB or image_id != IMAGE_ID
            or not daemon_id or "\n" in daemon_id or containers or owned or competitors
            or wsl_competitors or observation_errors
            or record["source_profile_sha256"] != SOURCE_PROFILE_SHA256):
        raise RuntimeError("status type build preflight refused")
    return record


def _artifact_hash(path: Path) -> str | None:
    if (not path.is_file() or path.stat().st_size == 0
            or any(parent.is_symlink() for parent in (path, *path.parents))):
        return None
    return _hash(path)


def _qualifies(result: dict) -> bool:
    hashes = (result.get(key) for key in GENERATED)
    return bool(
        result.get("build_started") is True
        and result.get("docker_exit") == 0
        and result.get("timed_out") is False
        and result.get("launch_error") is None
        and result.get("source_after_verified") is True
        and result.get("postflight_error") is None
        and result.get("installed_status_sha256") == PX4_STATUS_SHA256
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in hashes)
        and result.get("owned_container_remaining") == ""
        and result.get("container_inspection_error") is None
        and isinstance(result.get("daemon_id_before"), str)
        and bool(result["daemon_id_before"])
        and result.get("daemon_id_after") == result["daemon_id_before"]
    )


def main() -> int:
    if RESULT.exists():
        raise FileExistsError("one-shot status type build result already exists")
    RESULT.mkdir(parents=True)
    _write("run-profile.json", _profile())
    try:
        source_check = verify_workspace(SOURCE)
        _source_layout(SOURCE)
        source_profile = json.loads((SOURCE / "build-source-profile.json").read_bytes())
        if (source_check["file_count"] != 260
                or source_check["git_commit"] != PINNED_COMMIT
                or source_profile.get("schema") != STATUS_OVERLAY_SCHEMA
                or source_profile.get("build_started") is not False
                or source_profile.get("build_command") != BUILD_COMMAND_V2
                or _hash(SOURCE / "build-source-profile.json") != SOURCE_PROFILE_SHA256):
            raise RuntimeError("source overlay differs from fixed build pin")
        _write("source-verify-before-copy.json", source_check)
        shutil.copytree(SOURCE, WORKSPACE)
        _source_layout(WORKSPACE)
        copy_check = verify_workspace(WORKSPACE)
        if copy_check != source_check or _hash(WORKSPACE / "build-source-profile.json") != SOURCE_PROFILE_SHA256:
            raise RuntimeError("source copy differs from fixed build pin")
        _write("copy-verify-before-build.json", copy_check)
        preflight = _preflight()
    except Exception as exc:
        _write("result.json", {"status": "preflight_failed", "build_started": False,
                               "error": repr(exc), "compiled_status_type": False})
        raise

    command = [
        "docker", "run", "--rm", "--name", CONTAINER,
        "--cpus", "1", "--memory", "768m", "--memory-swap", "768m",
        "--pids-limit", "128", "--network", "none",
        "--mount", f"type=bind,source={WORKSPACE},target=/workspace",
        IMAGE_ID, "bash", "-lc",
        f"source /opt/ros/humble/setup.bash && cd /workspace && {BUILD_COMMAND_V2}",
    ]
    _write("launch.json", {"arguments": command, "started_unix_ns": time.time_ns()})
    started = time.monotonic()
    exit_code = None
    launch_error = None
    timed_out = False
    timeout_cleanup = None
    worker_started = False
    with (RESULT / "docker-colcon.log").open("xb") as output:
        try:
            worker = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            worker_started = True
            try:
                exit_code = worker.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    current_daemon = _docker_output("info", "--format", "{{.ID}}")
                    if current_daemon != preflight["daemon_id"]:
                        raise RuntimeError("Docker daemon changed before owned cleanup")
                    cleanup = subprocess.run(
                        ["docker", "rm", "-f", CONTAINER],
                        capture_output=True, text=True, timeout=30,
                    )
                    timeout_cleanup = {"daemon_id": current_daemon,
                                       "returncode": cleanup.returncode,
                                       "stdout": cleanup.stdout, "stderr": cleanup.stderr}
                except Exception as exc:
                    timeout_cleanup = {"error": repr(exc)}
                try:
                    exit_code = worker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    exit_code = worker.wait(timeout=30)
        except Exception as exc:
            launch_error = repr(exc)

    result = {
        "status": "build_failed",
        "build_started": worker_started,
        "compiled_status_type": False,
        "docker_exit": exit_code,
        "launch_error": launch_error,
        "timed_out": timed_out,
        "timeout_cleanup": timeout_cleanup,
        "elapsed_seconds": time.monotonic() - started,
        "daemon_id_before": preflight["daemon_id"],
    }
    try:
        result["source_after"] = verify_workspace(WORKSPACE)
        result["source_after_verified"] = (
            result["source_after"] == copy_check
            and _hash(WORKSPACE / "build-source-profile.json") == SOURCE_PROFILE_SHA256
        )
    except Exception as exc:
        result["source_after_verified"] = False
        result["source_after_error"] = repr(exc)
    installed = WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.msg"
    try:
        result["installed_status_sha256"] = _artifact_hash(installed)
        for name, relative in GENERATED.items():
            result[name] = _artifact_hash(WORKSPACE / relative)
    except Exception as exc:
        result["postflight_error"] = repr(exc)
    try:
        result["daemon_id_after"] = _docker_output("info", "--format", "{{.ID}}")
        if result["daemon_id_after"] != preflight["daemon_id"]:
            raise RuntimeError("Docker daemon changed before owned-container inspection")
        result["owned_container_remaining"] = _docker_output(
            "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}",
        )
        result["container_inspection_error"] = None
    except Exception as exc:
        result["owned_container_remaining"] = None
        result["container_inspection_error"] = repr(exc)
    if _qualifies(result):
        result["status"] = "compiled_ros_status_type"
        result["compiled_status_type"] = True
    _write("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["compiled_status_type"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
