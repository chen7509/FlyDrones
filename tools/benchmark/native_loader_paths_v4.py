"""Trace-selected POSIX file evidence. No loader invocation or SDK imports.

Controlled static directories only: repeated observations detect inconsistency,
but do not provide hostile-rename protection, import or runtime qualification.
Declared paths retain their separate no-parent-traversal contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import time
from collections import deque

_LIMITS = dict(stream_bytes=2097152, timeout_seconds=10, terminate_seconds=5, kill_seconds=5)
_MAX_QUERY_BYTES = 9 * 1024 * 1024


class SelectedPathError(ValueError):
    """A refusal carrying observations obtained before the primary failure."""

    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _spelling(path, *, absolute=True):
    _require(type(path) is str, "path must be exact UTF8 text")
    data = path.encode("utf-8", errors="strict")
    _require(1 <= len(data) <= 4095, "path byte bound")
    _require(not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in path), "path control character")
    _require(not path.startswith("//"), "leading double slash unsupported")
    if absolute:
        _require(path.startswith("/"), "absolute selected spelling required")
    return data


def _declared(path):
    _spelling(path)
    _require(".." not in path.split("/"), "parent traversal in declared input")


def _identity(info):
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def _valid_identity(value):
    _require(
        type(value) is dict and set(value) == {"device", "inode", "mode", "size", "mtime_ns", "ctime_ns"},
        "full file identity required",
    )
    _require(all(type(x) is int for x in value.values()), "integer identity required")
    _require(value["size"] >= 0 and stat.S_ISREG(value["mode"]), "regular file identity required")


def _pin(pin):
    _require(type(pin) is dict, "query pin required")
    for key in ("requested", "resolved"):
        _declared(pin[key])
    _valid_identity(pin["identity"])
    _require(type(pin["bytes"]) is int and pin["bytes"] == pin["identity"]["size"], "query pin size mismatch")
    _require(type(pin["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", pin["sha256"]), "query pin SHA required")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate retained query key")
        result[key] = value
    return result


def _environment(value):
    _require(type(value) is dict, "exact query environment required")
    for key, text in value.items():
        _require(
            type(key) is str and type(text) is str and key and "=" not in key and "\x00" not in key and "\x00" not in text,
            "impossible process environment",
        )
        key.encode("utf-8", errors="strict")
        text.encode("utf-8", errors="strict")


def _retained_query(reference):
    # Artifact is a declared host pathname, separate from POSIX selected spelling.
    artifact = reference["query_path"]
    _require(
        type(artifact) is str and os.path.isabs(artifact) and ".." not in re.split(r"[/\\]", artifact),
        "absolute non-traversing retained query path required",
    )
    with open(artifact, "rb") as stream:
        data = stream.read(_MAX_QUERY_BYTES + 1)
    _require(len(data) <= _MAX_QUERY_BYTES, "retained query byte bound")
    _require(hashlib.sha256(data).hexdigest() == reference["query_sha256"], "retained query SHA mismatch")
    return json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_json_object)


def _version(reference, tool):
    _require(
        type(reference) is dict and set(reference) == {"query_path", "query_sha256"}, "retained tool version reference required"
    )
    version = _retained_query(reference)
    _require(
        version["schema"] == "native-tool-version-query-v4"
        and version["kind"] == "version"
        and version["argv"] == [tool["requested"], "--version"]
        and version["tool_before"] == version["tool_after"] == tool,
        "tool version identity mismatch",
    )
    _outcome(version)
    raw = bytes.fromhex(version["stdout_hex"])
    _require(
        0 < len(raw) <= _LIMITS["stream_bytes"] and raw.decode("utf-8").strip() and not bytes.fromhex(version["stderr_hex"]),
        "tool version empty/error output",
    )
    _declared(version["cwd"])
    _environment(version["env"])
    return dict(reference=copy.deepcopy(reference), query=version)


def _outcome(query):
    _require(query["limits"] == _LIMITS, "query limits mismatch")
    _require(
        type(query["returncode"]) is int
        and query["returncode"] == 0
        and query["error"] is None
        and query["timed_out"] is False
        and query["output_limited"] is False
        and query["owned_child_waited"] is True,
        "unsuccessful or partial query",
    )
    _require(
        type(query["started_monotonic_ns"]) is int
        and type(query["ended_monotonic_ns"]) is int
        and 0 <= query["started_monotonic_ns"] <= query["ended_monotonic_ns"]
        and query["ended_monotonic_ns"] - query["started_monotonic_ns"] <= 10_000_000_000,
        "query monotonic budget mismatch",
    )


def _trace(raw_path, origin):
    """Rederive a token from the retained complete query, never a caller label."""
    _require(
        type(origin) is dict
        and set(origin) == {"schema", "query_path", "query_sha256", "query_index", "entry", "role", "line_span", "token_span"},
        "exact trace origin required",
    )
    _require(origin["schema"] == "native-loader-trace-origin-v4", "trace origin schema")
    query = _retained_query(origin)
    _require(query["schema"] == "native-entry-query-v4" and query["kind"] == "ldd", "complete ldd query required")
    _require(
        type(query["index"]) is int and query["index"] > 0 and query["index"] == origin["query_index"], "query index mismatch"
    )
    _require(
        query["role"] in ("dependency_entry", "python_extension_entry") and query["role"] == origin["role"], "entry role mismatch"
    )
    _require(query["entry"] == origin["entry"] == query["input_before"] == query["input_after"], "query entry pin drift")
    _require(query["tool_before"] == query["tool_after"], "query tool pin drift")
    _pin(query["entry"])
    _pin(query["tool_before"])
    _declared(query["cwd"])
    _require(query["argv"] == [query["tool_before"]["requested"], query["entry"]["requested"]], "query argv/input mismatch")
    _environment(query["env"])
    _outcome(query)
    version = _version(query["tool_version"], query["tool_before"])
    stdout = bytes.fromhex(query["stdout_hex"])
    stderr = bytes.fromhex(query["stderr_hex"])
    _require(0 < len(stdout) <= _LIMITS["stream_bytes"] and not stderr, "empty, oversized or error trace")
    stdout.decode("utf-8", errors="strict")
    tokens = []
    offset = 0
    for line in stdout.splitlines(keepends=True):
        # Deliberately requires complete LF lines and rejects blank/unknown output.
        match = re.fullmatch(rb"[\t ]*(?:([^\s]+) => )?(/[^\r\n]+) \(0x[0-9a-fA-F]+\)\n", line)
        if match:
            path = match[2].decode("utf-8", errors="strict")
            _spelling(path)
            soname = match[1].decode("utf-8") if match[1] else None
            _require(
                soname is None or all(not c.isspace() and ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in soname),
                "malformed SONAME",
            )
            tokens.append(
                dict(
                    path=path,
                    soname=soname,
                    line_span=[offset, offset + len(line)],
                    token_span=[offset + match.start(2), offset + match.end(2)],
                )
            )
        else:
            _require(
                re.fullmatch(rb"[\t ]*linux-vdso[a-zA-Z0-9_.-]* \(0x[0-9a-fA-F]+\)\n", line), "malformed or unresolved trace line"
            )
        offset += len(line)
    matches = [
        x
        for x in tokens
        if x["path"] == raw_path and x["line_span"] == origin["line_span"] and x["token_span"] == origin["token_span"]
    ]
    _require(len(matches) == 1, "selected token provenance mismatch")
    return dict(
        origin=copy.deepcopy(origin),
        query=query,
        tool_version=version,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        token=matches[0],
        selected_token_count=len(tokens),
    )


class _PosixFilesystem:
    supported = os.name == "posix"

    def lstat(self, path):
        return os.lstat(path)

    def readlink(self, path):
        return os.readlink(path)

    def open(self, path):
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)

    def fstat(self, fd):
        return os.fstat(fd)

    def read(self, fd, size):
        return os.read(fd, size)

    def close(self, fd):
        os.close(fd)


_FS = _PosixFilesystem()


def _walk(raw, events, observations, fs):
    pending = deque(raw[1:].split("/"))
    stack = []
    links = 0

    def observed(path):
        row = _identity(fs.lstat(path))
        observations.append(dict(operation="lstat", path=path, identity=row))
        return row

    root = observed("/")
    _require(stat.S_ISDIR(root["mode"]), "root must be directory")
    while pending:
        _require(len(events) < 4096, "component event bound")
        component = pending.popleft()
        parent = "/" + "/".join(stack)
        parent_id = observed(parent)
        _require(stat.S_ISDIR(parent_id["mode"]), "ENOTDIR: component parent is not directory")
        event = dict(component=component, parent=parent, parent_identity=parent_id)
        events.append(event)
        if component in ("", "."):
            event["action"] = "current"
        elif component == "..":
            if stack:
                stack.pop()
            event["action"] = "parent"
        else:
            path = parent.rstrip("/") + "/" + component
            row = observed(path)
            event.update(path=path, identity=row, action="lookup")
            if stat.S_ISLNK(row["mode"]):
                _require(links < 40, "symlink bound")
                links += 1
                target = fs.readlink(path)
                _spelling(target, absolute=False)
                observations.append(dict(operation="readlink", path=path, target=target))
                event.update(action="symlink", target=target)
                if target.startswith("/"):
                    stack = []
                    target_parts = target[1:].split("/")
                else:
                    target_parts = target.split("/")
                pending.extendleft(reversed(target_parts))
            else:
                stack.append(component)
    canonical = "/" + "/".join(stack)
    final = observed(canonical)
    _require(stat.S_ISREG(final["mode"]), "selected file is not regular")
    return dict(events=events, observations=observations, canonical_path=canonical, final_identity=final, links=links)


def record_selected_path(raw_path: str, *, trace_origin: dict) -> dict:
    result = dict(
        schema="native-loader-selected-path-v4",
        raw_path=raw_path,
        complete=False,
        started_monotonic_ns=time.monotonic_ns(),
        started_utc_ns=time.time_ns(),
        runtime_closure_qualified=False,
        secondary_errors=[],
    )
    fd = None
    primary = None
    try:
        result["raw_utf8_hex"] = _spelling(raw_path).hex()
        result["trace"] = _trace(raw_path, trace_origin)
        _require(_FS.supported, "POSIX filesystem observation unsupported on this host")
        events = []
        observations = []
        result["partial_walk"] = dict(events=events, observations=observations)
        before = _walk(raw_path, events, observations, _FS)
        result["walk_before"] = before
        result["canonical_path"] = before["canonical_path"]
        fd = _FS.open(raw_path)  # The original spelling, never the collapsed name.
        result["fd_before"] = _identity(_FS.fstat(fd))
        _valid_identity(result["fd_before"])
        _require(result["fd_before"] == before["final_identity"], "path/descriptor disagreement")
        digest = hashlib.sha256()
        count = 0
        while True:
            block = _FS.read(fd, 65536)
            _require(type(block) is bytes and len(block) <= 65536, "invalid descriptor read")
            if not block:
                break
            digest.update(block)
            count += len(block)
            result["partial_bytes"] = count
            _require(count <= result["fd_before"]["size"], "file grew while hashing")
        result.update(bytes=count, sha256=digest.hexdigest(), fd_after=_identity(_FS.fstat(fd)))
        _require(
            result["fd_after"] == result["fd_before"] and count == result["fd_before"]["size"], "descriptor mutation/short read"
        )
        after_events = []
        after_observations = []
        result["partial_walk_after"] = dict(events=after_events, observations=after_observations)
        result["walk_after"] = _walk(raw_path, after_events, after_observations, _FS)
        _require(result["walk_after"] == before, "path/link mutation")
        result["canonical_identity"] = _identity(_FS.lstat(result["canonical_path"]))
        _require(result["canonical_identity"] == result["fd_after"], "canonical/descriptor disagreement")
        _require(_trace(raw_path, trace_origin) == result["trace"], "trace changed during observation")
    except Exception as exc:
        primary = exc
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if fd is not None:
            try:
                _FS.close(fd)
                result["descriptor_closed"] = True
            except Exception as exc:
                result["secondary_errors"].append(f"close: {type(exc).__name__}: {exc}")
                if primary is None:
                    primary = exc
                    result["error"] = f"close: {exc}"
        result.update(ended_monotonic_ns=time.monotonic_ns(), ended_utc_ns=time.time_ns())
    if primary is not None:
        raise SelectedPathError(str(primary), result) from primary
    result["complete"] = True
    return result


class _ReplayFilesystem:
    def __init__(self, observations):
        self.rows = deque(observations)

    def _next(self, operation, path):
        _require(bool(self.rows), "incomplete walk observations")
        row = self.rows.popleft()
        _require(row["operation"] == operation and row["path"] == path, "walk operation/path mismatch")
        return row

    def lstat(self, path):
        row = self._next("lstat", path)["identity"]
        _require(
            set(row) == {"device", "inode", "mode", "size", "mtime_ns", "ctime_ns"} and all(type(x) is int for x in row.values()),
            "invalid walk identity",
        )

        # Reconstruct the same os.stat_result-compatible interface without IO.
        class Info:
            pass

        info = Info()
        for key, value in row.items():
            setattr(
                info,
                {
                    "device": "st_dev",
                    "inode": "st_ino",
                    "mode": "st_mode",
                    "size": "st_size",
                    "mtime_ns": "st_mtime_ns",
                    "ctime_ns": "st_ctime_ns",
                }[key],
                value,
            )
        return info

    def readlink(self, path):
        return self._next("readlink", path)["target"]


def audit_selected_path(record: dict, *, trace_origin: dict, baseline_files: dict) -> None:
    _require(
        record["schema"] == "native-loader-selected-path-v4"
        and record["complete"] is True
        and record["runtime_closure_qualified"] is False
        and record["descriptor_closed"] is True
        and not record["secondary_errors"]
        and "error" not in record,
        "incomplete/qualified selected path",
    )
    raw = record["raw_path"]
    _require(_spelling(raw).hex() == record["raw_utf8_hex"], "raw spelling mismatch")
    _require(_trace(raw, trace_origin) == record["trace"], "trace/record mismatch")
    _require(
        type(record["started_monotonic_ns"]) is int
        and type(record["ended_monotonic_ns"]) is int
        and 0 <= record["started_monotonic_ns"] <= record["ended_monotonic_ns"],
        "path monotonic interval",
    )
    _require(
        all(type(record.get(key)) is int for key in ("started_utc_ns", "ended_utc_ns")),
        "path UTC facts required; wallclock order is not monotonic evidence",
    )
    before = record["walk_before"]
    after = record["walk_after"]
    _require(before == after, "path postcheck mismatch")
    replay = _ReplayFilesystem(before["observations"])
    rebuilt = _walk(raw, [], [], replay)
    _require(not replay.rows and rebuilt == before, "walk transcript mismatch")
    _require(record["canonical_path"] == rebuilt["canonical_path"], "canonical path mismatch")
    _valid_identity(record["fd_before"])
    _require(
        record["fd_before"] == record["fd_after"] == record["canonical_identity"] == rebuilt["final_identity"],
        "descriptor/path postcheck mismatch",
    )
    _require(type(record["bytes"]) is int and record["bytes"] == record["fd_before"]["size"], "file byte count mismatch")
    baseline = baseline_files[record["canonical_path"]] if record["canonical_path"] in baseline_files else None
    _require(
        type(baseline) is dict
        and all(baseline.get(k) == record[k] for k in ("bytes", "sha256"))
        and baseline.get("identity") == record["fd_before"],
        "canonical baseline mismatch",
    )
    _require(type(record["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", record["sha256"]), "file SHA required")
