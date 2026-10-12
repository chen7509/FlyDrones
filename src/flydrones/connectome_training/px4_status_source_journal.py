"""Audit local read-only EstimatorStatus CDR envelopes, never grant capture."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "flydrones.px4_estimator_status_cdr.v1"
TOPIC = "/fmu/out/estimator_status"
ROS_TYPE = "px4_msgs/msg/EstimatorStatus"
MESSAGE_SHA256 = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
RATIOS = frozenset(("hdg_test_ratio", "vel_test_ratio", "pos_test_ratio", "hgt_test_ratio",
                    "tas_test_ratio", "hagl_test_ratio", "beta_test_ratio"))
RESETS = frozenset(("reset_count_vel_ne", "reset_count_vel_d", "reset_count_pos_ne",
                    "reset_count_pod_d", "reset_count_quat"))
SAMPLE_KEYS = frozenset((
    "schema", "kind", "topic", "ros_type", "message_sha256", "run_id",
    "journal_sequence", "rmw_implementation", "publisher_gid_hex",
    "rmw_source_timestamp_ns", "rmw_received_timestamp_ns",
    "rmw_publication_sequence", "rmw_reception_sequence", "callback_steady_ns",
    "px4_publication_us", "px4_sample_us", "control_mode_flags",
    "filter_fault_flags", "gps_check_fail_flags", "solution_status_flags",
    "pos_horiz_accuracy", "pos_vert_accuracy", "innovation_test_ratios",
    "innovation_ratio_available", "reset_counters", "cdr_hex", "cdr_sha256",
))
FAULT_KEYS = frozenset(("schema", "kind", "run_id", "reason", "cdr_length",
                        "cdr_hex", "cdr_sha256"))
FINISH_KEYS = frozenset(("schema", "kind", "run_id", "samples", "status", "reason"))
HEX = re.compile(r"[0-9a-f]+\Z")
RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
RMW = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
REASON = re.compile(r"[a-z_]{1,64}\Z")
MAX_LINE = 32768
MAX_CDR = 4096
MAX_SAMPLES = 8192
MAX_SAMPLE_GAP_US = 100_000
MAX_NS = 2**63 - 1
MAX_US = MAX_NS // 1000
MAX_F32 = 3.4028234663852886e38


@dataclass(frozen=True)
class StatusSourceJournalAudit:
    run_id: str
    samples: int
    completed: bool
    publisher_gid_hex: str
    first_cdr: bytes
    journal_sha256: str
    last_publication_us: int | None
    last_sample_us: int | None
    publication_to_sample_delay_us: int | None
    rmw_sequences_supported: bool
    observed_rmw_gap: bool
    unavailable_innovation_ratios: frozenset[str]
    faults: int
    live_source_authenticated: bool = False
    upstream_loss_qualified: bool = False
    fusion_qualified: bool = False
    camera_calibration_qualified: bool = False
    training_eligible: bool = False


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate status journal key: {key}")
        result[key] = value
    return result


def _integer(value, label, *, minimum=0, maximum=MAX_NS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {label}")
    return value


def _f32(value, label):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not 0 <= value <= MAX_F32):
        raise ValueError(f"invalid {label}")


def _cdr(row):
    value, digest = row["cdr_hex"], row["cdr_sha256"]
    if (type(value) is not str or not 8 <= len(value) <= 2 * MAX_CDR
            or len(value) % 2 or HEX.fullmatch(value) is None
            or type(digest) is not str or len(digest) != 64 or HEX.fullmatch(digest) is None):
        raise ValueError("status CDR or digest invalid")
    payload = bytes.fromhex(value)
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("status CDR digest mismatch")
    return payload


def _sample(row, previous):
    if (set(row) != SAMPLE_KEYS or row["schema"] != SCHEMA or row["kind"] != "sample"
            or row["topic"] != TOPIC or row["ros_type"] != ROS_TYPE
            or row["message_sha256"] != MESSAGE_SHA256):
        raise ValueError("status sample schema/type mismatch")
    if type(row["run_id"]) is not str or RUN.fullmatch(row["run_id"]) is None:
        raise ValueError("status run identity invalid")
    if (type(row["rmw_implementation"]) is not str
            or RMW.fullmatch(row["rmw_implementation"]) is None):
        raise ValueError("status RMW implementation invalid")
    gid = row["publisher_gid_hex"]
    if type(gid) is not str or len(gid) != 48 or HEX.fullmatch(gid) is None or gid == "0" * 48:
        raise ValueError("status publisher GID invalid")
    _integer(row["journal_sequence"], "journal sequence", minimum=1)
    _integer(row["callback_steady_ns"], "callback time", minimum=1)
    for name in ("rmw_source_timestamp_ns", "rmw_received_timestamp_ns"):
        _integer(row[name], name)
    for name in ("rmw_publication_sequence", "rmw_reception_sequence"):
        if row[name] is not None:
            _integer(row[name], name, maximum=2**64 - 2)
    publication = _integer(row["px4_publication_us"], "PX4 publication", minimum=1, maximum=MAX_US)
    sample = _integer(row["px4_sample_us"], "PX4 sample", minimum=1, maximum=MAX_US)
    if sample > publication:
        raise ValueError("PX4 sample after publication")
    for name, bound in (("control_mode_flags", 2**64 - 1), ("filter_fault_flags", 2**32 - 1),
                        ("gps_check_fail_flags", 2**16 - 1), ("solution_status_flags", 2**16 - 1)):
        _integer(row[name], name, maximum=bound)
    for name in ("pos_horiz_accuracy", "pos_vert_accuracy"):
        _f32(row[name], name)
    resets = row["reset_counters"]
    if type(resets) is not dict or set(resets) != RESETS:
        raise ValueError("status reset counters invalid")
    for name, value in resets.items():
        _integer(value, name, maximum=255)
    ratios, available = row["innovation_test_ratios"], row["innovation_ratio_available"]
    if (type(ratios) is not dict or type(available) is not dict
            or set(ratios) != RATIOS or set(available) != RATIOS):
        raise ValueError("status ratio schema invalid")
    unavailable = set()
    for name in RATIOS:
        if type(available[name]) is not bool:
            raise ValueError("status ratio availability invalid")
        if available[name]:
            _f32(ratios[name], name)
        elif ratios[name] is None:
            unavailable.add(name)
        else:
            raise ValueError("unavailable ratio must be null")
    payload = _cdr(row)
    if previous is None:
        if row["journal_sequence"] != 1:
            raise ValueError("status journal must start at one")
    else:
        for name in ("run_id", "publisher_gid_hex", "rmw_implementation"):
            if row[name] != previous[name]:
                raise ValueError("status source identity changed")
        if resets != previous["reset_counters"]:
            raise ValueError("PX4 status reset needs a new bound session")
        for name in ("journal_sequence", "callback_steady_ns", "px4_publication_us", "px4_sample_us"):
            if row[name] <= previous[name]:
                raise ValueError(f"{name} regressed or duplicated")
        if row["journal_sequence"] != previous["journal_sequence"] + 1:
            raise ValueError("status journal sequence gap")
        if row["px4_sample_us"] - previous["px4_sample_us"] > MAX_SAMPLE_GAP_US:
            raise ValueError("PX4 status sample discontinuity")
        for name in ("rmw_source_timestamp_ns", "rmw_received_timestamp_ns"):
            if row[name] and previous[name] and row[name] <= previous[name]:
                raise ValueError(f"{name} regressed")
        for name in ("rmw_publication_sequence", "rmw_reception_sequence"):
            if ((row[name] is None) != (previous[name] is None)
                    or row[name] is not None and row[name] <= previous[name]):
                raise ValueError(f"{name} changed support or regressed")
    return payload, unavailable


def _fault(row, expected_run_id):
    if set(row) != FAULT_KEYS or row["schema"] != SCHEMA or row["kind"] != "fault":
        raise ValueError("status fault schema invalid")
    run_id, reason = row["run_id"], row["reason"]
    if (type(run_id) is not str or RUN.fullmatch(run_id) is None
            or expected_run_id is not None and run_id != expected_run_id
            or type(reason) is not str or REASON.fullmatch(reason) is None):
        raise ValueError("status fault identity invalid")
    length = _integer(row["cdr_length"], "fault CDR length", maximum=2**32 - 1)
    if reason == "cdr_oversize":
        if (length <= MAX_CDR or row["cdr_hex"] != ""
                or type(row["cdr_sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", row["cdr_sha256"]) is None):
            raise ValueError("oversized status CDR fault invalid")
    elif length == 0 or length > MAX_CDR or len(_cdr(row)) != length:
        raise ValueError("status fault CDR invalid")
    return reason


def audit_status_source_journal(path: str | Path) -> StatusSourceJournalAudit:
    """Validate bounded JSONL only; CDR parity and PX4 provenance remain unverified."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("status journal must be a regular file")
    before = path.stat()
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    digest = hashlib.sha256()
    previous = None
    first_cdr = b""
    terminal = None
    fault_reason = fault_run_id = None
    count = 0
    gap = False
    unavailable = set()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
            raise ValueError("status journal changed before audit")
        while line := stream.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE or not line.endswith(b"\n"):
                raise ValueError("status journal line truncated or oversized")
            digest.update(line)
            try:
                row = json.loads(line, object_pairs_hook=_unique,
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("status journal JSON invalid") from exc
            if type(row) is not dict or terminal is not None or row.get("schema") != SCHEMA:
                raise ValueError("status journal row invalid or after terminal")
            if row.get("kind") == "sample":
                if fault_reason is not None or count >= MAX_SAMPLES:
                    raise ValueError("status sample after fault or over limit")
                payload, missing = _sample(row, previous)
                if count == 0:
                    first_cdr = payload
                elif row["rmw_publication_sequence"] is not None:
                    gap |= row["rmw_publication_sequence"] != previous["rmw_publication_sequence"] + 1
                unavailable.update(missing)
                previous = row
                count += 1
            elif row.get("kind") == "fault":
                if fault_reason is not None:
                    raise ValueError("duplicate status fault")
                fault_reason = _fault(row, None if previous is None else previous["run_id"])
                fault_run_id = row["run_id"]
            elif row.get("kind") == "finish":
                if set(row) != FINISH_KEYS or type(row["run_id"]) is not str or RUN.fullmatch(row["run_id"]) is None:
                    raise ValueError("status terminal schema or identity invalid")
                if (previous is not None and row["run_id"] != previous["run_id"]
                        or fault_run_id is not None and row["run_id"] != fault_run_id
                        or _integer(row["samples"], "terminal count") != count):
                    raise ValueError("status terminal identity or count mismatch")
                if (row["status"] == "complete" and (count == 0 or row["reason"] != "" or fault_reason)
                        or row["status"] == "failed" and
                        (type(row["reason"]) is not str or not row["reason"]
                         or fault_reason is not None and row["reason"] != fault_reason)
                        or row["status"] not in ("complete", "failed")):
                    raise ValueError("status terminal result invalid")
                terminal = row
            else:
                raise ValueError("status journal kind invalid")
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("status journal changed during audit")
    if identity(path.stat()) != identity(before) or terminal is None:
        raise ValueError("status journal changed or terminal missing")
    return StatusSourceJournalAudit(
        run_id=terminal["run_id"], samples=count, completed=terminal["status"] == "complete",
        publisher_gid_hex="" if previous is None else previous["publisher_gid_hex"],
        first_cdr=first_cdr, journal_sha256=digest.hexdigest(),
        last_publication_us=None if previous is None else previous["px4_publication_us"],
        last_sample_us=None if previous is None else previous["px4_sample_us"],
        publication_to_sample_delay_us=None if previous is None else (
            previous["px4_publication_us"] - previous["px4_sample_us"]),
        rmw_sequences_supported=previous is not None
        and previous["rmw_publication_sequence"] is not None
        and previous["rmw_reception_sequence"] is not None,
        observed_rmw_gap=gap, unavailable_innovation_ratios=frozenset(unavailable),
        faults=int(fault_reason is not None),
    )
