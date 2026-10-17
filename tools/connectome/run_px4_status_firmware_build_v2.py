"""Fail-closed admission and one bounded isolated PX4 status firmware build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
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
BUILD_SCOPE_UNIT = "flydrones-px4-status-build-v1-" + secrets.token_hex(12) + ".scope"
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
BUILD_EVIDENCE_DIR = ROOT / "results/px4-status-firmware-build-dev-1701-v2"
LEGACY_BUILD_EVIDENCE_DIR = ROOT / "results/px4-status-firmware-build-dev-1701-v1"
EXPECTED_TOOLCHAIN_FILES = {
    "/usr/bin/env": "886e5fa8be716b03eeda48856e0f04493f2969fc148fb7812594ffac647fa050",
    "/usr/bin/timeout": "12690a043dfd555a6c14ccc1564f5649c18f1762c0d6ff66729948130898ec52",
    "/usr/bin/systemd-run": "dbc8b988a849d5c9d7ef2de7068a6f107021bc6c11e0d7864c73f373eef726a7",
    "/usr/bin/git": "2a8c18fbf43da9f692d75474c72bea9dfd796c260b0f3dfe456376abc3bbd668",
    "/usr/bin/gcc": "1b99826121ae6682a634e5efe09bd3e3df58ce58e0b28f849114ab5b89139c26",
    "/usr/bin/g++": "1353e9bdd29a7295c7226bf6c63abccce056d8cac31f112e5cdbecc3f28c2769",
    "/usr/bin/cmake": "1c5227af4edd22d8d689def545e18ee458260c0fd579eba2187967f38817e638",
    "/usr/bin/ninja": "5965527e09fe2b3787772aa4f711d6a36b393e7f2fcaa744a7a96c5a4ddf59cb",
    "/usr/bin/make": "d78b8f1d099fbcfb6f2f49ab87223b9b68fb3956642f92d6ec6de812e8afa965",
    "/usr/bin/python3": "e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f",
}
EXPECTED_TOOLCHAIN_MODULES = {
    "em": {
        "version": "3.3.4",
        "origin": "/usr/local/lib/python3.12/dist-packages/em.py",
        "sha256": "0d03eb2b54a207061dcf3bb892b2b734d20008d91564637158fb784d0b7e6513",
    },
    "yaml": {
        "version": "6.0.1",
        "origin": "/usr/lib/python3/dist-packages/yaml/__init__.py",
        "sha256": "6e1974e6a49e3bed59c654918c6aef9769bd9eb5dbd67f7e1906ad4cdd0caea7",
    },
}
SOURCE_PROFILE = ROOT / "configs/px4/estimator-status-firmware-profile.json"
SOURCE_AUDITOR = ROOT / "src/flydrones/connectome_training/px4_status_firmware.py"
PREPARED_SOURCE_AUDIT = ROOT / "results/px4-status-firmware-source-dev-1701/candidate-audit-v2.json"
WSL_REPO = "/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility"
SCOPE_ENTRY = ROOT / "tools/connectome/px4_firmware_scope_entry_v2.py"
SCOPE_ENTRY_WSL = WSL_REPO + "/tools/connectome/px4_firmware_scope_entry_v2.py"
SCOPE_ENTRY_SHA256 = "4517fa60e7d37584754bbfb8f4179b8039a378d39e4b96c9a2e60d9ef6c50042"


def _pin_entry() -> dict:
    observed = _sha256(SCOPE_ENTRY)
    if observed != SCOPE_ENTRY_SHA256:
        raise ValueError("reviewed compiler entry bytes changed")
    return {"path": str(SCOPE_ENTRY), "wsl_path": SCOPE_ENTRY_WSL, "sha256": observed}


def _require_unused_build_evidence() -> None:
    for path in (LEGACY_BUILD_EVIDENCE_DIR, BUILD_EVIDENCE_DIR):
        if path.exists() or path.is_symlink():
            raise FileExistsError("original one-shot firmware evidence already consumed")


def _integer_at_least(value: object, limit: int) -> bool:
    return type(value) is int and value >= limit


def audit_build_admission(profile: Mapping, facts: Mapping) -> dict:
    """Decide only whether a future build may be dispatched now."""
    errors: list[str] = []
    result = {
        "schema": "flydrones.px4_status_firmware_build_audit.v1",
        "build_admitted": False,
        "errors": errors,
        **_NO_AUTHORITY,
    }
    if not isinstance(profile, Mapping) or profile.get("schema") != SCHEMA or not isinstance(facts, Mapping):
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


def audit_owned_scope_cleanup(
    observation: Mapping,
    *,
    expected_unit: str = BUILD_SCOPE_UNIT,
) -> dict:
    """Verify only the named scope release; escaped descendants remain unknown."""
    errors: list[str] = []
    result = {
        "schema": "flydrones.px4_status_owned_scope_cleanup.v1",
        "owned_scope_released": False,
        "graceful_scope_exit": False,
        "all_descendants_proven_exited": False,
        "errors": errors,
    }
    if not isinstance(observation, Mapping):
        errors.append("observation_invalid")
        return result
    if expected_unit != BUILD_SCOPE_UNIT and expected_unit not in {
        "flydrones-px4-status-lifecycle-v2.scope",
        "flydrones-px4-status-timeout-probe-v1.scope",
    }:
        errors.append("expected_unit_unsupported")
    if observation.get("unit") != expected_unit:
        errors.append("unit_mismatch")
    during = observation.get("during")
    expected_group_suffix = "/" + expected_unit
    if (
        not isinstance(during, Mapping)
        or during.get("load_state") != "loaded"
        or during.get("active_state") != "active"
        or not isinstance(during.get("control_group"), str)
        or not during["control_group"].startswith("/user.slice/")
        or not during["control_group"].endswith(expected_group_suffix)
    ):
        errors.append("during_scope_unverified")
    members = observation.get("cgroup_members_during")
    if (
        observation.get("cgroup_read_exit") != 0
        or not isinstance(members, list)
        or not members
        or any(not isinstance(pid, str) or not pid.isdecimal() or int(pid) <= 0 for pid in members)
    ):
        errors.append("during_members_missing")
    post = observation.get("post")
    post_normal = (
        isinstance(post, Mapping)
        and post.get("load_state") == "not-found"
        and post.get("active_state") == "inactive"
        and post.get("control_group") == ""
    )
    post_after_stop = (
        isinstance(post, Mapping)
        and post.get("load_state") == "loaded"
        and post.get("active_state") == "failed"
        and post.get("control_group") == ""
        and (observation.get("stop_exit") == 0 or observation.get("kill_exit") == 0)
    )
    if not post_normal and not post_after_stop:
        errors.append("unit_post_active_or_unknown")
    if observation.get("cgroup_exists_after") is not False:
        errors.append("cgroup_still_exists")
    if observation.get("cgroup_after_test_exit") != 1:
        errors.append("cgroup_post_unknown")
    if observation.get("launcher_alive_after") is not False:
        errors.append("launcher_still_alive")
    result["owned_scope_released"] = not errors
    result["graceful_scope_exit"] = (
        not errors and post_normal and "stop_exit" not in observation and "kill_exit" not in observation
    )
    return result


def audit_toolchain_snapshot(observation: Mapping) -> dict:
    """Pin selected compiler/build tools and Python generator entrypoints."""
    errors: list[str] = []
    if not isinstance(observation, Mapping):
        errors.append("toolchain_observation_invalid")
    else:
        if observation.get("files") != EXPECTED_TOOLCHAIN_FILES:
            errors.append("toolchain_files_mismatch")
        if observation.get("modules") != EXPECTED_TOOLCHAIN_MODULES:
            errors.append("toolchain_modules_mismatch")
    return {"schema": "flydrones.px4_status_toolchain_snapshot.v1", "toolchain_verified": not errors, "errors": errors}


def audit_build_tree(status: str, build_exists: bool, build_symlink: bool) -> dict:
    """Allow only the deliberate tracked DDS candidate; reject prior output."""
    errors: list[str] = []
    if status != " M src/modules/uxrce_dds_client/dds_topics.yaml\n":
        errors.append("unexpected_tracked_untracked_or_ignored_source")
    if build_exists or build_symlink:
        errors.append("build_tree_reused")
    return {"schema": "flydrones.px4_status_build_tree_audit.v1", "build_tree_verified": not errors, "errors": errors}


def _build_tree_snapshot() -> dict:
    status = _wsl(
        "/usr/bin/git", "-C", ISOLATED_ROOT, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"
    ).stdout
    path = ISOLATED_ROOT + "/build"
    exists = _wsl("test", "-e", path, check=False)
    link = _wsl("test", "-L", path, check=False)
    if exists.returncode not in (0, 1) or link.returncode not in (0, 1):
        raise RuntimeError("build tree existence unknown")
    return {"status": status, "build_exists": exists.returncode == 0, "build_symlink": link.returncode == 0}


def _toolchain_snapshot() -> dict:
    """Sample installed WSL files in one read-only Python subprocess."""
    script = (
        "import hashlib,importlib.metadata as m,importlib.util,json,pathlib;"
        "paths=" + repr(tuple(EXPECTED_TOOLCHAIN_FILES)) + ";"
        "names={'em':'empy','yaml':'PyYAML'};"
        "files={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths};"
        "mods={n:{'version':m.version(dist),'origin':(s:=importlib.util.find_spec(n)).origin,"
        "'sha256':hashlib.sha256(pathlib.Path(s.origin).read_bytes()).hexdigest()}"
        " for n,dist in names.items()};"
        "print(json.dumps({'files':files,'modules':mods},sort_keys=True))"
    )
    observed = json.loads(_wsl("/usr/bin/python3", "-c", script).stdout)
    if not isinstance(observed, dict):
        raise ValueError("toolchain observation malformed")
    return observed


def build_scope_command() -> list[str]:
    """Return only the frozen, cgroup-limited build command; do not run it."""
    return [
        "wsl.exe",
        "--distribution",
        WSL_DISTRO,
        "--exec",
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--unit=" + BUILD_SCOPE_UNIT.removesuffix(".scope"),
        "--property=MemoryMax=4G",
        "--property=MemorySwapMax=0",
        "--property=CPUQuota=100%",
        "--property=TasksMax=256",
        "--property=TimeoutStopSec=10s",
        f"--working-directory={ISOLATED_ROOT}",
        "/usr/bin/env",
        "-i",
        "HOME=/home/yuchen7509",
        "USER=yuchen7509",
        "PATH=/usr/bin:/bin",
        "GIT_CONFIG_COUNT=1",
        "GIT_CONFIG_KEY_0=protocol.allow",
        "GIT_CONFIG_VALUE_0=never",
        "GIT_TERMINAL_PROMPT=0",
        "CCACHE_DISABLE=1",
        "MAKEFLAGS=-j1",
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=10s",
        "5400s",
        "/usr/bin/python3",
        "-I",
        "-S",
        "-B",
        SCOPE_ENTRY_WSL,
        "--unit",
        BUILD_SCOPE_UNIT,
    ]


def audit_two_phase_dispatch(profile: Mapping, first: Mapping, second: Mapping) -> dict:
    """Require a second fresh source/resource gate immediately before launch."""
    first_audit = audit_build_admission(profile, first)
    second_audit = audit_build_admission(profile, second)
    errors: list[str] = []
    if not first_audit["build_admitted"]:
        errors.append("first_admission_refused")
    if not second_audit["build_admitted"]:
        errors.append("second_admission_refused")
    first_source = first.get("source_observation") if isinstance(first, Mapping) else None
    second_source = second.get("source_observation") if isinstance(second, Mapping) else None
    if (
        not isinstance(first_source, Mapping)
        or not isinstance(first_source.get("facts"), Mapping)
        or not isinstance(second_source, Mapping)
        or not isinstance(second_source.get("facts"), Mapping)
        or first_source["facts"] != second_source["facts"]
    ):
        errors.append("source_changed_between_admissions")
    return {
        "schema": "flydrones.px4_status_two_phase_dispatch.v1",
        "dispatch_permitted": not errors,
        "build_dispatched": False,
        "first_admission": first_audit,
        "second_admission": second_audit,
        "errors": errors,
        "firmware_compiled_verified": False,
        "live_source_authenticated": False,
        "training_eligible": False,
    }


def execute_once(
    profile: Mapping,
    *,
    collect=None,
    dispatch=None,
) -> dict:
    """Sample twice and call the one-shot dispatcher only after both pass."""
    _require_unused_build_evidence()
    _pin_entry()
    collect = collect or collect_admission_facts
    dispatch = dispatch or _dispatch_approved
    first = collect(profile)
    first_audit = audit_build_admission(profile, first)
    if not first_audit["build_admitted"]:
        return {
            "schema": "flydrones.px4_status_build_execution.v1",
            "first": first,
            "first_audit": first_audit,
            "second": None,
            "dispatch_permitted": False,
            "build_dispatched": False,
            **_NO_AUTHORITY,
        }
    second = collect(profile)
    decision = audit_two_phase_dispatch(profile, first, second)
    if not decision["dispatch_permitted"]:
        return {
            "schema": "flydrones.px4_status_build_execution.v1",
            "first": first,
            "second": second,
            "decision": decision,
            "dispatch_permitted": False,
            **_NO_AUTHORITY,
        }
    result = dict(dispatch(profile, first, second))
    result["schema"] = "flydrones.px4_status_build_execution.v1"
    result["dispatch_permitted"] = True
    result["firmware_compiled_verified"] = False
    result["live_source_authenticated"] = False
    result["fusion_qualified"] = False
    result["training_eligible"] = False
    return result


def _show_build_unit(*, deadline: float | None = None) -> dict[str, str]:
    observed = _wsl(
        "systemctl",
        "--user",
        "show",
        BUILD_SCOPE_UNIT,
        "--property=LoadState,ActiveState,ControlGroup,Result,InvocationID",
        deadline=deadline,
    ).stdout
    items = {}
    for line in observed.splitlines():
        if "=" not in line:
            raise ValueError("malformed systemd unit state")
        key, value = line.split("=", 1)
        if key in items:
            raise ValueError("duplicate systemd unit field")
        items[key] = value
    if not {"LoadState", "ActiveState", "ControlGroup"} <= set(items):
        raise ValueError("missing systemd unit state")
    return {
        "load_state": items["LoadState"],
        "active_state": items["ActiveState"],
        "control_group": items["ControlGroup"],
        "result": items.get("Result", ""),
        "invocation_id": items.get("InvocationID", ""),
    }


def _read_cgroup(group: str, *, deadline: float | None = None) -> dict:
    if not group.startswith("/user.slice/") or not group.endswith("/" + BUILD_SCOPE_UNIT):
        raise ValueError("unowned cgroup path")
    root = "/sys/fs/cgroup" + group
    members = _wsl("cat", root + "/cgroup.procs", deadline=deadline).stdout.splitlines()
    memory = _wsl("cat", root + "/memory.max", deadline=deadline).stdout.strip()
    cpu = _wsl("cat", root + "/cpu.max", deadline=deadline).stdout.strip()
    swap = _wsl("cat", root + "/memory.swap.max", deadline=deadline).stdout.strip()
    tasks = _wsl("cat", root + "/pids.max", deadline=deadline).stdout.strip()
    peak = _wsl("cat", root + "/memory.peak", deadline=deadline).stdout.strip()
    if not members or any(not pid.isdecimal() or int(pid) <= 0 for pid in members):
        raise ValueError("owned cgroup members missing")
    if memory != str(SCOPE_MEMORY) or cpu != SCOPE_CPU or not peak.isdecimal() or swap != "0" or tasks != "256":
        raise ValueError("runtime scope resource limit mismatch")
    return {
        "path": root,
        "members": members,
        "memory_max": int(memory),
        "cpu_max": cpu,
        "memory_peak_bytes": int(peak),
        "swap_max": int(swap),
        "tasks_max": int(tasks),
    }


def _write_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def _persist_final_result(path: Path, result: dict) -> None:
    """Return a visible failure record even if the evidence volume is full."""
    result["final_record_persisted"] = True
    try:
        _write_exclusive(path, result)
    except OSError as exc:
        result["final_record_persisted"] = False
        result["errors"].append(f"final_record_write_failed:{type(exc).__name__}:{exc}")


def classify_build_exit(exit_code: object) -> tuple[str | None, bool]:
    """Preserve timeout-like exit ambiguity; host deadline is separate evidence."""
    if type(exit_code) is not int:
        return "build_exit_unknown", False
    if exit_code == 0:
        return None, False
    if exit_code == 124:
        return "build_exit_124_possible_timeout", False
    if exit_code == 137:
        return "build_exit_137_possible_sigkill", False
    return f"build_exit_nonzero:{exit_code}", False


def _stop_owned_scope(expected_invocation_id: str | None = None) -> dict:
    """Stop only this nonce-named scope, rejecting a changed invocation."""
    outcome = {"stop_exit": None, "kill_exit": None, "errors": []}
    if expected_invocation_id is None:
        outcome["errors"].append("scope_invocation_not_bound")
        return outcome
    state = _show_build_unit()
    outcome["state_before_stop"] = state
    if state["active_state"] != "active":
        outcome["errors"].append("scope_not_active_at_stop")
        return outcome
    if (
        state["load_state"] != "loaded"
        or not state["control_group"].endswith("/" + BUILD_SCOPE_UNIT)
        or not state["control_group"].startswith("/user.slice/")
        or len(state["invocation_id"]) != 32
        or any(character not in "0123456789abcdef" for character in state["invocation_id"])
    ):
        outcome["errors"].append("scope_identity_malformed")
        return outcome
    if expected_invocation_id is not None and state["invocation_id"] != expected_invocation_id:
        outcome["errors"].append("scope_invocation_changed")
        return outcome
    try:
        outcome["stop_exit"] = _wsl(
            "systemctl",
            "--user",
            "stop",
            BUILD_SCOPE_UNIT,
            check=False,
        ).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        outcome["errors"].append(f"stop_error:{type(exc).__name__}:{exc}")
    try:
        after_stop = _show_build_unit()
        outcome["state_after_stop"] = after_stop
        if after_stop["active_state"] == "active":
            if (
                after_stop.get("invocation_id") != state["invocation_id"]
                or after_stop.get("control_group") != state["control_group"]
            ):
                outcome["errors"].append("scope_replaced_before_kill")
                return outcome
            outcome["kill_exit"] = _wsl(
                "systemctl",
                "--user",
                "kill",
                "--signal=SIGKILL",
                BUILD_SCOPE_UNIT,
                check=False,
            ).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        outcome["errors"].append(f"post_stop_or_kill_error:{type(exc).__name__}:{exc}")
    return outcome


def _recorded_launcher_invocation_id(path: Path) -> str | None:
    """Bind a fast-exiting launcher through its own systemd-run stderr record."""
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        return None
    pattern = (
        rb"Running as unit: " + re.escape(BUILD_SCOPE_UNIT.encode("ascii")) + rb"; invocation ID: ([0-9a-f]{32})(?![0-9a-f])"
    )
    matches = re.findall(pattern, data[:4096])
    return matches[0].decode("ascii") if len(matches) == 1 else None


def _dispatch_approved(profile: Mapping, first: Mapping, second: Mapping) -> dict:
    """Consume the unique attempt only after two gates; never qualify a binary here."""
    entry_before = _pin_entry()
    _require_unused_build_evidence()
    decision = audit_two_phase_dispatch(profile, first, second)
    if not decision["dispatch_permitted"]:
        raise ValueError("two-phase dispatch refused")
    before_unit = _show_build_unit()
    if before_unit["load_state"] != "not-found" or before_unit["active_state"] != "inactive":
        raise RuntimeError("named build scope already exists")
    existing = _wsl("test", "-e", BUILD_RESULT_PATH, check=False)
    linked = _wsl("test", "-L", BUILD_RESULT_PATH, check=False)
    if existing.returncode != 1 or linked.returncode != 1:
        raise FileExistsError("one-shot WSL build result path is existing or unknown")
    toolchain_before = _toolchain_snapshot()
    toolchain_audit = audit_toolchain_snapshot(toolchain_before)
    if not toolchain_audit["toolchain_verified"]:
        raise RuntimeError("pinned toolchain changed before build dispatch")
    tree_before = _build_tree_snapshot()
    tree_audit = audit_build_tree(**tree_before)
    if not tree_audit["build_tree_verified"]:
        raise RuntimeError("isolated build tree is not pristine")

    _pin_entry()
    BUILD_EVIDENCE_DIR.mkdir(parents=False, exist_ok=False)
    _write_exclusive(
        BUILD_EVIDENCE_DIR / "preflight.json",
        {
            "profile": profile,
            "first": first,
            "second": second,
            "two_phase": decision,
            "unit_before": before_unit,
            "toolchain_before": toolchain_before,
            "toolchain_audit": toolchain_audit,
            "build_tree_before": tree_before,
            "build_tree_audit": tree_audit,
            "runner_sha256": _sha256(Path(__file__)),
            "entry_before": entry_before,
            "command": build_scope_command(),
            "build_dispatched": False,
        },
    )
    result = {
        "build_dispatched": False,
        "build_exit_code": None,
        "owned_scope_released": False,
        "errors": [],
        "evidence_path": str(BUILD_EVIDENCE_DIR),
    }
    process = None
    group_path = None
    during = None
    cgroup = None
    stop_exit = None
    kill_exit = None
    scope_invocation_id = None
    timed_out = False
    try:
        _pin_entry()
        _wsl("mkdir", BUILD_RESULT_PATH)
        _write_exclusive(
            BUILD_EVIDENCE_DIR / "wsl-result-created.json",
            {
                "build_result_path": BUILD_RESULT_PATH,
                "created": True,
            },
        )
        with (BUILD_EVIDENCE_DIR / "stdout.bin").open("xb") as stdout:
            with (BUILD_EVIDENCE_DIR / "stderr.bin").open("xb") as stderr:
                _pin_entry()
                started = time.monotonic()
                deadline = started + TIMEOUT_SECONDS
                process = subprocess.Popen(build_scope_command(), stdout=stdout, stderr=stderr)
                result["build_dispatched"] = True
                result["launcher_pid"] = process.pid
                _write_exclusive(
                    BUILD_EVIDENCE_DIR / "launch.json",
                    {
                        "launcher_pid": process.pid,
                        "unit": BUILD_SCOPE_UNIT,
                        "command": build_scope_command(),
                        "started_monotonic": started,
                    },
                )
                with (BUILD_EVIDENCE_DIR / "scope-samples.jsonl").open("x", encoding="utf-8") as samples:
                    while process.poll() is None:
                        elapsed = time.monotonic() - started
                        if elapsed >= TIMEOUT_SECONDS:
                            timed_out = True
                            result["errors"].append("wall_timeout")
                            break
                        state = _show_build_unit(deadline=deadline)
                        if state["active_state"] == "active":
                            observed_id = state.get("invocation_id")
                            if (
                                not isinstance(observed_id, str)
                                or len(observed_id) != 32
                                or any(c not in "0123456789abcdef" for c in observed_id)
                            ):
                                result["errors"].append("scope_invocation_missing")
                                break
                            if scope_invocation_id is not None and observed_id != scope_invocation_id:
                                result["errors"].append("scope_invocation_changed_during_build")
                                break
                            scope_invocation_id = observed_id
                            during = state
                            try:
                                cgroup = _read_cgroup(state["control_group"], deadline=deadline)
                                group_path = cgroup["path"]
                            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                                result["errors"].append(f"scope_runtime_invalid:{exc}")
                                break
                            samples.write(json.dumps({"elapsed_s": elapsed, "unit": state, "cgroup": cgroup}) + "\n")
                            samples.flush()
                        elif elapsed >= 15 and during is None:
                            result["errors"].append("build_scope_not_observed")
                            break
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            time.sleep(min(1 if during is None else 5, remaining))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result["errors"].append(f"dispatch_error:{type(exc).__name__}:{exc}")
    finally:
        try:
            state_at_final = _show_build_unit()
            if state_at_final["active_state"] == "active":
                result["errors"].append("scope_still_active_after_launcher_or_abort")
                if scope_invocation_id is None:
                    scope_invocation_id = _recorded_launcher_invocation_id(BUILD_EVIDENCE_DIR / "stderr.bin")
                    result["invocation_from_launcher_stderr"] = scope_invocation_id
                stop_action = _stop_owned_scope(scope_invocation_id)
                stop_exit = stop_action["stop_exit"]
                kill_exit = stop_action["kill_exit"]
                result["final_stop_action"] = stop_action
                result["errors"].extend(stop_action["errors"])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["errors"].append(f"final_scope_check_error:{exc}")
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                result["errors"].append("final_launcher_kill_scope_unknown")
        if process is not None:
            result["build_exit_code"] = process.returncode
            exit_error, _ = classify_build_exit(process.returncode)
            if exit_error:
                result["errors"].append(exit_error)
            result["elapsed_s"] = time.monotonic() - started
        try:
            post = _show_build_unit()
            group_after = _wsl("test", "-e", group_path, check=False).returncode if group_path else None
            cleanup_facts = {
                "unit": BUILD_SCOPE_UNIT,
                "during": during,
                "post": post,
                "cgroup_members_during": cgroup["members"] if cgroup else None,
                "cgroup_read_exit": 0 if cgroup else None,
                "cgroup_exists_after": group_after == 0 if group_after is not None else None,
                "cgroup_after_test_exit": group_after,
                "launcher_alive_after": process.poll() is None if process else None,
            }
            if stop_exit is not None:
                cleanup_facts["stop_exit"] = stop_exit
            if kill_exit is not None:
                cleanup_facts["kill_exit"] = kill_exit
            cleanup = audit_owned_scope_cleanup(cleanup_facts)
            result["cleanup"] = cleanup
            result["owned_scope_released"] = cleanup["owned_scope_released"]
            if not cleanup["owned_scope_released"]:
                result["errors"].append("owned_cleanup_unverified")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["errors"].append(f"cleanup_observation_error:{exc}")
        try:
            toolchain_after = _toolchain_snapshot()
            result["toolchain_after"] = toolchain_after
            result["toolchain_unchanged"] = toolchain_after == toolchain_before
            if not result["toolchain_unchanged"]:
                result["errors"].append("toolchain_changed_during_build")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["toolchain_unchanged"] = False
            result["errors"].append(f"toolchain_post_unknown:{exc}")
        try:
            result["entry_after"] = _pin_entry()
            result["entry_unchanged"] = result["entry_after"] == entry_before
        except (OSError, ValueError) as exc:
            result["entry_unchanged"] = False
            result["errors"].append(f"entry_post_unknown_or_changed:{exc}")
        result["timed_out"] = timed_out
        _persist_final_result(BUILD_EVIDENCE_DIR / "dispatch-result.json", result)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wsl(*args: str, check: bool = True, deadline: float | None = None) -> subprocess.CompletedProcess[str]:
    budget = 30 if deadline is None else min(30, deadline - time.monotonic())
    if budget <= 0:
        raise subprocess.TimeoutExpired(args, 0)
    return subprocess.run(
        ["wsl.exe", "--distribution", WSL_DISTRO, "--exec", *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=budget,
    )


def _is_competitor(name: str, command: str) -> bool:
    name = name.lower().removesuffix(".exe")
    command = command.lower()
    return bool(
        name in {"px4", "gz", "gzserver", "gazebo", "gz-sim-server", "make", "ninja", "cmake"}
        or "openvins" in name
        or "px4_sitl_default" in command
        or name.startswith("python")
        and any(word in command for word in ("pytest", "train", "openvins"))
        or "gz sim" in command
        or "docker build" in command
    )


def _command_sensitive_name(name: str) -> bool:
    name = name.lower().removesuffix(".exe")
    return bool(
        name.startswith("python")
        or name
        in {
            "px4",
            "gz",
            "gzserver",
            "gazebo",
            "gz-sim-server",
            "ninja",
            "cmake",
            "make",
            "pytest",
            "cmd",
            "pwsh",
            "powershell",
            "bash",
            "sh",
            "docker",
            "wsl",
            "node",
        }
        or "openvins" in name
    )


def _windows_process_name(pid: int) -> str:
    observed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Process -Id {pid} -ErrorAction Stop).ProcessName"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
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
                competitors.append({"surface": "windows", "pid": process.pid, "name": name, "command": command[:300]})
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
                competitors.append({"surface": "wsl", "pid": int(pid), "name": name, "command": command[:300]})
    except (OSError, subprocess.SubprocessError, UnicodeError):
        complete = False
    return competitors, complete


def _scope_facts() -> tuple[bool, int | None, str | None]:
    script = (
        "import json,pathlib;"
        "g=pathlib.Path('/proc/self/cgroup').read_text().strip().split(':')[-1];"
        "p=pathlib.Path('/sys/fs/cgroup')/g.lstrip('/');"
        "print(json.dumps({'group':g,'memory':(p/'memory.max').read_text().strip(),"
        "'cpu':(p/'cpu.max').read_text().strip(),"
        "'swap':(p/'memory.swap.max').read_text().strip(),"
        "'tasks':(p/'pids.max').read_text().strip()}))"
    )
    try:
        output = _wsl(
            "systemd-run",
            "--user",
            "--scope",
            "-p",
            "MemoryMax=4G",
            "-p",
            "MemorySwapMax=0",
            "-p",
            "TasksMax=256",
            "-p",
            "CPUQuota=100%",
            "python3",
            "-c",
            script,
        ).stdout
        rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        if len(rows) != 1:
            return False, None, None
        row = rows[0]
        memory = int(row["memory"])
        cpu = row["cpu"]
        return bool("run-" in row["group"] and row["swap"] == "0" and row["tasks"] == "256"), memory, cpu
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return False, None, None


def collect_admission_facts(profile: Mapping) -> dict:
    """Sample current resources and source without creating build output."""
    source_profile_hash = _sha256(SOURCE_PROFILE)
    source_auditor_hash = _sha256(SOURCE_AUDITOR)
    prepared_audit_hash = _sha256(PREPARED_SOURCE_AUDIT)
    source_command = (
        "python3",
        f"{WSL_REPO}/src/flydrones/connectome_training/px4_status_firmware.py",
        "--profile",
        f"{WSL_REPO}/configs/px4/estimator-status-firmware-profile.json",
        "--root",
        ISOLATED_ROOT,
        "--candidate",
        f"{WSL_REPO}/configs/px4/estimator-status-dds-candidate.yaml",
        "--result-path",
        BUILD_RESULT_PATH,
        "--stage",
        "candidate",
    )
    source_run = _wsl(*source_command, check=False)
    source_observation = json.loads(source_run.stdout)
    source_prepared = source_run.returncode == 0 and source_observation.get("audit", {}).get("source_prepared") is True
    meminfo = _wsl("cat", "/proc/meminfo").stdout
    available_kib = next(int(line.split()[1]) for line in meminfo.splitlines() if line.startswith("MemAvailable:"))
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
        windows_available >= MIN_WINDOWS
        and available_kib * 1024 >= MIN_WSL
        and disk_available >= MIN_DISK
        and scan_complete
        and not competitors
        and source_prepared
        and not result_exists
    )
    scope_verified, scope_memory, scope_cpu = _scope_facts() if eligible_for_scope else (False, None, None)
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
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("live firmware runner forbidden under pytest")
    _require_unused_build_evidence()
    _pin_entry()
    parser = argparse.ArgumentParser(description="One bounded PX4 firmware build attempt with pre-make scope entry")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--admission-only", action="store_true")
    mode.add_argument("--execute-once", action="store_true")
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        if args.execute_once:
            result = execute_once(profile)
            success = (
                result.get("build_dispatched") is True
                and result.get("build_exit_code") == 0
                and result.get("owned_scope_released") is True
                and result.get("cleanup", {}).get("graceful_scope_exit") is True
                and result.get("toolchain_unchanged") is True
                and result.get("entry_unchanged") is True
                and result.get("final_record_persisted") is True
                and not result.get("errors")
            )
        else:
            facts = collect_admission_facts(profile)
            audit = audit_build_admission(profile, facts)
            result = {"facts": facts, "audit": audit}
            success = audit["build_admitted"]
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"errors": [f"execution_or_collection_error:{type(exc).__name__}:{exc}"], **_NO_AUTHORITY}
        success = False
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
