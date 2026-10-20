"""Preserve PX4 SITL ULogs from one episode's private runtime directory."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ULOG_MAGIC = b"ULog\x01\x12\x35"


def ulog_evidence_failures(records: list[dict], capture_error: str | None) -> list[str]:
    if capture_error is not None:
        return ["px4_ulog_capture_error"]
    if not records:
        return ["px4_ulog_missing"]
    if any(not record.get("valid_header") for record in records):
        return ["px4_ulog_invalid_header"]
    return []


def episode_exit_code(status: str, evidence_failures: list[str]) -> int:
    return 2 if status in {"infrastructure_error", "controller_error"} or evidence_failures else 0


def verify_episode_ulog_evidence(episode: Path, result: dict) -> None:
    """Fail closed before a new formal report accepts an episode result."""
    episode = Path(episode).resolve()
    records = result.get("px4_ulogs")
    if result.get("px4_ulog_capture_accepted") is not True or not isinstance(records, list) or not records:
        raise ValueError("missing validated PX4 ULog capture")
    manifest = episode / "px4-ulog-manifest.json"
    if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("logs") != records:
        raise ValueError("PX4 ULog manifest differs from result")
    for record in records:
        relative = Path(record["path"])
        log = (episode / relative).resolve()
        if relative.is_absolute() or not log.is_relative_to(episode / "px4-ulog") or not log.is_file():
            raise ValueError("PX4 ULog path invalid or missing")
        if log.stat().st_size != record["bytes"]:
            raise ValueError(f"changed PX4 ULog: {relative}")
        with log.open("rb") as stream:
            header = stream.read(16)
        with log.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != record["sha256"] or len(header) != 16 or not header.startswith(ULOG_MAGIC):
            raise ValueError(f"changed PX4 ULog: {relative}")


def collect_ulogs(runtime: Path, output: Path) -> list[dict]:
    """Copy every ULog without overwriting evidence and record its digest.

    Call only after the episode's PX4 process has exited so the logger has
    flushed. A missing or truncated log is retained as an explicit failure.
    """
    runtime = Path(runtime).resolve()
    output = Path(output).resolve()
    sources = sorted(runtime.rglob("*.ulg")) if runtime.is_dir() else []
    copies = []
    for source in sources:
        resolved = source.resolve()
        if not resolved.is_relative_to(runtime) or not resolved.is_file():
            raise ValueError(f"ULog outside episode runtime: {source}")
        relative = source.relative_to(runtime)
        destination = output / "px4-ulog" / relative
        if destination.exists():
            raise FileExistsError(destination)
        copies.append((source, destination))
    manifest = output / "px4-ulog-manifest.json"
    if manifest.exists():
        raise FileExistsError(manifest)

    records = []
    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        with destination.open("rb") as stream:
            header = stream.read(16)
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append({
            "path": destination.relative_to(output).as_posix(),
            "bytes": destination.stat().st_size,
            "sha256": digest,
            "valid_header": len(header) == 16 and header.startswith(ULOG_MAGIC),
        })
    output.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"schema": "flydrones-px4-ulog-capture-v1",
                                    "logs": records}, indent=2) + "\n", encoding="utf-8")
    return records
