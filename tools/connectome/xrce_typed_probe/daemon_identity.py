"""Read-only, prospective identity gate for one owned WSL Docker container.

This does not authenticate a PX4 producer or attest what happened between probes.
"""

from __future__ import annotations

import re
import subprocess
import time

SCHEMA = "flydrones.xrce_owned_daemon_identity.v1"
PREFIX = ["wsl", "-d", "Ubuntu", "--", "docker"]
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_CONTEXT = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


class DaemonProbeError(ValueError):
    """Refusal carrying the actual partial read-only query evidence."""

    def __init__(self, reason: str, record: dict) -> None:
        super().__init__(reason)
        self.record = record


def _commands(owned_name: str) -> dict[str, list[str]]:
    if type(owned_name) is not str or _NAME.fullmatch(owned_name) is None:
        raise ValueError("owned name invalid")
    escaped_name = owned_name.replace(".", r"\.")
    return {
        "info": PREFIX + ["info", "--format", "{{.ID}}"],
        "context": PREFIX + ["context", "show"],
        "ps": PREFIX + ["ps", "-a", "--filter", f"name=^/{escaped_name}$",
                          "--format", "{{.Names}}"],
    }


def _one_line(record: dict, label: str, pattern: re.Pattern[str]) -> str:
    if type(record.get("returncode")) is not int or record["returncode"] != 0:
        raise ValueError(f"{label} query failed")
    raw = record.get("stdout")
    if type(raw) is not str or raw.count("\n") != 1 or not raw.endswith("\n"):
        raise ValueError(f"{label} record malformed")
    value = raw[:-1]
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} record malformed")
    return value


def _validate_one(record: dict, owned_name: str) -> None:
    commands = _commands(owned_name)
    if (type(record) is not dict
            or set(record) != {"schema", "owned_name", "sample_monotonic_ns",
                               "daemon_id", "context", "queries", "px4_source_authenticated"}
            or record["schema"] != SCHEMA or record["owned_name"] != owned_name
            or type(record["sample_monotonic_ns"]) is not int
            or record["sample_monotonic_ns"] <= 0
            or record["px4_source_authenticated"] is not False
            or type(record["queries"]) is not dict
            or set(record["queries"]) != set(commands)):
        raise ValueError("daemon record schema mismatch")
    for label, command in commands.items():
        query = record["queries"][label]
        if (type(query) is not dict
                or set(query) != {"args", "returncode", "stdout", "stderr"}
                or query["args"] != command
                or type(query["stderr"]) is not str):
            raise ValueError(f"{label} record mismatch")
    if record["daemon_id"] != _one_line(record["queries"]["info"], "info", _ID):
        raise ValueError("daemon record ID mismatch")
    if record["context"] != _one_line(record["queries"]["context"], "context", _CONTEXT):
        raise ValueError("daemon record context mismatch")
    ps = record["queries"]["ps"]
    if type(ps["returncode"]) is not int or ps["returncode"] != 0:
        raise ValueError("ps query failed")
    if ps["stdout"] != "":
        raise ValueError("owned container still present or ambiguous")


def observe(owned_name: str, *, runner=subprocess.run,
            clock_ns=time.monotonic_ns) -> dict:
    """Probe through one WSL Docker CLI; never starts or removes a container."""
    commands = _commands(owned_name)
    queries = {}
    started_ns = clock_ns()
    for label, command in commands.items():
        try:
            completed = runner(command, capture_output=True, text=True,
                               errors="replace", timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DaemonProbeError(f"{label} query failed", {
                "owned_name": owned_name, "sample_monotonic_ns": started_ns,
                "queries": queries, "failed_command": command,
                "exception": repr(exc),
            }) from exc
        queries[label] = {"args": command, "returncode": completed.returncode,
                          "stdout": completed.stdout, "stderr": completed.stderr}
        if completed.returncode != 0:
            raise DaemonProbeError(f"{label} query failed", {
                "owned_name": owned_name, "sample_monotonic_ns": started_ns,
                "queries": queries,
            })
    result = {"schema": SCHEMA, "owned_name": owned_name,
              "sample_monotonic_ns": clock_ns(),
              "daemon_id": queries["info"]["stdout"].strip(),
              "context": queries["context"]["stdout"].strip(),
              "queries": queries, "px4_source_authenticated": False}
    try:
        _validate_one(result, owned_name)
    except ValueError as exc:
        raise DaemonProbeError(str(exc), result) from exc
    return result


def validate_pair(before: dict, after: dict, owned_name: str) -> dict:
    """Require stable Docker identity; still not a capture/producer grant."""
    _validate_one(before, owned_name)
    _validate_one(after, owned_name)
    if (before["daemon_id"] != after["daemon_id"]
            or before["context"] != after["context"]
            or before["sample_monotonic_ns"] >= after["sample_monotonic_ns"]):
        raise ValueError("Docker daemon identity changed or time reversed")
    return {"schema": "flydrones.xrce_owned_daemon_pair.v1",
            "owned_name": owned_name,
            "daemon_id": before["daemon_id"], "context": before["context"],
            "same_daemon": True, "owned_container_absent": True,
            "intervening_capture_verified": False,
            "px4_source_authenticated": False, "fusion_qualified": False}
