"""One bounded offline ROS build for the independent PX4 status journal.

This does not start PX4, Gazebo, an Agent, or a ROS publisher. A successful
build never authenticates a live estimator source or grants student capture.
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
from flydrones.connectome_training.px4_status_journal_source import (  # noqa: E402
    BUILD_COMMAND,
    PX4_STATUS_SHA256,
    verify_source,
)
from tools.connectome.run_byte_bound_ros_build import _docker_build_command  # noqa: E402
from tools.connectome.run_status_ros_type_build import (  # noqa: E402
    _command_sensitive_name,
    _is_competitor,
    _windows_process_name,
    _wsl_competitors,
)

SOURCE = ROOT / "results/px4-status-journal-source-dev-1701/source-v2"
RESULT = ROOT / "results/px4-status-journal-build-dev-1701-v2"
WORKSPACE = RESULT / "workspace-v1"
SOURCE_PROFILE_SHA256 = "9b09019edaba29bee1364e67f3d2f7d31820936a1a12e6b7bc470b19c5cc3572"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
CONTAINER = "flydrones-px4-status-journal-build-v2"
MIN_FREE_KIB = 900_000
TIMEOUT_SECONDS = 3_600
GENERATED = {
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
BINARY = (
    "install/flydrones_px4_status_ros2_source/lib/"
    "flydrones_px4_status_ros2_source/px4_estimator_status_source"
)
_INACCESSIBLE = object()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(name: str, value: dict) -> None:
    with (RESULT / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def _profile() -> dict:
    return {
        "schema": "flydrones.px4_status_journal_build.v1",
        "source": str(SOURCE), "destination": str(WORKSPACE),
        "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "image_id": IMAGE_ID, "command": BUILD_COMMAND,
        "cpus": 1, "memory_mib": 768, "memory_swap_mib": 768,
        "pids_limit": 128, "network": "none",
        "minimum_host_free_kib": MIN_FREE_KIB,
        "timeout_seconds": TIMEOUT_SECONDS, "run_count_limit": 1,
        "firmware_compiled_verified": False,
        "live_source_authenticated": False, "training_eligible": False,
    }


def _docker_output(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True,
        check=True, timeout=15,
    ).stdout.strip()


def _preflight() -> dict:
    image_id = _docker_output("image", "inspect", IMAGE_ID, "--format", "{{.Id}}")
    daemon_id = _docker_output("info", "--format", "{{.ID}}")
    containers = _docker_output("ps", "--format", "{{.ID}}").splitlines()
    owned = _docker_output("ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}")
    competitors = []
    errors = []
    opaque = 0
    for process in psutil.process_iter(["pid", "name", "cmdline"], ad_value=_INACCESSIBLE):
        if process.pid == os.getpid():
            continue
        try:
            name, argv = process.info["name"], process.info["cmdline"]
            if name is _INACCESSIBLE or name is None or not name:
                try:
                    name = _windows_process_name(process.pid)
                except Exception as exc:
                    errors.append({"pid": process.pid, "reason": "inaccessible_process_name",
                                   "error": repr(exc)})
                    continue
            name = name.lower()
            if argv is _INACCESSIBLE or argv is None:
                if _command_sensitive_name(name):
                    errors.append({"pid": process.pid, "name": name,
                                   "reason": "inaccessible_launcher_command"})
                else:
                    opaque += 1
                continue
            command = " ".join(argv).lower()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            errors.append({"pid": process.pid, "reason": "access_denied"})
            continue
        if (_is_competitor(name, command)
                or name in {"docker", "docker.exe"} and _docker_build_command(argv)):
            competitors.append({"pid": process.pid, "name": name, "command": command[:500]})
    wsl_competitors = _wsl_competitors()
    record = {
        "free_kib": psutil.virtual_memory().available // 1024,
        "minimum_free_kib": MIN_FREE_KIB,
        "image_id": image_id, "daemon_id": daemon_id,
        "running_containers": containers, "existing_owned_container": owned,
        "competing_processes": competitors, "process_observation_errors": errors,
        "opaque_nonlauncher_process_count": opaque,
        "wsl_competing_processes": wsl_competitors,
        "source_profile_sha256": _hash(SOURCE / "source-profile.json"),
    }
    _write("preflight.json", record)
    if (record["free_kib"] < MIN_FREE_KIB or image_id != IMAGE_ID
            or not daemon_id or "\n" in daemon_id or containers or owned
            or competitors or errors or wsl_competitors
            or record["source_profile_sha256"] != SOURCE_PROFILE_SHA256):
        raise RuntimeError("status journal build preflight refused")
    return record


def _artifact_hash(path: Path) -> str | None:
    if (not path.is_file() or path.stat().st_size == 0
            or any(parent.is_symlink() for parent in (path, *path.parents))):
        return None
    return _hash(path)


def _qualifies(result: dict) -> bool:
    return bool(
        result.get("build_started") is True and result.get("docker_exit") == 0
        and result.get("timed_out") is False and result.get("launch_error") is None
        and result.get("source_after_verified") is True
        and result.get("postflight_error") is None
        and result.get("installed_status_sha256") == PX4_STATUS_SHA256
        and all(isinstance(result.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", result[key])
                for key in (*GENERATED, "collector_binary_sha256"))
        and result.get("owned_container_remaining") == ""
        and result.get("container_inspection_error") is None
        and bool(result.get("daemon_id_before"))
        and result.get("daemon_id_after") == result["daemon_id_before"]
    )


def main() -> int:
    if RESULT.exists():
        raise FileExistsError("one-shot status journal build result already exists")
    RESULT.mkdir(parents=True)
    _write("run-profile.json", _profile())
    try:
        source_check = verify_source(SOURCE)
        if (source_check["file_count"] != 263
                or source_check["profile_sha256"] != SOURCE_PROFILE_SHA256):
            raise RuntimeError("source differs from fixed journal source pin")
        _write("source-verify-before-copy.json", source_check)
        shutil.copytree(SOURCE, WORKSPACE)
        copy_check = verify_source(WORKSPACE)
        if copy_check != source_check:
            raise RuntimeError("journal source copy differs from pin")
        _write("copy-verify-before-build.json", copy_check)
        preflight = _preflight()
    except Exception as exc:
        _write("result.json", {"status": "preflight_failed", "build_started": False,
                               "error": repr(exc), "compiled_collector": False})
        raise

    command = [
        "docker", "run", "--rm", "--name", CONTAINER,
        "--cpus", "1", "--memory", "768m", "--memory-swap", "768m",
        "--pids-limit", "128", "--network", "none",
        "--mount", f"type=bind,source={WORKSPACE},target=/workspace",
        IMAGE_ID, "bash", "-lc",
        f"source /opt/ros/humble/setup.bash && cd /workspace && {BUILD_COMMAND}",
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
        "status": "build_failed", "build_started": worker_started,
        "compiled_collector": False, "docker_exit": exit_code,
        "launch_error": launch_error, "timed_out": timed_out,
        "timeout_cleanup": timeout_cleanup,
        "elapsed_seconds": time.monotonic() - started,
        "daemon_id_before": preflight["daemon_id"],
    }
    try:
        result["source_after"] = verify_source(WORKSPACE, allow_build_output=True)
        result["source_after_verified"] = result["source_after"] == copy_check
    except Exception as exc:
        result["source_after_verified"] = False
        result["source_after_error"] = repr(exc)
    try:
        result["installed_status_sha256"] = _artifact_hash(
            WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.msg")
        result["collector_binary_sha256"] = _artifact_hash(WORKSPACE / BINARY)
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
        result["status"] = "compiled_offline_status_collector"
        result["compiled_collector"] = True
    _write("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["compiled_collector"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
