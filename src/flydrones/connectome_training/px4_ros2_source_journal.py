"""Audit a read-only ROS 2 PX4 odometry CDR journal; never grant capture.

The journal can prove local byte and callback continuity. Publisher GID and
caller-supplied run labels do not authenticate an owned PX4/Agent process.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "flydrones.px4_ros2_odometry_cdr.v1"
TOPIC = "/fmu/out/vehicle_odometry"
ROS_TYPE = "px4_msgs/msg/VehicleOdometry"
TYPE_BLOB = "cf117ff82cdbf191bf576db91db900b7ce34f6a7"
_HEX = re.compile(r"[0-9a-f]+\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_RMW = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_MAX_LINE = 32_768
_MAX_CDR = 4096
_MAX_EVENTS = 8192
_MAX_NS = 2**63 - 1
_MAX_US = _MAX_NS // 1000


@dataclass(frozen=True)
class SourceJournalAudit:
    run_id: str
    samples: int
    completed: bool
    publisher_gid_hex: str
    first_cdr: bytes
    journal_sha256: str
    rmw_sequences_supported: bool
    observed_sequence_gap: bool
    faults: int
    eligible_for_live_capture: bool = False
    missing_qualification: tuple[str, ...] = (
        "cdr_decode_parity_not_verified",
        "rosidl_type_support_not_verified",
        "writer_exit_and_durability_not_verified",
        "publisher_process_not_authenticated",
        "owned_agent_not_verified",
        "px4_clock_epoch_not_verified",
        "camera_calibration_not_verified",
        "ekf2_health_not_verified",
        "ego_teacher_not_verified",
    )


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate journal key: {key}")
        result[key] = value
    return result


def _integer(value: object, name: str, *, maximum: int = _MAX_NS,
             minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _sequence(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name, maximum=2**64 - 2)


def _sample(row: dict, previous: dict | None) -> bytes:
    required = {
        "schema", "kind", "topic", "ros_type", "message_blob_sha", "run_id",
        "journal_sequence", "rmw_implementation", "publisher_gid_hex",
        "rmw_source_timestamp_ns", "rmw_received_timestamp_ns",
        "rmw_publication_sequence", "rmw_reception_sequence",
        "callback_steady_ns", "px4_publication_us", "px4_sample_us",
        "pose_frame", "velocity_frame", "reset_counter", "quality",
        "cdr_hex", "cdr_sha256",
    }
    if set(row) != required or row["schema"] != SCHEMA or row["kind"] != "sample":
        raise ValueError("journal sample schema mismatch")
    if row["topic"] != TOPIC or row["ros_type"] != ROS_TYPE or row["message_blob_sha"] != TYPE_BLOB:
        raise ValueError("PX4 topic, type or blob mismatch")
    if type(row["run_id"]) is not str or _RUN.fullmatch(row["run_id"]) is None:
        raise ValueError("run identity invalid")
    if (type(row["rmw_implementation"]) is not str
            or _RMW.fullmatch(row["rmw_implementation"]) is None):
        raise ValueError("RMW implementation invalid")
    gid = row["publisher_gid_hex"]
    if type(gid) is not str or len(gid) != 48 or _HEX.fullmatch(gid) is None or gid == "0" * 48:
        raise ValueError("RMW publisher GID invalid")
    _integer(row["journal_sequence"], "journal sequence", minimum=1)
    _integer(row["rmw_source_timestamp_ns"], "RMW source timestamp")
    _integer(row["rmw_received_timestamp_ns"], "RMW received timestamp")
    _sequence(row["rmw_publication_sequence"], "RMW publication sequence")
    _sequence(row["rmw_reception_sequence"], "RMW reception sequence")
    _integer(row["callback_steady_ns"], "callback receipt", minimum=1)
    _integer(row["px4_publication_us"], "PX4 publication", maximum=_MAX_US, minimum=1)
    _integer(row["px4_sample_us"], "PX4 sample", maximum=_MAX_US, minimum=1)
    if row["px4_sample_us"] > row["px4_publication_us"]:
        raise ValueError("PX4 sample after publication")
    if (type(row["pose_frame"]) is not int or row["pose_frame"] != 1
            or type(row["velocity_frame"]) is not int or row["velocity_frame"] != 1):
        raise ValueError("PX4 odometry frame unsupported")
    _integer(row["reset_counter"], "PX4 reset counter", maximum=255)
    if type(row["quality"]) is not int or row["quality"] != 0:
        raise ValueError("fixed PX4 quality field unexpected")
    cdr_hex = row["cdr_hex"]
    digest = row["cdr_sha256"]
    if (type(cdr_hex) is not str or not 8 <= len(cdr_hex) <= 2 * _MAX_CDR
            or len(cdr_hex) % 2 or _HEX.fullmatch(cdr_hex) is None
            or type(digest) is not str or len(digest) != 64
            or _HEX.fullmatch(digest) is None):
        raise ValueError("serialized CDR or digest invalid")
    cdr = bytes.fromhex(cdr_hex)
    if hashlib.sha256(cdr).hexdigest() != digest:
        raise ValueError("serialized CDR digest mismatch")
    if previous is not None:
        if (row["run_id"], gid, row["rmw_implementation"]) != (
            previous["run_id"], previous["publisher_gid_hex"],
            previous["rmw_implementation"],
        ):
            raise ValueError("RMW source identity changed")
        if row["reset_counter"] != previous["reset_counter"]:
            raise ValueError("PX4 coordinate reset unresolved")
        for key in ("journal_sequence", "callback_steady_ns", "px4_publication_us",
                    "px4_sample_us"):
            if row[key] <= previous[key]:
                raise ValueError(f"{key} regressed or duplicated")
        if row["journal_sequence"] != previous["journal_sequence"] + 1:
            raise ValueError("journal sequence gap")
        if row["px4_sample_us"] - previous["px4_sample_us"] > 100_000:
            raise ValueError("PX4 sample gap")
        for key in ("rmw_source_timestamp_ns", "rmw_received_timestamp_ns"):
            if previous[key] and row[key] and row[key] <= previous[key]:
                raise ValueError(f"{key} regressed")
        for key in ("rmw_publication_sequence", "rmw_reception_sequence"):
            if ((row[key] is None) != (previous[key] is None)
                    or (row[key] is not None and row[key] <= previous[key])):
                raise ValueError(f"{key} changed support or regressed")
    elif row["journal_sequence"] != 1:
        raise ValueError("journal must begin at sequence one")
    return cdr


def audit_source_journal(path: str | Path) -> SourceJournalAudit:
    """Validate a complete or explicitly failed journal without source grants."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("journal must be a regular file")
    before = path.stat()
    digest = hashlib.sha256()
    previous = None
    first_cdr = b""
    count = 0
    gap = False
    terminal = None
    fault_reason = None
    fault_run_id = None
    with path.open("rb") as stream:
        while line := stream.readline(_MAX_LINE + 1):
            if len(line) > _MAX_LINE or not line.endswith(b"\n"):
                raise ValueError("journal line truncated or oversized")
            digest.update(line)
            try:
                row = json.loads(line, object_pairs_hook=_pairs_without_duplicates,
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("journal JSON invalid") from exc
            if type(row) is not dict or terminal is not None:
                raise ValueError("journal row after terminal or malformed")
            if row.get("kind") == "sample":
                if fault_reason is not None:
                    raise ValueError("sample after source fault")
                if count >= _MAX_EVENTS:
                    raise ValueError("journal event limit exceeded")
                cdr = _sample(row, previous)
                if count == 0:
                    first_cdr = cdr
                if previous is not None and row["rmw_publication_sequence"] is not None:
                    gap |= (row["rmw_publication_sequence"]
                            != previous["rmw_publication_sequence"] + 1)
                previous = row
                count += 1
            elif row.get("kind") == "fault":
                if fault_reason is not None or set(row) != {
                    "schema", "kind", "run_id", "reason", "cdr_length",
                    "cdr_hex", "cdr_sha256",
                }:
                    raise ValueError("source fault schema or order invalid")
                if (row["schema"] != SCHEMA or type(row["run_id"]) is not str
                        or _RUN.fullmatch(row["run_id"]) is None
                        or previous is not None and row["run_id"] != previous["run_id"]
                        or type(row["reason"]) is not str
                        or re.fullmatch(r"[a-z_]{1,64}", row["reason"]) is None):
                    raise ValueError("source fault identity invalid")
                cdr_hex, cdr_hash = row["cdr_hex"], row["cdr_sha256"]
                cdr_length = _integer(row["cdr_length"], "fault CDR length",
                                      maximum=2**32 - 1)
                if (type(cdr_hex) is not str or type(cdr_hash) is not str
                        or len(cdr_hash) != 64 or _HEX.fullmatch(cdr_hash) is None):
                    raise ValueError("source fault CDR invalid")
                if row["reason"] == "cdr_oversize":
                    if cdr_length <= _MAX_CDR or cdr_hex != "":
                        raise ValueError("oversized source fault invalid")
                elif (not 0 < cdr_length <= _MAX_CDR
                      or len(cdr_hex) != 2 * cdr_length
                      or _HEX.fullmatch(cdr_hex) is None
                      or hashlib.sha256(bytes.fromhex(cdr_hex)).hexdigest() != cdr_hash):
                    raise ValueError("source fault CDR invalid")
                fault_reason = row["reason"]
                fault_run_id = row["run_id"]
            elif row.get("kind") == "finish":
                if set(row) != {"schema", "kind", "run_id", "samples", "status", "reason"}:
                    raise ValueError("journal terminal schema mismatch")
                if (row["schema"] != SCHEMA or type(row["run_id"]) is not str
                        or _RUN.fullmatch(row["run_id"]) is None
                        or previous is not None and row["run_id"] != previous["run_id"]
                        or fault_run_id is not None and row["run_id"] != fault_run_id):
                    raise ValueError("journal terminal identity mismatch")
                if (fault_reason is not None and
                        (row["status"] != "failed" or row["reason"] != fault_reason)):
                    raise ValueError("journal source fault terminal mismatch")
                if _integer(row["samples"], "terminal count") != count:
                    raise ValueError("journal terminal count mismatch")
                if (row["status"] == "complete" and row["reason"] != ""
                        or row["status"] == "failed" and
                        (type(row["reason"]) is not str or not row["reason"])
                        or row["status"] == "complete" and count == 0
                        or row["status"] not in ("complete", "failed")):
                    raise ValueError("journal terminal status invalid")
                terminal = row
            else:
                raise ValueError("journal row kind invalid")
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("journal changed during audit")
    if terminal is None:
        raise ValueError("journal terminal missing")
    return SourceJournalAudit(
        run_id=terminal["run_id"], samples=count,
        completed=terminal["status"] == "complete",
        publisher_gid_hex="" if previous is None else previous["publisher_gid_hex"],
        first_cdr=first_cdr, journal_sha256=digest.hexdigest(),
        rmw_sequences_supported=previous is not None
        and previous["rmw_publication_sequence"] is not None
        and previous["rmw_reception_sequence"] is not None,
        observed_sequence_gap=gap,
        faults=int(fault_reason is not None),
    )
