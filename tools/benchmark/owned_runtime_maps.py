"""Bounded runtime maps for explicitly registered owned processes only."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from tools.benchmark.owned_group_evidence import parse_stat


def parse_maps(text):
    rows, seen = [], set()
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        if (len(fields) < 5 or not re.fullmatch(r"[0-9a-f]+-[0-9a-f]+", fields[0])
                or not re.fullmatch(r"[r-][w-][x-][ps]", fields[1])
                or not re.fullmatch(r"[0-9a-f]+", fields[2])
                or not re.fullmatch(r"[0-9a-f]+:[0-9a-f]+", fields[3])
                or not fields[4].isdigit()):
            raise ValueError("malformed process mapping")
        if len(fields) == 5 or fields[5].startswith("[") and fields[5].endswith("]"):
            continue
        path = fields[5]
        if not path.startswith("/") or path.endswith(" (deleted)") or "\\" in path:
            raise ValueError("deleted/escaped/nonabsolute process mapping")
        identity = (path, fields[3], int(fields[4]))
        if identity not in seen:
            seen.add(identity)
            rows.append(dict(path=path, device=fields[3], inode=int(fields[4])))
    return rows


def _read_stat(pid):
    return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")


def _read_exe(pid):
    return str(Path(f"/proc/{pid}/exe").resolve(strict=True))


def _read_maps(pid, limit):
    with Path(f"/proc/{pid}/maps").open("r", encoding="utf-8") as stream:
        return stream.read(limit + 1)


def _write(path, value):
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
    with path.open("x", encoding="utf-8") as stream:
        if stream.write(text) != len(text):
            raise OSError("short runtime map evidence write")
        stream.flush()


def _device_parts(value):
    if hasattr(os, "major"):
        return os.major(value), os.minor(value)
    return value >> 8 & 0xFFF, value & 0xFF | value >> 12 & 0xFFF00


class OwnedRuntimeMaps:
    def __init__(self, output, known, *, max_maps_bytes, max_observations,
                 stat_reader=_read_stat, exe_reader=_read_exe, maps_reader=_read_maps,
                 path_resolver=os.path.realpath):
        if type(max_maps_bytes) is not int or not 0 < max_maps_bytes <= 8 * 1024 * 1024:
            raise ValueError("invalid maps size limit")
        if type(max_observations) is not int or not 0 < max_observations <= 16:
            raise ValueError("invalid observation limit")
        self.output = Path(output)
        self.known = known
        self.max_maps_bytes = max_maps_bytes
        self.max_observations = max_observations
        self.stat_reader, self.exe_reader, self.maps_reader = stat_reader, exe_reader, maps_reader
        self.path_resolver = path_resolver
        self.registered, self.observed = {}, set()
        self.count = 0

    def _identity(self, pid):
        row = parse_stat(self.stat_reader(pid))
        if row["pid"] != pid:
            raise ValueError("owned process identity changed")
        row["executable"] = self.exe_reader(pid)
        return row

    def register(self, role, process, executable):
        if not re.fullmatch(r"[a-z][a-z0-9-]*", role) or role in self.registered:
            raise ValueError("invalid or repeated registered role")
        if type(process.pid) is not int or process.pid <= 1:
            raise ValueError("invalid owned process pid")
        requested = str(executable)
        if not requested.startswith("/"):
            raise ValueError("owned executable must be an absolute Linux path")
        identity = self._identity(process.pid)
        expected = self.path_resolver(requested)
        if identity["executable"] != expected or expected not in self.known:
            raise ValueError("owned executable is not the declared executable")
        identity["role"] = role
        self.registered[role] = identity
        _write(self.output / f"runtime-owner-{role}.json", identity)
        return dict(identity)

    def observe(self, role, phase):
        key = (role, phase)
        if role not in self.registered or not re.fullmatch(r"[a-z][a-z0-9-]*", phase):
            raise ValueError("invalid owned mapping observation")
        if key in self.observed:
            raise ValueError("repeated owned mapping phase")
        if self.count >= self.max_observations:
            raise ValueError("runtime mapping observation budget exhausted")
        self.observed.add(key)
        self.count += 1
        record = dict(role=role, phase=phase, observed_files_covered=False, error=None)
        raw = ""
        try:
            before = self._identity(self.registered[role]["pid"])
            expected = self.registered[role]
            if any(before[k] != expected[k] for k in ("pid", "pgrp", "session", "start_ticks")):
                raise ValueError("owned process identity changed")
            if before["executable"] != expected["executable"]:
                raise ValueError("owned process executable changed")
            raw = self.maps_reader(expected["pid"], self.max_maps_bytes)
            if len(raw) > self.max_maps_bytes:
                raise ValueError("runtime maps size limit exceeded")
            after = self._identity(expected["pid"])
            if any(after[k] != expected[k] for k in ("pid", "pgrp", "session", "start_ticks")):
                raise ValueError("owned process identity changed")
            if after["executable"] != expected["executable"]:
                raise ValueError("owned process executable changed")
            unknown, mismatched = [], []
            for row in parse_maps(raw):
                identity = self.known.get(row["path"])
                if identity is None:
                    unknown.append(row)
                elif (row["inode"] != identity["inode"]
                      or tuple(int(x, 16) for x in row["device"].split(":"))
                      != _device_parts(identity["device"])):
                    mismatched.append(row)
            record.update(identity_before=before, identity_after=after, unknown=unknown, mismatched=mismatched)
            if unknown or mismatched:
                raise ValueError("runtime process mappings are not covered")
            record["observed_files_covered"] = True
        except Exception as exc:
            record["error"] = repr(exc)
        raw_path = self.output / f"runtime-maps-{role}-{phase}.txt"
        with raw_path.open("x", encoding="utf-8") as stream:
            if stream.write(raw) != len(raw):
                raise OSError("short runtime maps write")
            stream.flush()
        _write(self.output / f"runtime-maps-{role}-{phase}.json", record)
        if record["error"]:
            raise ValueError(record["error"])
        return record
