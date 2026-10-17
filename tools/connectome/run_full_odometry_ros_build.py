"""One bounded, exact-source ROS build for the opt-in full-state odometry journal.

This does not start PX4, Gazebo, an Agent, training, or a DDS publisher.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flydrones.connectome_training.px4_ros2_build_source import (  # noqa: E402
    BUILD_COMMAND_V2,
    PINNED_COMMIT,
    PINNED_MESSAGE_SHA256,
    verify_workspace,
)

SOURCE = ROOT / "results/px4-ros2-full-byte-build-dev-1701/source-v1"
RESULT = ROOT / "results/px4-ros2-full-build-attempt-dev-1701"
WORKSPACE = RESULT / "workspace-v1"
CONTAINER = "flydrones-px4-ros2-fullbuild-v1"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
SOURCE_PROFILE_SHA256 = "38746117fe011b1eb2179c163db0be2b01134bacbab8b4b3abd9079b9702e372"
MIN_FREE_KIB = 900_000
TIMEOUT_SECONDS = 3_600


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(name: str, value: dict) -> None:
    (RESULT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _preflight() -> dict:
    image_id = subprocess.run(
        ["docker", "image", "inspect", "fly-ego-benchmark:humble", "--format", "{{.Id}}"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()
    containers = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip().splitlines()
    competitors = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        if process.pid == os.getpid():
            continue
        try:
            name = (process.info["name"] or "").lower()
            command = " ".join(process.info["cmdline"] or []).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if (name in {"px4", "gz", "gzserver", "gazebo", "colcon"}
                or ("python" in name and any(
                    token in command for token in ("pytest", "train", "openvins")))):
            competitors.append({"pid": process.pid, "name": name, "command": command[:500]})
    record = {
        "free_kib": psutil.virtual_memory().available // 1024,
        "minimum_free_kib": MIN_FREE_KIB,
        "running_containers": containers,
        "competing_processes": competitors,
        "image_id": image_id,
        "source_profile_sha256": _hash(SOURCE / "build-source-profile.json"),
    }
    _write("preflight.json", record)
    if (record["free_kib"] < MIN_FREE_KIB or containers or competitors
            or image_id != IMAGE_ID or record["source_profile_sha256"] != SOURCE_PROFILE_SHA256):
        raise RuntimeError("full-state build preflight refused")
    return record


def main() -> int:
    if RESULT.exists():
        raise FileExistsError("one-shot full-state build result already exists")
    RESULT.mkdir(parents=True)
    _write("run-profile.json", {
        "schema": "flydrones.px4_ros2_full_build.v1",
        "image_id": IMAGE_ID,
        "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "command": BUILD_COMMAND_V2,
        "cpus": 1,
        "memory_mib": 768,
        "memory_swap_mib": 768,
        "pids_limit": 128,
        "network": "none",
        "minimum_host_free_kib": MIN_FREE_KIB,
        "timeout_seconds": TIMEOUT_SECONDS,
        "run_count_limit": 1,
    })
    try:
        source_check = verify_workspace(SOURCE)
        profile = json.loads((SOURCE / "build-source-profile.json").read_text(encoding="utf-8"))
        if (profile["schema"] != "flydrones.px4_ros2_build_source.v2"
                or profile["git_commit"] != PINNED_COMMIT
                or profile["vehicle_odometry_sha256"] != PINNED_MESSAGE_SHA256
                or profile["build_command"] != BUILD_COMMAND_V2):
            raise RuntimeError("source profile differs from full-state pin")
        _write("source-verify-before-copy.json", source_check)
        shutil.copytree(SOURCE, WORKSPACE)
        _write("copy-verify-before-build.json", verify_workspace(WORKSPACE))
        _preflight()
    except Exception as exc:
        _write("result.json", {"status": "preflight_failed", "build_started": False,
                               "error": repr(exc)})
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
    timed_out = False
    timeout_cleanup = None
    exit_code = None
    launch_error = None
    worker_started = False
    with (RESULT / "docker-colcon.log").open("wb") as output:
        try:
            worker = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            worker_started = True
            try:
                exit_code = worker.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    cleanup = subprocess.run(
                        ["docker", "rm", "-f", CONTAINER],
                        capture_output=True, text=True, timeout=30,
                    )
                    timeout_cleanup = {"returncode": cleanup.returncode,
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
    try:
        post = verify_workspace(WORKSPACE)
        post_error = None
    except Exception as exc:
        post = None
        post_error = repr(exc)
    binary = (WORKSPACE / "install/flydrones_px4_ros2_source/lib/"
              "flydrones_px4_ros2_source/px4_odometry_source")
    installed_msg = WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/VehicleOdometry.msg"
    try:
        remaining = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()
        remaining_error = None
    except Exception as exc:
        remaining = None
        remaining_error = repr(exc)
    result = {
        "status": "build_succeeded" if (exit_code == 0 and not timed_out and not remaining
                                        and remaining_error is None and post_error is None
                                        and binary.is_file() and installed_msg.is_file()
                                        and _hash(installed_msg) == PINNED_MESSAGE_SHA256)
        else "build_failed",
        "build_started": worker_started, "docker_exit": exit_code,
        "launch_error": launch_error, "timed_out": timed_out,
        "timeout_cleanup": timeout_cleanup, "elapsed_seconds": time.monotonic() - started,
        "source_after": post, "source_after_error": post_error,
        "binary_sha256": _hash(binary) if binary.is_file() else None,
        "installed_message_sha256": _hash(installed_msg) if installed_msg.is_file() else None,
        "owned_container_remaining": remaining, "container_inspection_error": remaining_error,
    }
    _write("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "build_succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
