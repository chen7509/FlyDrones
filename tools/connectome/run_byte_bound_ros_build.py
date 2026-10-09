"""One-shot, bounded build of the already frozen ROS 2 source tree.

This diagnostic does not run PX4, Gazebo, an Agent or a publisher.
"""

from __future__ import annotations

import argparse
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
    BUILD_COMMAND,
    verify_workspace,
)

SOURCE = ROOT / "results/px4-ros2-byte-bound-dev-1701/workspace-v3"
RESULT = ROOT / "results/px4-ros2-byte-build-dev-1701"
WORKSPACE = RESULT / "workspace-v1"
CONTAINER_NAME = "flydrones-px4-ros2-bytebuild-v1"
IMAGE = "fly-ego-benchmark:humble"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
SOURCE_PROFILE_SHA256 = "cfaca8d891fd89739236efb1a263b867e4def91775bdfb6422bc55501a4004fe"
MIN_FREE_KIB = 900_000
TIMEOUT_SECONDS = 1_800


def _write_json(name: str, value: dict) -> None:
    (RESULT / name).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile() -> dict:
    return {
        "schema": "flydrones.px4_ros2_byte_build.v1",
        "image": IMAGE,
        "image_id": IMAGE_ID,
        "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "command": BUILD_COMMAND,
        "cpus": 1,
        "memory_mib": 768,
        "memory_swap_mib": 768,
        "pids_limit": 128,
        "network": "none",
        "minimum_host_free_kib": MIN_FREE_KIB,
        "timeout_seconds": TIMEOUT_SECONDS,
        "source": str(SOURCE),
        "destination": str(WORKSPACE),
        "run_count_limit": 1,
    }


def _docker_build_command(argv: list[str]) -> bool:
    args = [part.lower() for part in argv[1:]]

    def skip_options(index: int, value_options: set[str]) -> int:
        while index < len(args) and args[index].startswith("-"):
            option = args[index].split("=", 1)[0]
            index += 2 if option in value_options and "=" not in args[index] else 1
        return index

    index = skip_options(0, {
        "--config", "-c", "--context", "--host", "-h", "--log-level", "-l",
        "--tlscacert", "--tlscert", "--tlskey",
    })
    if index >= len(args):
        return False
    action = args[index]
    index += 1
    if action in {"build", "bake"}:
        return True
    if action in {"image", "builder"}:
        return index < len(args) and args[index] == "build"
    if action == "buildx":
        index = skip_options(index, {"--builder"})
        return index < len(args) and args[index] in {"build", "bake"}
    if action == "compose":
        index = skip_options(index, {
            "--file", "-f", "--project-name", "-p", "--env-file", "--profile", "--project-directory",
            "--ansi", "--progress", "--parallel",
        })
        if index >= len(args):
            return False
        if args[index] == "build":
            return True
        if args[index] != "up":
            return False
        return any(part in {"--build", "--build=true", "--build=1"} for part in args[index + 1:])
    return False


def _preflight(record_name: str = "preflight.json") -> dict:
    free_kib = psutil.virtual_memory().available // 1024
    containers = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip().splitlines()
    image_id = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()
    competing = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        if process.pid == os.getpid():
            continue
        try:
            name = (process.info["name"] or "").lower()
            argv = process.info["cmdline"] or []
            command = " ".join(argv).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        docker_build = name in {"docker", "docker.exe"} and _docker_build_command(argv)
        if (name in {"px4", "gz", "gzserver", "gazebo", "colcon"}
                or docker_build
                or ("python" in name and any(
                    token in command for token in ("pytest", "train", "openvins")
                ))):
            competing.append({"pid": process.pid, "name": name, "command": command[:500]})
    record = {
        "free_kib": free_kib,
        "minimum_free_kib": MIN_FREE_KIB,
        "running_containers": containers,
        "competing_processes": competing,
        "image_id": image_id,
        "source_profile_sha256": _hash(SOURCE / "build-source-profile.json"),
    }
    _write_json(record_name, record)
    if (free_kib < MIN_FREE_KIB or containers or competing or image_id != IMAGE_ID):
        raise RuntimeError("build preflight refused")
    return record


