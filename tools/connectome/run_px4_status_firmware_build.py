"""Read-only admission for one isolated PX4 EstimatorStatus firmware build.

This phase contains no build dispatch. A future runner must re-sample all facts
immediately before dispatch and audit the exact source again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import psutil

SCHEMA = "flydrones.px4_status_firmware_build_admission.v1"
SOURCE_PROFILE_SHA256 = "13fd3306e2cd19254cafba28f9dc21463173aa4b8dc43f9e0927b8cbb26a6b88"
SOURCE_AUDITOR_SHA256 = "badbab9a9eb877e6447bddd35c9624af86d9fb60b7a07798bc58d6c5b514ce94"
PREPARED_SOURCE_AUDIT_SHA256 = "ca2cb14a192bac354d457ce9e58b684f7b0421c70f096ebf3ed21be2f6b50251"
ISOLATED_ROOT = "/home/yuchen7509/px4-status-worktrees/firmware-v1"
BUILD_RESULT_PATH = "/home/yuchen7509/px4-status-worktrees/status-build-v1"
WSL_DISTRO = "Ubuntu"
COMMAND = ["make", "-j1", "px4_sitl_default"]
MIN_WINDOWS = 4 * 1024**3
MIN_WSL = 4 * 1024**3
MIN_DISK = 15 * 1024**3
SCOPE_MEMORY = 4 * 1024**3
SCOPE_CPU = "100000 100000"
TIMEOUT_SECONDS = 5400
_NO_AUTHORITY = {
    "build_dispatched": False,
    "firmware_compiled_verified": False,
    "live_source_authenticated": False,
    "fusion_qualified": False,
    "training_eligible": False,
}
ROOT = Path(__file__).resolve().parents[2]
SOURCE_PROFILE = ROOT / "configs/px4/estimator-status-firmware-profile.json"
SOURCE_AUDITOR = ROOT / "src/flydrones/connectome_training/px4_status_firmware.py"
PREPARED_SOURCE_AUDIT = ROOT / "results/px4-status-firmware-source-dev-1701/candidate-audit-v2.json"
WSL_REPO = "/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility"


def _integer_at_least(value: object, limit: int) -> bool:
    return type(value) is int and value >= limit


def audit_build_admission(profile: Mapping, facts: Mapping) -> dict:
    """Decide only whether a future build may be dispatched now."""
    errors: list[str] = []
    result = {"schema": "flydrones.px4_status_firmware_build_audit.v1",
              "build_admitted": False, "errors": errors, **_NO_AUTHORITY}
    if (not isinstance(profile, Mapping) or profile.get("schema") != SCHEMA
            or not isinstance(facts, Mapping)):
        errors.append("profile_or_facts_invalid")
        return result
    frozen = {
        "source_profile_sha256": SOURCE_PROFILE_SHA256,
        "source_auditor_sha256": SOURCE_AUDITOR_SHA256,
        "prepared_source_audit_sha256": PREPARED_SOURCE_AUDIT_SHA256,
        "isolated_root": ISOLATED_ROOT,
        "build_result_path": BUILD_RESULT_PATH,
        "wsl_distro": WSL_DISTRO,
        "command": COMMAND,
        "minimum_windows_available_bytes": MIN_WINDOWS,
        "minimum_wsl_available_bytes": MIN_WSL,
        "minimum_disk_free_bytes": MIN_DISK,
        "scope_memory_max_bytes": SCOPE_MEMORY,
        "scope_cpu_max": SCOPE_CPU,
        "timeout_seconds": TIMEOUT_SECONDS,
        "run_count_limit": 1,
    }
    if any(profile.get(key) != value for key, value in frozen.items()):
        errors.append("profile_contract_mismatch")
    if facts.get("source_profile_sha256") != profile.get("source_profile_sha256"):
        errors.append("source_profile_mismatch")
    if facts.get("source_auditor_sha256") != profile.get("source_auditor_sha256"):
        errors.append("source_auditor_mismatch")
    if facts.get("prepared_source_audit_sha256") != profile.get("prepared_source_audit_sha256"):
        errors.append("source_audit_mismatch")
    if facts.get("source_prepared") is not True:
        errors.append("source_not_prepared")
    if facts.get("result_path") != profile.get("build_result_path"):
        errors.append("result_path_mismatch")
    if facts.get("result_path_exists") is not False:
        errors.append("result_path_reused")
    if facts.get("command") != COMMAND:
        errors.append("build_command_mismatch")
    for key, limit, error in (
        ("windows_available_bytes", MIN_WINDOWS, "windows_memory_low"),
        ("wsl_available_bytes", MIN_WSL, "wsl_memory_low"),
        ("disk_free_bytes", MIN_DISK, "disk_low"),
    ):
        if not _integer_at_least(facts.get(key), limit):
            errors.append(error)
    if facts.get("process_scan_complete") is not True:
        errors.append("process_scan_incomplete")
    if not isinstance(facts.get("competitors"), list) or facts["competitors"]:
        errors.append("competitor_present")
    if facts.get("scope_observed_inside") is not True:
        errors.append("scope_unverified")
    if facts.get("scope_memory_max_bytes") != SCOPE_MEMORY:
        errors.append("scope_memory_mismatch")
    if facts.get("scope_cpu_max") != SCOPE_CPU:
        errors.append("scope_cpu_mismatch")
    if facts.get("timeout_seconds") != TIMEOUT_SECONDS:
        errors.append("timeout_mismatch")
    if facts.get("run_count") != 0:
        errors.append("run_count_exhausted")
    result["build_admitted"] = not errors
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wsl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl.exe", "--distribution", WSL_DISTRO, "--exec", *args],
        capture_output=True, text=True, check=check, timeout=30,
    )


def _is_competitor(name: str, command: str) -> bool:
    name = name.lower().removesuffix(".exe")
    command = command.lower()
    return bool(
        name in {"px4", "gz", "gzserver", "gazebo", "gz-sim-server", "ninja", "cmake"}
        or "openvins" in name
        or name.startswith("python") and any(
            word in command for word in ("pytest", "train", "openvins")
        )
        or "gz sim" in command
        or "docker build" in command
    )


def _command_sensitive_name(name: str) -> bool:
    name = name.lower().removesuffix(".exe")
    return bool(
        name.startswith("python")
        or name in {"px4", "gz", "gzserver", "gazebo", "gz-sim-server",
                    "ninja", "cmake", "make", "pytest", "cmd", "pwsh",
                    "powershell", "bash", "sh", "docker", "wsl", "node"}
        or "openvins" in name
    )


def _windows_process_name(pid: int) -> str:
    observed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-Process -Id {pid} -ErrorAction Stop).ProcessName"],
        capture_output=True, text=True, check=True, timeout=5,
    ).stdout.strip()
    if not observed or "\n" in observed or "\r" in observed:
        raise ValueError("process name fallback malformed")
    return observed


def _process_facts() -> tuple[list[dict], bool]:
    competitors: list[dict] = []
    complete = True
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        if process.pid == os.getpid():
            continue
        try:
            name = process.info["name"]
            argv = process.info["cmdline"]
            if not isinstance(name, str) or not name:
                try:
                    name = _windows_process_name(process.pid)
                except (OSError, ValueError, subprocess.SubprocessError):
                    complete = False
                    continue
            if not isinstance(argv, (list, tuple)) or not argv:
                if _command_sensitive_name(name):
                    complete = False
                continue
            command = " ".join(argv)
            if _is_competitor(name, command):
                competitors.append({"surface": "windows", "pid": process.pid,
                                    "name": name, "command": command[:300]})
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, TypeError):
            complete = False
    try:
        observed = _wsl("ps", "-eo", "pid=,comm=,args=").stdout
        for line in observed.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) < 3 or not parts[0].isdigit():
                complete = False
                continue
            pid, name, command = parts
            if _is_competitor(name, command):
                competitors.append({"surface": "wsl", "pid": int(pid),
                                    "name": name, "command": command[:300]})
    except (OSError, subprocess.SubprocessError, UnicodeError):
        complete = False
    return competitors, complete


def _scope_facts() -> tuple[bool, int | None, str | None]:
    script = (
        "import json,pathlib;"
        "g=pathlib.Path('/proc/self/cgroup').read_text().strip().split(':')[-1];"
        "p=pathlib.Path('/sys/fs/cgroup')/g.lstrip('/');"
        "print(json.dumps({'group':g,'memory':(p/'memory.max').read_text().strip(),"
        "'cpu':(p/'cpu.max').read_text().strip()}))"
    )
    try:
        output = _wsl(
            "systemd-run", "--user", "--scope", "-p", "MemoryMax=4G",
            "-p", "CPUQuota=100%", "python3", "-c", script,
        ).stdout
        rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        if len(rows) != 1:
            return False, None, None
        row = rows[0]
        memory = int(row["memory"])
        cpu = row["cpu"]
        return bool("run-" in row["group"]), memory, cpu
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return False, None, None


def collect_admission_facts(profile: Mapping) -> dict:
    """Sample current resources and source without creating build output."""
    source_profile_hash = _sha256(SOURCE_PROFILE)
    source_auditor_hash = _sha256(SOURCE_AUDITOR)
    prepared_audit_hash = _sha256(PREPARED_SOURCE_AUDIT)
    source_command = (
        "python3", f"{WSL_REPO}/src/flydrones/connectome_training/px4_status_firmware.py",
        "--profile", f"{WSL_REPO}/configs/px4/estimator-status-firmware-profile.json",
        "--root", ISOLATED_ROOT,
        "--candidate", f"{WSL_REPO}/configs/px4/estimator-status-dds-candidate.yaml",
        "--result-path", BUILD_RESULT_PATH, "--stage", "candidate",
    )
    source_run = _wsl(*source_command, check=False)
    source_observation = json.loads(source_run.stdout)
    source_prepared = (
        source_run.returncode == 0
        and source_observation.get("audit", {}).get("source_prepared") is True
    )
    meminfo = _wsl("cat", "/proc/meminfo").stdout
    available_kib = next(
        int(line.split()[1]) for line in meminfo.splitlines()
        if line.startswith("MemAvailable:")
    )
    df = _wsl("df", "-B1", "--output=avail", ISOLATED_ROOT).stdout.splitlines()
    disk_available = int(df[-1].strip())
    exists = _wsl("test", "-e", BUILD_RESULT_PATH, check=False)
    link = _wsl("test", "-L", BUILD_RESULT_PATH, check=False)
    if exists.returncode not in (0, 1) or link.returncode not in (0, 1):
        raise RuntimeError("result path existence is unknown")
    result_exists = exists.returncode == 0 or link.returncode == 0
    competitors, scan_complete = _process_facts()
    windows_available = int(psutil.virtual_memory().available)
    eligible_for_scope = (
        windows_available >= MIN_WINDOWS and available_kib * 1024 >= MIN_WSL
        and disk_available >= MIN_DISK and scan_complete and not competitors
        and source_prepared and not result_exists
    )
    scope_verified, scope_memory, scope_cpu = (
        _scope_facts() if eligible_for_scope else (False, None, None)
    )
    return {
        "source_profile_sha256": source_profile_hash,
        "source_auditor_sha256": source_auditor_hash,
        "prepared_source_audit_sha256": prepared_audit_hash,
        "source_prepared": source_prepared,
        "source_observation": source_observation,
        "result_path": BUILD_RESULT_PATH,
        "result_path_exists": result_exists,
        "command": COMMAND,
        "windows_available_bytes": windows_available,
        "wsl_available_bytes": available_kib * 1024,
        "disk_free_bytes": disk_available,
        "competitors": competitors,
        "process_scan_complete": scan_complete,
        "scope_observed_inside": scope_verified,
        "scope_memory_max_bytes": scope_memory,
        "scope_cpu_max": scope_cpu,
        "timeout_seconds": TIMEOUT_SECONDS,
        "run_count": 1 if result_exists else 0,
        "scope_probe_skipped_due_to_other_gate": not eligible_for_scope,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only PX4 firmware build admission")
    parser.add_argument("--admission-only", action="store_true", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        facts = collect_admission_facts(profile)
        audit = audit_build_admission(profile, facts)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        facts = None
        audit = {"build_admitted": False, "errors": [f"collection_error:{type(exc).__name__}:{exc}"],
                 **_NO_AUTHORITY}
    print(json.dumps({"facts": facts, "audit": audit}, indent=2, sort_keys=True))
    return 0 if audit["build_admitted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
