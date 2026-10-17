"""Bounded, read-only inspection of the pinned EGO-Swarm teacher image.

This proves a source checkout and installed executables exist in the image. It
does not prove that those binaries were built from the checkout or can plan a
trajectory in the benchmark world.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
_INSPECTION_LIMIT = 65536


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


def verify_pinned_ego_inspection(path: Path, expected_sha256: str) -> dict:
    """Verify the saved inspection transcript, not planner execution or image freshness.

    The caller must pin the exact file digest before using the record. A saved
    transcript is evidence of the earlier check, not a live Docker attestation.
    """
    path = Path(path)
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("teacher inspection record digest invalid")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > _INSPECTION_LIMIT:
        raise ValueError("teacher inspection record file invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        raw = source.read(_INSPECTION_LIMIT + 1)
    after = path.lstat()
    if (len(raw) > _INSPECTION_LIMIT or before.st_dev != opened.st_dev
            or before.st_ino != opened.st_ino or before.st_size != opened.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            or len(raw) != opened.st_size):
        raise ValueError("teacher inspection record changed during read")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("teacher inspection record digest mismatch")

    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("teacher inspection record duplicate JSON key")
            result[key] = value
        return result

    try:
        record = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("teacher inspection record JSON invalid") from exc
    if (type(record) is not dict
            or set(record) != {"schema", "inspected", "image_id", "upstream_commit",
                               "upstream_repository", "commands", "executables",
                               "planner_executed", "trajectory_produced",
                               "student_capture_authorized"}
            or record["schema"] != "flydrones-ego-image-inspection-v1"
            or record["inspected"] is not True
            or record["image_id"] != EGO_IMAGE_ID
            or record["upstream_commit"] != EGO_COMMIT
            or record["upstream_repository"] != _UPSTREAM
            or any(record[key] is not False for key in (
                "planner_executed", "trajectory_produced", "student_capture_authorized"))):
        raise ValueError("teacher inspection record identity invalid")
    commands = record["commands"]
    if type(commands) is not list or len(commands) != 6:
        raise ValueError("teacher inspection record commands invalid")
    expected = (
        ("image ID", ["docker", "image", "inspect", EGO_IMAGE_ID,
                      "--format", "{{.Id}}"], EGO_IMAGE_ID + "\n"),
        ("upstream commit", ["git", "-C", _SOURCE, "rev-parse", "HEAD"], EGO_COMMIT + "\n"),
        ("clean worktree", ["git", "-C", _SOURCE, "status", "--porcelain"], ""),
        ("upstream remote", ["git", "-C", _SOURCE, "config", "--local",
                             "--get-all", "remote.origin.url"], _UPSTREAM + "\n"),
        ("ROS executables", ["bash", "-lc",
                             "source /opt/ros/humble/setup.bash && source /ego_ws/install/setup.bash "
                             "&& ros2 pkg executables ego_planner"], None),
        ("binary hashes", ["sha256sum", *_BINARIES], None),
    )
    for index, (label, argv, stdout) in enumerate(expected):
        command = commands[index]
        if (type(command) is not dict
                or set(command) != {"label", "argv", "stdout", "stderr", "returncode"}
                or command["label"] != label or type(command["returncode"]) is not int
                or command["returncode"] != 0
                or command["stderr"] != "" or type(command["stdout"]) is not str):
            raise ValueError("teacher inspection record commands invalid")
        actual_argv = command["argv"]
        if index == 0:
            if actual_argv != argv:
                raise ValueError("teacher inspection record commands invalid")
        else:
            if type(actual_argv) is not list or len(actual_argv) < 15:
                raise ValueError("teacher inspection record commands invalid")
            name_position = actual_argv.index("--name") if "--name" in actual_argv else -1
            name = actual_argv[name_position + 1] if 0 <= name_position < len(actual_argv) - 1 else ""
            if re.fullmatch(r"flydrones-ego-inspect-[0-9a-f]{32}", name) is None:
                raise ValueError("teacher inspection record container name invalid")
            expected_argv = [
                "docker", "run", "--rm", "--pull=never", "--name", name,
                "--memory", "256m", "--cpus", "0.25", "--network", "none",
                "--read-only", "--pids-limit", "64", "--entrypoint", "/usr/bin/timeout",
                EGO_IMAGE_ID, "15s", *argv,
            ]
            if actual_argv != expected_argv:
                raise ValueError("teacher inspection record commands invalid")
        if stdout is not None and command["stdout"] != stdout:
            raise ValueError("teacher inspection record output invalid")
    listed = commands[4]["stdout"].splitlines()
    if len(listed) != len(_EXECUTABLES) or set(listed) != _EXECUTABLES:
        raise ValueError("teacher inspection record executables invalid")
    parsed = {}
    for line in commands[5]["stdout"].splitlines():
        match = _HASH_LINE.fullmatch(line)
        if match is None or match.group(2) in parsed:
            raise ValueError("teacher inspection record binary hashes invalid")
        parsed[match.group(2)] = match.group(1)
    if set(parsed) != set(_BINARIES) or record["executables"] != parsed:
        raise ValueError("teacher inspection record binary hashes invalid")
    return record