def main(*, resume: bool = False) -> int:
    if resume:
        if not RESULT.is_dir() or (RESULT / "launch.json").exists():
            raise RuntimeError("only an unlaunched preflight can be resumed")
        previous = json.loads((RESULT / "result.json").read_text(encoding="utf-8"))
        if previous.get("status") != "preflight_failed" or previous.get("build_started") is not False:
            raise RuntimeError("previous result is not an unlaunched preflight")
        reservation = RESULT / "resume-reserved.json"
        fd = os.open(reservation, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"pid": os.getpid(), "reserved_unix_ns": time.time_ns()}, output)
        result_name = "resume-result.json"
        try:
            profile = json.loads((RESULT / "run-profile.json").read_text(encoding="utf-8"))
            if profile != _profile():
                raise RuntimeError("saved run profile differs from immutable runner pin")
        except Exception as exc:
            _write_json(result_name, {"status": "preflight_failed", "error": repr(exc), "build_started": False})
            raise
    else:
        if RESULT.exists():
            raise FileExistsError("one-shot result directory already exists")
        RESULT.mkdir(parents=True)
        profile = _profile()
        _write_json("run-profile.json", profile)
        result_name = "result.json"
    try:
        source_check = verify_workspace(SOURCE)
        _write_json("source-verify-resume.json" if resume else "source-verify-before-copy.json", source_check)
        if not resume:
            shutil.copytree(SOURCE, WORKSPACE)
        copy_check = verify_workspace(WORKSPACE)
        _write_json("copy-verify-resume.json" if resume else "copy-verify-before-build.json", copy_check)
        preflight = _preflight("preflight-resume.json" if resume else "preflight.json")
        if (preflight["source_profile_sha256"] != SOURCE_PROFILE_SHA256
                or _hash(WORKSPACE / "build-source-profile.json") != SOURCE_PROFILE_SHA256):
            raise RuntimeError("prepared source profile differs from predeclared hash")
    except Exception as exc:
        _write_json(result_name, {"status": "preflight_failed", "error": repr(exc), "build_started": False})
        raise

    command = [
        "docker", "run", "--rm", "--name", CONTAINER_NAME,
        "--cpus", "1", "--memory", "768m", "--memory-swap", "768m",
        "--pids-limit", "128", "--network", "none",
        "--mount", f"type=bind,source={WORKSPACE},target=/workspace",
        IMAGE_ID, "bash", "-lc",
        f"source /opt/ros/humble/setup.bash && cd /workspace && {BUILD_COMMAND}",
    ]
    _write_json("launch.json", {"arguments": command, "started_unix_ns": time.time_ns()})
    print("Attempting bounded byte-source colcon build", flush=True)
    started = time.monotonic()
    timed_out = False
    docker_exit = None
    launch_error = None
    timeout_cleanup = None
    worker = None
    with (RESULT / "docker-colcon.log").open("wb") as output:
        try:
            worker = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                docker_exit = worker.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    cleanup = subprocess.run(
                        ["docker", "rm", "-f", CONTAINER_NAME],
                        capture_output=True, text=True, timeout=30,
                    )
                    timeout_cleanup = {
                        "returncode": cleanup.returncode,
                        "stdout": cleanup.stdout,
                        "stderr": cleanup.stderr,
                    }
                except Exception as exc:
                    timeout_cleanup = {"error": repr(exc)}
                try:
                    docker_exit = worker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    docker_exit = worker.wait(timeout=30)
        except Exception as exc:
            launch_error = repr(exc)
    result = {
        "status": "build_failed",
        "build_started": worker is not None,
        "docker_exit": docker_exit,
        "timed_out": timed_out,
        "timeout_cleanup": timeout_cleanup,
        "launch_error": launch_error,
        "elapsed_seconds": time.monotonic() - started,
    }
    try:
        result["source_after"] = verify_workspace(WORKSPACE)
        binary = WORKSPACE / "install/flydrones_px4_ros2_source/lib/flydrones_px4_ros2_source/px4_odometry_source"
        message = WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/VehicleOdometry.msg"
        generated = {
            "vehicle_odometry_idl": WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/VehicleOdometry.idl",
            "vehicle_odometry_struct": WORKSPACE / "install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/vehicle_odometry__struct.hpp",
            "vehicle_odometry_type_support": WORKSPACE / "install/px4_msgs/include/px4_msgs/px4_msgs/msg/detail/vehicle_odometry__type_support.hpp",
        }
        result["binary_sha256"] = _hash(binary) if binary.is_file() else None
        result["installed_message_sha256"] = _hash(message) if message.is_file() else None
        result["generated_type_sha256"] = {
            name: _hash(path) if path.is_file() else None
            for name, path in generated.items()
        }
        remaining = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER_NAME}$", "--format", "{{.ID}}"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        result["owned_container_remaining"] = remaining.stdout.strip()
        source_message = WORKSPACE / "src/px4_msgs/msg/VehicleOdometry.msg"
        result["source_message_sha256"] = _hash(source_message)
        if (docker_exit == 0 and not timed_out and launch_error is None
                and result["binary_sha256"]
                and all(result["generated_type_sha256"].values())
                and result["installed_message_sha256"] == result["source_message_sha256"]
                and not result["owned_container_remaining"]):
            result["status"] = "byte_bound_build_passed"
    except Exception as exc:
        result["postflight_error"] = repr(exc)
    _write_json(result_name, result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "byte_bound_build_passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-preflight", action="store_true")
    raise SystemExit(main(resume=parser.parse_args().resume_preflight))
