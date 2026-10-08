"""Offline wire evidence readers. Full live-chain qualification is not implemented.

Integrity of retained files is distinct from receipt by PX4, source provenance,
or runtime success. These helpers grant neither live nor fusion qualification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, _unique_pairs
from tools.benchmark.declared_runtime_snapshot import file_record
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


def _equal(value, expected, label):
    if not _typed_equal(value, expected):
        raise ValueError("inconsistent " + label)


def _shape(value, keys, label):
    if type(value) is not dict or value.keys() != set(keys):
        raise ValueError("invalid " + label + " schema")


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid " + label)


def _json(raw):
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid(value)
        return number

    return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=invalid, parse_float=finite_float)


def _read_stable(path, maximum):
    if path.is_symlink() or path.stat().st_size > maximum:
        raise ValueError("symlink or oversized evidence member")
    before = file_record(path)
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("evidence member exceeded read bound")
    _equal(file_record(path), before, "evidence identity during read")
    _equal(len(data), before["bytes"], "evidence read length")
    _equal(hashlib.sha256(data).hexdigest(), before["sha256"], "evidence read hash")
    return data, before


def read_segmented_wire_records(directory, terminal):
    """Verify producer member index against terminal evidence and raw JSONL.

    The supplied terminal record still needs binding to capture/owner evidence by
    the complete auditor. Original directory strings may differ from an archive's
    extraction path; only the exact indexed local member names are opened here.
    """
    directory = Path(directory)
    keys = (
        "profile",
        "directory",
        "phase",
        "limits",
        "closed",
        "failure",
        "records",
        "bytes",
        "channels",
        "segments",
        "active",
        "unsealed",
        "failed_record",
        "unpersisted_failures",
        "complete_retention",
        "fsync_proven",
        "network_authorized",
        "fusion_qualified",
    )
    _shape(terminal, keys, "retention")
    limits = dict(segments=64, events_per_segment=8192, bytes=512 * 1024 * 1024)
    for key, expected in dict(
        profile="capture-wire-segmented-v1",
        limits=limits,
        closed=True,
        failure=None,
        active=None,
        unsealed=[],
        failed_record=None,
        unpersisted_failures={},
        complete_retention=True,
        fsync_proven=False,
        network_authorized=False,
        fusion_qualified=False,
    ).items():
        _equal(terminal[key], expected, "retention " + key)
    if type(terminal["directory"]) is not str or not terminal["directory"]:
        raise ValueError("original retention directory missing")
    phases = ("bootstrap", "maintenance", "stopping")
    if terminal["phase"] not in phases:
        raise ValueError("unknown terminal phase")
    _integer(terminal["records"], 1, 64 * 8192, "record count")
    _integer(terminal["bytes"], 1, limits["bytes"], "total bytes")
    channels = terminal["channels"]
    if type(channels) is not dict or not channels or not channels.keys() <= SegmentedWireJournal.CHANNELS:
        raise ValueError("unknown/empty channel set")
    for count in channels.values():
        _integer(count, 0, terminal["records"], "channel count")
    members = terminal["segments"]
    if type(members) is not list or not 1 <= len(members) <= 64:
        raise ValueError("invalid segment count")
    manifest_raw, manifest_identity = _read_stable(directory / "manifest.json", 1024 * 1024)
    index = _json(manifest_raw)
    expected_index = copy.deepcopy(terminal)
    expected_index.update(complete_retention=False, manifest_scope="member_index_not_completion_grant")
    _equal(index, expected_index, "member index versus terminal retention")
    expected_names = {"manifest.json", *(f"segment-{n:04d}.jsonl" for n in range(len(members)))}
    _equal({path.name for path in directory.iterdir()}, expected_names, "directory members")
    rows, identities = [], [manifest_identity]
    counts = {key: 0 for key in channels}
    total_bytes, phase_index = 0, 0
    for number, member in enumerate(members):
        _shape(member, ("name", "first_index", "last_index", "records", "bytes", "sha256"), "segment")
        _equal(member["name"], f"segment-{number:04d}.jsonl", "segment name")
        _integer(member["records"], 1, 8192, "segment records")
        if number < len(members) - 1:
            _equal(member["records"], 8192, "full preceding segment")
        _integer(member["bytes"], 1, limits["bytes"] - total_bytes, "segment bytes")
        _equal(member["first_index"], len(rows), "segment first index")
        _equal(member["last_index"], len(rows) + member["records"] - 1, "segment last index")
        data, identity = _read_stable(directory / member["name"], member["bytes"])
        identities.append(identity)
        _equal(len(data), member["bytes"], "member length")
        _equal(identity["sha256"], member["sha256"], "member hash")
        if not data.endswith(b"\n"):
            raise ValueError("unterminated JSONL member")
        lines = data.splitlines()
        _equal(len(lines), member["records"], "member line count")
        for line in lines:
            row = _json(line)
            _shape(row, ("index", "source", "source_index", "phase", "event"), "wire row")
            _equal(row["index"], len(rows), "global ordinal")
            if type(row["source"]) is not str or row["source"] not in counts:
                raise ValueError("undeclared channel")
            _equal(row["source_index"], counts[row["source"]], "channel ordinal")
            if row["phase"] not in phases or phases.index(row["phase"]) < phase_index:
                raise ValueError("invalid/regressed phase")
            phase_index = phases.index(row["phase"])
            if type(row["event"]) is not dict:
                raise ValueError("event must be a dictionary")
            counts[row["source"]] += 1
            rows.append(row)
        total_bytes += len(data)
    _equal(counts, channels, "final channel counts")
    _equal(len(rows), terminal["records"], "total records")
    _equal(total_bytes, terminal["bytes"], "total bytes")
    if phase_index > phases.index(terminal["phase"]):
        raise ValueError("terminal phase precedes retained event")
    for identity in identities:
        _equal(file_record(identity["requested"]), identity, "final evidence identity")
    _equal({path.name for path in directory.iterdir()}, expected_names, "final directory members")
    return dict(
        records=rows, channels=counts, members=identities, integrity_verified=True, live_qualified=False, fusion_qualified=False
    )
