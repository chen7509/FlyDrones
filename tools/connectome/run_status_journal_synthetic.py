"""One bounded synthetic ROS status callback and journal-I/O fault study.

The fixed inputs are copied from Git blobs. This never starts PX4 or Gazebo.
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
sys.path.insert(0, str(ROOT))
from flydrones.connectome_training.px4_status_journal_source import verify_source  # noqa: E402
from flydrones.connectome_training.px4_status_source_journal import (  # noqa: E402
    audit_status_source_journal,
)
from tools.connectome.run_status_ros_type_build import (  # noqa: E402
    _INACCESSIBLE,
    _command_sensitive_name,
    _is_competitor,
    _windows_process_name,
    _wsl_competitors,
)

BUILD = ROOT / "results/px4-status-journal-build-dev-1701-v2"
WORKSPACE = BUILD / "workspace-v1"
PRIOR = ROOT / "results/px4-status-journal-synthetic-dev-1701"
RESULT = ROOT / "results/px4-status-journal-synthetic-dev-1701-v2"
IMAGE_ID = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
CONTAINER = "flydrones-px4-status-journal-synthetic-v2"
HARNESS_COMMIT = "8becb9e71cab5a7da5a1ad98cdfed8661b43b0bc"
HARNESS = {
    "status_synthetic_pub.py": "fc9f33c3119a217d019906ef364ed6b78717ace141d7e07e368243fcd0c2ad22",
    "status_synthetic_cdr_check.py": "e62b73b179ca665a9afad34ffe6290e3e05a00edd49ea36465029e244d364698",
    "status_journal_fault.c": "a446e8bb7268c587263d411813f6fe05f2ed6291f9e75a10d5eb83bb33ad210e",
    "status_journal_synthetic_run.sh": "45eaa7dfa724f38428bcc6d199f019d974345ae6697bad4aca4ca0a3948ab755",
}
BINARY = ("install/flydrones_px4_status_ros2_source/lib/"
          "flydrones_px4_status_ros2_source/px4_estimator_status_source")
MIN_FREE_KIB = 900_000
SOURCE_PROFILE_SHA256 = "9b09019edaba29bee1364e67f3d2f7d31820936a1a12e6b7bc470b19c5cc3572"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(name: str, value: dict) -> None:
    with (RESULT / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          check=True, timeout=15).stdout.strip()


def _stage_harness() -> None:
    target = RESULT / "tools"
    target.mkdir()
    for name, expected in HARNESS.items():
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "blob",
             f"{HARNESS_COMMIT}:tools/connectome/{name}"],
            capture_output=True, check=True, timeout=15,
        ).stdout
        if _sha(blob) != expected:
            raise ValueError(f"fixed harness Git blob changed: {name}")
        (target / name).write_bytes(blob)


def _host_competitors() -> tuple[list[dict], list[dict]]:
    competitors = []
    errors = []
    for process in psutil.process_iter(
            ["pid", "name", "cmdline"], ad_value=_INACCESSIBLE):
        if process.pid == os.getpid():
            continue
        try:
            raw_name = process.info["name"]
            if raw_name is _INACCESSIBLE or not raw_name:
                try:
                    raw_name = _windows_process_name(process.pid)
                except Exception as exc:
                    errors.append({"pid": process.pid,
                                   "reason": "inaccessible_process_name",
                                   "fallback_error": repr(exc)})
                    continue
            name = raw_name.lower()
            argv = process.info["cmdline"]
            if argv is _INACCESSIBLE or not argv:
                if _command_sensitive_name(name):
                    errors.append({"pid": process.pid, "name": name,
                                   "reason": "inaccessible_launcher_command"})
                continue
            command = " ".join(argv).lower()
            if _is_competitor(name, command):
                competitors.append({"pid": process.pid, "name": name})
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, TypeError) as exc:
            errors.append({"pid": process.pid, "error": repr(exc)})
    return competitors, errors


def _preflight() -> dict:
    build = json.loads((BUILD / "result.json").read_text(encoding="utf-8"))
    source = verify_source(WORKSPACE, allow_build_output=True)
    binary = WORKSPACE / BINARY
    message = WORKSPACE / "install/px4_msgs/share/px4_msgs/msg/EstimatorStatus.msg"
    competitors, errors = _host_competitors()
    record = {
        "free_kib": psutil.virtual_memory().available // 1024,
        "minimum_free_kib": MIN_FREE_KIB,
        "image_id": _docker("image", "inspect", IMAGE_ID, "--format", "{{.Id}}"),
        "daemon_id": _docker("info", "--format", "{{.ID}}"),
        "running_containers": _docker("ps", "--format", "{{.ID}}").splitlines(),
        "owned_container": _docker("ps", "-a", "--filter", f"name=^{CONTAINER}$",
                                   "--format", "{{.ID}}"),
        "competing_processes": competitors,
        "wsl_competing_processes": _wsl_competitors(),
        "process_errors": errors,
        "build_status": build.get("status"),
        "source": source,
        "binary_sha256": _sha(binary.read_bytes()) if binary.is_file() else None,
        "message_sha256": _sha(message.read_bytes()) if message.is_file() else None,
        "harness_sha256": {name: _sha((RESULT / "tools" / name).read_bytes())
                           for name in HARNESS},
    }
    _write("preflight.json", record)
    if (record["free_kib"] < MIN_FREE_KIB or record["image_id"] != IMAGE_ID
            or not record["daemon_id"] or record["running_containers"]
            or record["owned_container"] or competitors or errors
            or record["wsl_competing_processes"]
            or build.get("status") != "compiled_offline_status_collector"
            or build.get("compiled_collector") is not True
            or source.get("profile_sha256") != SOURCE_PROFILE_SHA256
            or record["binary_sha256"] != build.get("collector_binary_sha256")
            or record["message_sha256"] != build.get("installed_status_sha256")
            or record["harness_sha256"] != HARNESS):
        raise RuntimeError("status synthetic preflight refused")
    return record


def _audit_case(mode: str) -> dict:
    directory = RESULT / mode
    writer_exit = int((directory / "subscriber.exit").read_text(encoding="ascii").strip())
    publisher_exit = int((directory / "publisher.exit").read_text(encoding="ascii").strip())
    journal = directory / "source.jsonl"
    output = {"writer_exit": writer_exit, "publisher_exit": publisher_exit,
              "journal_sha256": _sha(journal.read_bytes()) if journal.is_file() else None}
    if mode != "normal":
        expected = {
            "fsync_eio": "flydrones injected fsync EIO",
            "close_eio": "flydrones injected close EIO",
            "partial_then_eio": "flydrones injected write EIO",
        }[mode]
        output["injection_marker"] = expected in (
            directory / "subscriber.log").read_text(encoding="utf-8", errors="replace")
    try:
        audit = audit_status_source_journal(journal, observed_writer_exit_code=writer_exit)
        output.update({"audit_completed": audit.completed,
                       "terminal_claimed_complete": audit.terminal_claimed_complete,
                       "samples": audit.samples, "training_eligible": audit.training_eligible})
    except Exception as exc:
        output["audit_error"] = repr(exc)
    return output


def _qualifies(result: dict, preflight: dict) -> bool:
    cases = result.get("cases", {})
    if set(cases) != {"normal", "fsync_eio", "close_eio", "partial_then_eio"}:
        return False
    normal = cases["normal"]
    expected_fault_exits = {"fsync_eio": 2, "close_eio": 2, "partial_then_eio": 1}
    return bool(
        result.get("docker_exit") == 0 and result.get("timed_out") is False
        and result.get("launch_error") is None
        and result.get("daemon_id_after") == preflight["daemon_id"]
        and result.get("owned_container_remaining") == ""
        and result.get("source_after") == preflight["source"]
        and result.get("harness_after") == HARNESS
        and normal.get("writer_exit") == 0 and normal.get("publisher_exit") == 0
        and normal.get("audit_completed") is True and normal.get("samples") == 3
        and result.get("cdr_parity") == {
            "independent_cdr_parity": True, "samples": 3,
            "unavailable_ratios": ["vel_test_ratio"],
        }
        and all(case.get("writer_exit") == expected_exit
                and case.get("publisher_exit") == 0
                and case.get("injection_marker") is True
                and case.get("audit_completed") is not True
                for name, expected_exit in expected_fault_exits.items()
                for case in (cases[name],))
        and all(cases[name].get("terminal_claimed_complete") is True
                and cases[name].get("audit_completed") is False
                for name in ("fsync_eio", "close_eio"))
        and isinstance(cases["partial_then_eio"].get("audit_error"), str)
        and bool(cases["partial_then_eio"]["audit_error"])
        and all(case.get("training_eligible") is not True for case in cases.values())
    )


def _prior_preflight_refusal() -> bool:
    """V2 is allowed only after V1 refused before Docker launch."""
    if not PRIOR.is_dir() or {p.name for p in PRIOR.iterdir()} != {
        "run-profile.json", "tools", "preflight.json", "result.json",
    }:
        raise ValueError("prior synthetic attempt was not prelaunch-only")
    prior = json.loads((PRIOR / "result.json").read_text(encoding="utf-8"))
    preflight = json.loads((PRIOR / "preflight.json").read_text(encoding="utf-8"))
    if (prior != {"status": "preflight_failed", "started": False,
                  "error": "RuntimeError('status synthetic preflight refused')"}
            or not isinstance(preflight.get("competing_processes"), list)
            or not preflight["competing_processes"]):
        raise ValueError("prior refusal was not a recorded competitor")
    return True


def main() -> int:
    if RESULT.exists():
        raise FileExistsError("one-shot status synthetic result already exists")
    _prior_preflight_refusal()
    RESULT.mkdir()
    _write("run-profile.json", {
        "schema": "flydrones.px4_status_journal_synthetic.v2",
        "prior_prelaunch_refusal": str(PRIOR),
        "build_result": str(BUILD), "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "image_id": IMAGE_ID, "harness_commit": HARNESS_COMMIT,
        "harness_sha256": HARNESS, "cpus": 1, "memory_mib": 512,
        "network": "none", "timeout_seconds": 180, "run_count_limit": 1,
        "live_source_authenticated": False, "training_eligible": False,
    })
    try:
        _stage_harness()
        preflight = _preflight()
    except Exception as exc:
        _write("result.json", {"status": "preflight_failed", "started": False,
                               "error": repr(exc)})
        raise
    command = [
        "docker", "run", "--rm", "--name", CONTAINER, "--cpus", "1",
        "--memory", "512m", "--memory-swap", "512m", "--pids-limit", "64",
        "--network", "none",
        "--mount", f"type=bind,source={WORKSPACE},target=/workspace,readonly",
        "--mount", f"type=bind,source={RESULT},target=/case",
        "--mount", f"type=bind,source={RESULT / 'tools'},target=/tools,readonly",
        IMAGE_ID, "bash", "/tools/status_journal_synthetic_run.sh",
    ]
    _write("launch.json", {"arguments": command, "started_unix_ns": time.time_ns()})
    started = time.monotonic()
    with (RESULT / "container.log").open("xb") as output:
        try:
            run = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                 timeout=180, check=False)
            exit_code, launch_error, timed_out = run.returncode, None, False
        except subprocess.TimeoutExpired as exc:
            exit_code, launch_error, timed_out = None, repr(exc), True
        except Exception as exc:
            exit_code, launch_error, timed_out = None, repr(exc), False
    result = {"status": "synthetic_failed", "started": True,
              "docker_exit": exit_code, "timed_out": timed_out,
              "launch_error": launch_error, "elapsed_seconds": time.monotonic() - started}
    try:
        if timed_out and _docker("info", "--format", "{{.ID}}") == preflight["daemon_id"]:
            cleanup = subprocess.run(["docker", "rm", "-f", CONTAINER],
                                     capture_output=True, text=True, timeout=30)
            result["timeout_cleanup"] = {"exit": cleanup.returncode,
                                         "stdout": cleanup.stdout, "stderr": cleanup.stderr}
        result["daemon_id_after"] = _docker("info", "--format", "{{.ID}}")
        result["owned_container_remaining"] = _docker(
            "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}")
        result["source_after"] = verify_source(WORKSPACE, allow_build_output=True)
        result["harness_after"] = {
            name: _sha((RESULT / "tools" / name).read_bytes()) for name in HARNESS}
        result["cases"] = {mode: _audit_case(mode) for mode in (
            "normal", "fsync_eio", "close_eio", "partial_then_eio")}
        parity = json.loads((RESULT / "normal/cdr-parity.json").read_text(encoding="utf-8"))
        result["cdr_parity"] = parity
        qualified = _qualifies(result, preflight)
        result["qualified"] = qualified
        if qualified:
            result["status"] = "synthetic_callback_and_faults_verified"
    except Exception as exc:
        result["audit_error"] = repr(exc)
        result["qualified"] = False
    _write("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
