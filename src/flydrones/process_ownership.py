"""Linux process identities that remain safe when PIDs are reused."""

from __future__ import annotations

import json
import math
import os
import signal
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    argv: tuple[str, ...]
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "start_ticks": self.start_ticks,
            "argv": list(self.argv),
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProcessIdentity:
        return cls(
            pid=int(value["pid"]),
            start_ticks=int(value["start_ticks"]),
            argv=tuple(str(item) for item in value["argv"]),
            role=str(value["role"]),
        )


def _start_ticks(stat_text: str) -> int:
    closing = stat_text.rfind(")")
    if closing < 0:
        raise ValueError("malformed /proc stat: missing command terminator")
    fields_from_state = stat_text[closing + 1:].split()
    if len(fields_from_state) <= 19:
        raise ValueError("malformed /proc stat: start time missing")
    return int(fields_from_state[19])


def _process_state(stat_text: str) -> str:
    closing = stat_text.rfind(")")
    if closing < 0:
        raise ValueError("malformed /proc stat: missing command terminator")
    fields_from_state = stat_text[closing + 1:].split()
    if not fields_from_state:
        raise ValueError("malformed /proc stat: process state missing")
    return fields_from_state[0]


def read_process_identity(
    pid: int,
    proc_root: Path = Path("/proc"),
    *,
    role: str = "",
) -> ProcessIdentity:
    directory = proc_root / str(pid)
    stat_text = (directory / "stat").read_text(encoding="utf-8")
    argv = tuple(
        item.decode("utf-8", errors="replace")
        for item in (directory / "cmdline").read_bytes().split(b"\0")
        if item
    )
    return ProcessIdentity(pid=pid, start_ticks=_start_ticks(stat_text), argv=argv, role=role)


def process_identity_status(record: ProcessIdentity, proc_root: Path = Path("/proc")) -> str:
    try:
        stat_text = (proc_root / str(record.pid) / "stat").read_text(encoding="utf-8")
        if _process_state(stat_text) == "Z":
            return "already-gone"
        actual = read_process_identity(record.pid, proc_root=proc_root, role=record.role)
    except (FileNotFoundError, ProcessLookupError):
        return "already-gone"
    if actual.start_ticks == record.start_ticks and not actual.argv:
        return "already-gone"
    if actual.start_ticks != record.start_ticks or actual.argv != record.argv:
        return "ownership-mismatch"
    return "matching"


def identity_matches(record: ProcessIdentity, proc_root: Path = Path("/proc")) -> bool:
    return process_identity_status(record, proc_root=proc_root) == "matching"


def load_process_registry(path: Path) -> list[ProcessIdentity]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "flydrones-owned-processes-v1":
        raise ValueError(f"unsupported process registry schema: {payload.get('schema')}")
    return [ProcessIdentity.from_dict(item) for item in payload.get("processes", [])]


def _write_process_registry(path: Path, records: Sequence[ProcessIdentity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "flydrones-owned-processes-v1",
        "processes": [record.to_dict() for record in records],
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def append_process_identity(
    registry: Path,
    pid: int,
    role: str,
    proc_root: Path = Path("/proc"),
) -> ProcessIdentity:
    record = read_process_identity(pid, proc_root=proc_root, role=role)
    records = load_process_registry(registry)
    for current in records:
        if current.pid != pid:
            continue
        if current == record:
            return current
        raise ValueError(f"PID {pid} already has a different recorded identity")
    records.append(record)
    _write_process_registry(registry, records)
    return record


def stop_owned_processes(
    records: Sequence[ProcessIdentity],
    *,
    timeout_s: float,
    proc_root: Path = Path("/proc"),
    send_signal: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[dict[str, Any]]]:
    evidence: dict[str, list[dict[str, Any]]] = {
        "stopped": [],
        "already_gone": [],
        "ownership_mismatch": [],
        "failed_to_stop": [],
    }
    pending: list[ProcessIdentity] = []
    for record in reversed(records):
        status = process_identity_status(record, proc_root=proc_root)
        if status == "already-gone":
            evidence["already_gone"].append(record.to_dict())
        elif status == "ownership-mismatch":
            evidence["ownership_mismatch"].append(record.to_dict())
        else:
            send_signal(record.pid, signal.SIGTERM)
            pending.append(record)

    attempts = max(1, math.ceil(max(timeout_s, 0.0) / 0.05))
    for _ in range(attempts):
        if not any(identity_matches(record, proc_root=proc_root) for record in pending):
            break
        sleep(0.05)

    for record in pending:
        status = process_identity_status(record, proc_root=proc_root)
        if status == "matching":
            send_signal(record.pid, signal.SIGKILL)
            sleep(0.01)
            status = process_identity_status(record, proc_root=proc_root)
        if status == "already-gone":
            evidence["stopped"].append(record.to_dict())
        elif status == "ownership-mismatch":
            evidence["ownership_mismatch"].append(record.to_dict())
        else:
            evidence["failed_to_stop"].append(record.to_dict())
    return evidence
