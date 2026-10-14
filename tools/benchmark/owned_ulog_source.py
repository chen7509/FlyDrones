"""Produce bounded owned writable-opener evidence; never grant sensor authority."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
from itertools import islice
from pathlib import Path

from tools.benchmark.owned_group_evidence import DEAD, parse_stat

LIMITS = {
    "max_fd_entries": 256,
    "max_log_identities": 8,
    "max_observations": 64,
    "max_artifact_bytes": 64 * 1024**2,
    "observe_sim_period_ns": 1_000_000_000,
}
ARTIFACTS = ("rgb-capture-manifest.json", "camera-info.json", "events.jsonl", "px4-ulog-manifest.json")


def identity(pid):
    result = parse_stat(Path(f"/proc/{pid}/stat").read_text(encoding="utf8"))
    result["executable"] = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    return result


def duplicate_record(pid, target_fd):
    """Bind identity/access mode to one open file description; never modify it."""
    if platform.system() != "Linux" or platform.machine() != "x86_64" or not hasattr(os, "pidfd_open"):
        raise ValueError("owned descriptor duplication requires Linux x86_64 pidfd API")
    import ctypes
    import fcntl

    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    pidfd = os.pidfd_open(pid, 0)
    duplicate = -1
    try:
        duplicate = int(library.syscall(ctypes.c_long(438), ctypes.c_int(pidfd), ctypes.c_int(target_fd), ctypes.c_uint(0)))
        if duplicate < 0:
            error = ctypes.get_errno()
            raise OSError(error, "owned pidfd_getfd refused: " + os.strerror(error))
        return os.fstat(duplicate), fcntl.fcntl(duplicate, fcntl.F_GETFL)
    finally:
        try:
            if duplicate >= 0:
                os.close(duplicate)
        finally:
            os.close(pidfd)


def descriptors(pid, limit):
    paths = list(islice(Path(f"/proc/{pid}/fd").iterdir(), limit + 1))
    if len(paths) > limit:
        raise ValueError("owned fd entry budget exceeded")
    rows = []
    for p in paths:
        if not p.name.isdecimal():
            raise ValueError("invalid owned fd entry")
        try:
            target = os.readlink(p)
        except FileNotFoundError:
            continue  # Ordinary non-ULog descriptors can close during enumeration.
        if not target.endswith((".ulg", ".ulg (deleted)")):
            continue
        if target.endswith(" (deleted)"):
            raise ValueError("deleted owned ULog descriptor")
        s, flags = duplicate_record(pid, int(p.name))
        named = Path(target).stat()
        if (s.st_dev, s.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("owned descriptor identity changed during duplication")
        rows.append(
            {
                "fd": int(p.name),
                "path": target,
                "device": s.st_dev,
                "inode": s.st_ino,
                "mode": s.st_mode,
                "flags": flags,
            }
        )
    return rows


def linked(path):
    return any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path.absolute(), *path.absolute().parents))


def file_record(path):
    path = Path(path)
    if linked(path) or not path.is_file():
        raise ValueError("regular controlled artifact required")
    before = path.stat()
    if before.st_size > LIMITS["max_artifact_bytes"]:
        raise ValueError("artifact byte budget exceeded")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(LIMITS["max_artifact_bytes"] + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    final_path = path.stat()
    if (
        len(raw) != before.st_size
        or len(raw) > LIMITS["max_artifact_bytes"]
        or any(getattr(before, f) != getattr(s, f) for s in (opened, after, final_path) for f in fields)
        # Windows Python3.12 stat/fstat expose different ctime semantics.
        or before.st_ctime_ns != final_path.st_ctime_ns
        or opened.st_ctime_ns != after.st_ctime_ns
    ):
        raise ValueError("artifact changed during read")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "device": before.st_dev, "inode": before.st_ino}


def write(path, value):
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


class OwnedUlogSource:
    def __init__(self, runtime, output, *, expected_executable_sha256, identity_reader=identity, fd_reader=descriptors):
        self.runtime, self.output = Path(runtime), Path(output)
        if (
            linked(self.runtime)
            or linked(self.output)
            or not self.runtime.is_dir()
            or not self.output.is_dir()
            or list(self.runtime.rglob("*.ulg"))
        ):
            raise ValueError("new controlled runtime without existing ULogs required")
        if type(expected_executable_sha256) is not str or re.fullmatch("[0-9a-f]{64}", expected_executable_sha256) is None:
            raise ValueError("declared executable digest required")
        self.directory = self.output / "owned-ulog-source"
        self.directory.mkdir(exist_ok=False)
        self.expected_sha = expected_executable_sha256
        self.identity_reader, self.fd_reader = identity_reader, fd_reader
        self.process = None
        self.owner = None
        self.observations = 0
        self.logs = {}
        self.failure = None

    def current_identity(self):
        if self.process is None or self.process.poll() is not None:
            raise ValueError("owned process identity not alive")
        row = self.identity_reader(self.process.pid)
        if row["pid"] != self.process.pid or row["state"] in DEAD:
            raise ValueError("owned process identity not alive")
        return {k: row[k] for k in ("pid", "pgrp", "session", "start_ticks", "executable")}

    def register(self, process, executable):
        if self.process is not None or type(process.pid) is not int or process.pid <= 1:
            raise ValueError("one actual owned Popen required")
        self.process = process
        self.owner = self.current_identity()
        record = file_record(executable)
        if self.owner["executable"] != str(Path(executable).resolve(strict=True)) or record["sha256"] != self.expected_sha:
            raise ValueError("owned executable identity mismatch")
        write(self.directory / "owner.json", {"identity": self.owner, "executable": record, "source_authenticated": False})

    def observe(self):
        if self.failure is not None:
            raise ValueError("owned source observation previously failed: " + self.failure)
        try:
            return self._observe()
        except Exception as error:
            self.failure = str(error)
            raise

    def _observe(self):
        if self.current_identity() != self.owner:
            raise ValueError("owned process identity changed")
        if self.observations >= LIMITS["max_observations"]:
            raise ValueError("owned source observation budget exceeded")
        self.observations += 1
        rows = self.fd_reader(self.process.pid, LIMITS["max_fd_entries"])
        if len(rows) > LIMITS["max_fd_entries"]:
            raise ValueError("owned fd entry budget exceeded")
        opened = []
        pending = dict(self.logs)
        for row in rows:
            path = Path(row["path"])
            if (
                not path.is_absolute()
                or linked(path)
                or not path.resolve().is_relative_to(self.runtime.resolve())
                or path.suffix != ".ulg"
                or not stat.S_ISREG(row["mode"])
            ):
                raise ValueError("owned ULog descriptor escapes controlled runtime")
            if row["flags"] & 0o3 not in (os.O_WRONLY, os.O_RDWR):  # Linux O_ACCMODE; Windows protocol tests lack it.
                raise ValueError("owned ULog descriptor is not writable")
            s = path.stat()
            if (s.st_dev, s.st_ino) != (row["device"], row["inode"]):
                raise ValueError("owned ULog fd/path inode mismatch")
            name = path.relative_to(self.runtime).as_posix()
            observation = {
                "path": name,
                "device": s.st_dev,
                "inode": s.st_ino,
                "fd": row["fd"],
                "flags": row["flags"],
                "owner": self.owner,
            }
            if name in self.logs and any(self.logs[name][k] != observation[k] for k in ("device", "inode")):
                raise ValueError("owned ULog path was replaced")
            pending[name] = observation
            if len(pending) > LIMITS["max_log_identities"]:
                raise ValueError("owned ULog identity budget exceeded")
            opened.append(observation)
        if self.current_identity() != self.owner:
            raise ValueError("owned process identity changed during observation")
        write(
            self.directory / f"open-{self.observations:03d}.json",
            {"owner": self.owner, "opened": opened, "live_source_authenticated": False, "sole_writer_proven": False},
        )
        self.logs = pending

    def finish(self, records):
        if self.process is None or self.process.poll() is None:
            raise ValueError("actual owned child exit required before source association")
        summary = {
            "schema": "capture-owned-ULog-opener-association-v1",
            "owner": self.owner,
            "owner_exit": self.process.poll(),
            "logs": [],
            "artifacts": {},
            "errors": [],
            "live_source_authenticated": False,
            "sole_writer_proven": False,
            "sensor_generation_time_verified": False,
            "clock_epoch_qualified": False,
            "camera_calibration_verified": False,
            "fusion_training_flight_eligible": False,
        }
        if self.failure is not None:
            summary["errors"].append("prior source observation failed: " + self.failure)
        collected = {Path(*Path(row["path"]).parts[1:]).as_posix() for row in records}
        for name in self.logs.keys() - collected:
            summary["errors"].append("witnessed ULog missing from collection: " + name)
        for row in records:
            result = {"path": row["path"], "sha256": row["sha256"], "observed_writable_opener": False}
            try:
                p = Path(row["path"])
                if p.is_absolute() or ".." in p.parts or p.parts[0] != "px4-ulog":
                    raise ValueError("collected log path invalid")
                relative = Path(*p.parts[1:])
                witness = self.logs.get(relative.as_posix())
                if witness is None:
                    raise ValueError("collected ULog lacks owned writable opener witness")
                source = file_record(self.runtime / relative)
                copied = file_record(self.output / p)
                if (
                    (source["device"], source["inode"]) != (witness["device"], witness["inode"])
                    or source["sha256"] != row["sha256"]
                    or copied["sha256"] != row["sha256"]
                    or source["bytes"] != row["bytes"]
                    or copied["bytes"] != row["bytes"]
                ):
                    raise ValueError("source/copy inode or byte identity changed")
                result.update(observed_writable_opener=True, witness=witness)
            except (OSError, ValueError) as error:
                result["error"] = str(error)
                summary["errors"].append(str(error))
            summary["logs"].append(result)
        if not records:
            summary["errors"].append("no ULogs collected")
        for name in ARTIFACTS:
            try:
                summary["artifacts"][name] = file_record(self.output / name)
            except (OSError, ValueError) as error:
                summary["errors"].append(name + ": " + str(error))
        summary["all_logs_associated"] = bool(records) and not summary["errors"]
        write(self.directory / "association.json", summary)
        return summary
