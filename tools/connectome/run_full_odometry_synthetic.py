"""One bounded synthetic DDS callback and independent CDR-decoding check.

No PX4, Gazebo, Agent, live-source grant, training, or actuator topic is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flydrones.connectome_training.px4_ros2_build_source import (  # noqa: E402
    PINNED_MESSAGE_SHA256,
    verify_workspace,
)

WORKSPACE = ROOT / "results/px4-ros2-full-build-attempt-dev-1701/workspace-v1"
BUILD_RESULT = ROOT / "results/px4-ros2-full-build-attempt-dev-1701/result.json"
RESULT = ROOT / "results/px4-ros2-full-synthetic-dev-1701"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
CONTAINER = "flydrones-px4-ros2-synthetic-v1"
MIN_FREE_KIB = 900_000
MESSAGE = (
    "{timestamp: 1000100, timestamp_sample: 1000000, pose_frame: 1, "
    "position: [1.25, -2.5, 3.0], q: [1.0, 0.0, 0.0, 0.0], "
    "velocity_frame: 1, velocity: [0.1, 0.2, -0.3], "
    "angular_velocity: [0.0, 0.0, 0.5], "
    "position_variance: [0.01, 0.02, 0.03], "
    "orientation_variance: [0.001, 0.002, 0.003], "
    "velocity_variance: [0.1, 0.2, 0.3], reset_counter: 0, quality: 0}"
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(name: str, data: dict) -> None:
    (RESULT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _error(exc: Exception) -> str:
    return f"{exc!r}; stderr={getattr(exc, 'stderr', None)!r}"


def cleanup_owned_container() -> tuple[dict | None, str | None]:
    try:
        cleanup = subprocess.run(
            ["docker", "rm", "-f", CONTAINER],
            capture_output=True, text=True, timeout=15, check=False,
        )
        record = {"returncode": cleanup.returncode,
                  "stdout": cleanup.stdout, "stderr": cleanup.stderr}
        return record, None if cleanup.returncode == 0 else f"docker rm exited {cleanup.returncode}"
    except Exception as exc:
        return None, _error(exc)


def inspect_owned_container() -> tuple[str | None, str | None]:
    try:
        inspected = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$",
             "--format", "{{.ID}}"],
            check=True, capture_output=True, text=True, timeout=15,
        )
        return inspected.stdout.strip(), None
    except Exception as exc:
        return None, _error(exc)


def select_result(arguments: list[str]) -> Path:
    if arguments == []:
        return ROOT / "results/px4-ros2-full-synthetic-dev-1701"
    if arguments == ["--retry-after-preflight"]:
        prior = ROOT / "results/px4-ros2-full-synthetic-dev-1701"
        previous = json.loads((prior / "result.json").read_text(encoding="utf-8"))
        if (previous.get("status") != "preflight_failed"
                or previous.get("started") is not False
                or (prior / "launch.json").exists()):
            raise RuntimeError("only an unlaunched preflight refusal can be retried")
        return ROOT / "results/px4-ros2-full-synthetic-dev-1701-v2"
    if arguments == ["--retry-after-startup-failure"]:
        prior = ROOT / "results/px4-ros2-full-synthetic-dev-1701-v2"
        previous = json.loads((prior / "result.json").read_text(encoding="utf-8"))
        output = (prior / "container.log").read_text(encoding="utf-8")
        if (previous.get("status") != "synthetic_failed"
                or previous.get("docker_exit") != 1
                or previous.get("owned_container_remaining") != ""
                or (prior / "synthetic-v2.jsonl").exists()
                or "AMENT_TRACE_SETUP_FILES: unbound variable" not in output):
            raise RuntimeError("only the documented pre-ROS startup failure can be retried")
        return ROOT / "results/px4-ros2-full-synthetic-dev-1701-v3"
    if arguments == ["--retry-after-memory-refusal"]:
        prior = ROOT / "results/px4-ros2-full-synthetic-dev-1701-v3"
        previous = json.loads((prior / "result.json").read_text(encoding="utf-8"))
        if (previous.get("status") != "preflight_failed"
                or previous.get("started") is not False
                or (prior / "launch.json").exists()):
            raise RuntimeError("only an unlaunched v3 preflight refusal can be retried")
        return ROOT / "results/px4-ros2-full-synthetic-dev-1701-v4"
    raise SystemExit("usage: run_full_odometry_synthetic.py "
                     "[--retry-after-preflight|--retry-after-startup-failure|"
                     "--retry-after-memory-refusal]")


def main() -> int:
    if RESULT.exists():
        raise FileExistsError("synthetic result directory already exists")
    RESULT.mkdir(parents=True)
    try:
        build = json.loads(BUILD_RESULT.read_text(encoding="utf-8"))
        binary = (WORKSPACE / "install/flydrones_px4_ros2_source/lib/"
                  "flydrones_px4_ros2_source/px4_odometry_source")
        message = WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/VehicleOdometry.msg"
        image = subprocess.run(
            ["docker", "image", "inspect", "fly-ego-benchmark:humble", "--format", "{{.Id}}"],
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        containers = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}"],
            check=True, capture_output=True, text=True, timeout=15,
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
                        item in command for item in ("pytest", "train", "openvins")))):
                competitors.append({"pid": process.pid, "name": name})
        preflight = {
            "free_kib": psutil.virtual_memory().available // 1024,
            "minimum_free_kib": MIN_FREE_KIB,
            "running_containers": containers,
            "competing_processes": competitors,
            "image_id": image,
            "build_binary_sha256": _hash(binary) if binary.is_file() else None,
            "installed_message_sha256": _hash(message) if message.is_file() else None,
            "source_after": verify_workspace(WORKSPACE),
        }
        _write("preflight.json", preflight)
        if (build.get("status") != "build_succeeded" or image != IMAGE_ID
                or preflight["free_kib"] < MIN_FREE_KIB or containers or competitors
                or preflight["build_binary_sha256"] != build.get("binary_sha256")
                or preflight["installed_message_sha256"] != PINNED_MESSAGE_SHA256):
            raise RuntimeError("synthetic DDS preflight refused")
    except Exception as exc:
        _write("result.json", {"status": "preflight_failed", "error": repr(exc),
                               "started": False})
        raise

    shell = (
        "set -eo pipefail\n"
        "source /opt/ros/humble/setup.bash\n"
        "source /workspace/install/setup.bash\n"
        "set -u\n"
        "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp\n"
        "/workspace/install/flydrones_px4_ros2_source/lib/"
        "flydrones_px4_ros2_source/px4_odometry_source "
        "/evidence/synthetic-v2.jsonl synthetic-v2 15 1 --full-state-v2 "
        ">/evidence/subscriber.log 2>&1 &\n"
        "subscriber_pid=$!\n"
        "sleep 2\n"
        "timeout 12 ros2 topic pub --once -w 1 /fmu/out/vehicle_odometry "
        f"px4_msgs/msg/VehicleOdometry '{MESSAGE}' "
        ">/evidence/publisher.log 2>&1\n"
        "wait \"$subscriber_pid\"\n"
        "python3 /repo/tools/connectome/check_full_odometry_cdr_parity.py "
        "/evidence/synthetic-v2.jsonl >/evidence/parity.json\n"
    )
    command = [
        "docker", "run", "--rm", "--name", CONTAINER, "--cpus", "1",
        "--memory", "512m", "--memory-swap", "512m", "--pids-limit", "64",
        "--network", "none",
        "--mount", f"type=bind,source={WORKSPACE},target=/workspace,readonly",
        "--mount", f"type=bind,source={RESULT},target=/evidence",
        "--mount", f"type=bind,source={ROOT},target=/repo,readonly",
        IMAGE_ID, "bash", "-lc", shell,
    ]
    _write("launch.json", {"arguments": command, "started_unix_ns": time.time_ns(),
                           "parity_script_sha256": _hash(
                               ROOT / "tools/connectome/check_full_odometry_cdr_parity.py")})
    started = time.monotonic()
    cleanup, cleanup_error = None, None
    try:
        with (RESULT / "container.log").open("wb") as output:
            completed = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                       timeout=60, check=False)
        exit_code, timed_out, launch_error = completed.returncode, False, None
    except subprocess.TimeoutExpired:
        timed_out, exit_code, launch_error = True, None, None
        cleanup, cleanup_error = cleanup_owned_container()
        _write("timeout-cleanup.json", {"attempt": cleanup,
                                        "error": cleanup_error})
    except Exception as exc:
        timed_out, exit_code, launch_error = False, None, repr(exc)
    remaining, inspection_error = inspect_owned_container()
    parity = RESULT / "parity.json"
    result = {
        "status": "synthetic_passed" if (exit_code == 0 and not timed_out
                                           and cleanup_error is None
                                           and inspection_error is None
                                           and remaining == "" and parity.is_file())
        else "synthetic_failed",
        "docker_exit": exit_code, "timed_out": timed_out,
        "launch_error": launch_error, "elapsed_seconds": time.monotonic() - started,
        "timeout_cleanup": cleanup, "timeout_cleanup_error": cleanup_error,
        "owned_container_remaining": remaining,
        "owned_container_inspection_error": inspection_error,
        "journal_sha256": _hash(RESULT / "synthetic-v2.jsonl")
        if (RESULT / "synthetic-v2.jsonl").is_file() else None,
        "parity_sha256": _hash(parity) if parity.is_file() else None,
        "eligible_for_live_capture": False,
    }
    _write("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "synthetic_passed" else 1


if __name__ == "__main__":
    RESULT = select_result(sys.argv[1:])
    raise SystemExit(main())
