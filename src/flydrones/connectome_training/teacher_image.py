"""Bounded, read-only inspection of the pinned EGO-Swarm teacher image.

This proves a source checkout and installed executables exist in the image. It
does not prove that those binaries were built from the checkout or can plan a
trajectory in the benchmark world.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from .corpus_config import EGO_COMMIT, EGO_IMAGE_ID

_UPSTREAM = "https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git"
_SOURCE = "/ego_ws/src/ego-planner-swarm"
_BINARIES = (
    "/ego_ws/install/ego_planner/lib/ego_planner/ego_planner_node",
    "/ego_ws/install/ego_planner/lib/ego_planner/traj_server",
)
_EXECUTABLES = {"ego_planner ego_planner_node", "ego_planner traj_server"}
_HASH_LINE = re.compile(r"([0-9a-f]{64})  (/ego_ws/install/ego_planner/lib/ego_planner/[^\n]+)\Z")
_OUTPUT_LIMIT = 65536


class _CleanupUnverified(RuntimeError):
    def __init__(self, name: str, stdout: str, stderr: str, cleanup: dict):
        super().__init__(f"owned Docker container cleanup unverified: {name}")
        self.stdout = stdout
        self.stderr = stderr
        self.cleanup = cleanup


def _cleanup_owned(name: str) -> dict:
    args = ["docker", "rm", "-f", name]
    record = {"label": "owned container cleanup", "argv": args,
              "stdout": "", "stderr": "", "returncode": None}
    try:
        result = _bounded_run(args, capture_output=True, text=True, timeout=5, check=False)
        record.update(stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record["stderr"] = f"{type(exc).__name__}: {exc}"[:_OUTPUT_LIMIT]
    return record


def _bounded_run(
    args: list[str], *, capture_output: bool, text: bool, timeout: int, check: bool,
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes concurrently without retaining more than the evidence limit."""
    assert capture_output and text and not check
    owned_name = args[args.index("--name") + 1] if "--name" in args else None
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = [bytearray(), bytearray()]
    oversized = threading.Event()

    def drain(pipe, buffer: bytearray) -> None:
        try:
            while chunk := pipe.read(4096):
                if len(buffer) < _OUTPUT_LIMIT + 1:
                    buffer.extend(chunk[:_OUTPUT_LIMIT + 1 - len(buffer)])
                if len(buffer) > _OUTPUT_LIMIT:
                    oversized.set()
        finally:
            pipe.close()

    threads = [
        threading.Thread(target=drain, args=(pipe, buffer), daemon=True)
        for pipe, buffer in zip((proc.stdout, proc.stderr), buffers, strict=True)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    interrupted = False
    while proc.poll() is None:
        if oversized.is_set() or time.monotonic() >= deadline:
            interrupted = True
            proc.kill()
            break
        time.sleep(0.01)
    proc.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)
    stdout, stderr = (_text(bytes(buffer)) for buffer in buffers)
    if any(thread.is_alive() for thread in threads):
        interrupted = True
    if interrupted and owned_name is not None:
        # Only the uniquely named container created by this invocation is targeted.
        cleanup_record = _cleanup_owned(owned_name)
        if cleanup_record["returncode"] != 0:
            raise _CleanupUnverified(owned_name, stdout, stderr, cleanup_record)
    if interrupted and not oversized.is_set():
        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(args, 125 if oversized.is_set() else proc.returncode, stdout, stderr)


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf8", errors="replace") if isinstance(value, bytes) else value


def inspect_pinned_ego_image(
    output: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = _bounded_run,
) -> dict:
    """Inspect the immutable image with no network, writes, planner or simulator.

    A fresh output directory is required; failure retains every attempted
    command and its bounded output instead of leaving an ambiguous boolean.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    evidence: dict = {
        "schema": "flydrones-ego-image-inspection-v1",
        "inspected": False,
        "image_id": EGO_IMAGE_ID,
        "upstream_commit": EGO_COMMIT,
        "upstream_repository": _UPSTREAM,
        "commands": [],
        "executables": {},
        "planner_executed": False,
        "trajectory_produced": False,
        "student_capture_authorized": False,
    }

    def invoke(label: str, args: list[str]) -> str:
        record: dict = {"label": label, "argv": args, "stdout": "", "stderr": "", "returncode": None}
        evidence["commands"].append(record)
        try:
            result = run(args, capture_output=True, text=True, timeout=20, check=False)
        except _CleanupUnverified as exc:
            record["stdout"] = exc.stdout
            record["stderr"] = exc.stderr
            evidence["commands"].append(exc.cleanup)
            raise ValueError(f"{label} cleanup unverified") from exc
        except subprocess.TimeoutExpired as exc:
            record["stdout"] = _text(exc.output)[:65536]
            record["stderr"] = _text(exc.stderr)[:65536]
            raise ValueError(f"{label} timeout") from exc
        except OSError as exc:
            record["stderr"] = f"{type(exc).__name__}: {exc}"[:65536]
            raise ValueError(f"{label} launch failed") from exc
        record["stdout"] = _text(result.stdout)[:65536]
        record["stderr"] = _text(result.stderr)[:65536]
        record["returncode"] = result.returncode
        if (result.returncode != 0 or len(_text(result.stdout)) > 65536
                or len(_text(result.stderr)) > 65536):
            raise ValueError(f"{label} failed or exceeded output limit")
        return record["stdout"]

    def container(label: str, program: str, *arguments: str) -> str:
        return invoke(label, [
            "docker", "run", "--rm", "--pull=never",
            "--name", f"flydrones-ego-inspect-{uuid.uuid4().hex}",
            "--memory", "256m", "--cpus", "0.25",
            "--network", "none", "--read-only", "--pids-limit", "64",
            "--entrypoint", "/usr/bin/timeout", EGO_IMAGE_ID,
            "15s", program, *arguments,
        ])

    try:
        image = invoke("image ID", ["docker", "image", "inspect", EGO_IMAGE_ID, "--format", "{{.Id}}"])
        if image != EGO_IMAGE_ID + "\n":
            raise ValueError("image ID mismatch")
        head = container("upstream commit", "git", "-C", _SOURCE, "rev-parse", "HEAD")
        if head != EGO_COMMIT + "\n":
            raise ValueError("upstream commit mismatch")
        if container("clean worktree", "git", "-C", _SOURCE, "status", "--porcelain") != "":
            raise ValueError("dirty upstream worktree")
        remote = container(
            "upstream remote", "git", "-C", _SOURCE,
            "config", "--local", "--get-all", "remote.origin.url",
        )
        if remote != _UPSTREAM + "\n":
            raise ValueError("upstream remote mismatch")
        listed = container(
            "ROS executables", "bash", "-lc",
            "source /opt/ros/humble/setup.bash && source /ego_ws/install/setup.bash "
            "&& ros2 pkg executables ego_planner",
        )
        if set(listed.splitlines()) != _EXECUTABLES or len(listed.splitlines()) != len(_EXECUTABLES):
            raise ValueError("ROS executables mismatch")
        hashes = container("binary hashes", "sha256sum", *_BINARIES)
        parsed = {}
        for line in hashes.splitlines():
            match = _HASH_LINE.fullmatch(line)
            if match is None or match.group(2) in parsed:
                raise ValueError("binary hashes invalid")
            parsed[match.group(2)] = match.group(1)
        if set(parsed) != set(_BINARIES):
            raise ValueError("binary hashes incomplete")
        evidence["executables"] = parsed
        evidence["inspected"] = True
    except BaseException as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        with (output / "inspection.json").open("x", encoding="utf8") as stream:
            json.dump(evidence, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    return evidence
