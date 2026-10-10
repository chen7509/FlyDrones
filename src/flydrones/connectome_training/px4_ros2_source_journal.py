"""Audit a read-only ROS 2 PX4 odometry CDR journal; never grant capture.

The journal can prove local byte and callback continuity. Publisher GID and
caller-supplied run labels do not authenticate an owned PX4/Agent process.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "flydrones.px4_ros2_odometry_cdr.v1"
SCHEMA_V2 = "flydrones.px4_ros2_odometry_cdr.v2"
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
_MAX_FLOAT32 = 3.4028234663852886e38
_GEOMETRY = {
    "position_ned_m": 3,
    "q_body_to_ned_wxyz": 4,
    "velocity_ned_m_s": 3,
    "omega_body_frd_rad_s": 3,
    "position_variance_m2": 3,
    "orientation_variance_rad2": 3,
    "velocity_variance_m2_s2": 3,
}


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
    schema: str = SCHEMA
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


@dataclass(frozen=True)
class OfflineOdometryGeometry:
    """Decoded row projection only; neither CDR parity nor owned source is proven."""

    run_id: str
    journal_sequence: int
    journal_sha256: str
    publisher_gid_hex: str
    rmw_implementation: str
    rmw_source_timestamp_ns: int
    rmw_received_timestamp_ns: int
    rmw_publication_sequence: int | None
    rmw_reception_sequence: int | None
    sample_us: int
    publication_us: int
    receipt_monotonic_ns: int
    pose_frame: int
    velocity_frame: int
    position_ned_m: tuple[float, float, float]
    q_body_to_ned_wxyz: tuple[float, float, float, float]
    velocity_ned_m_s: tuple[float, float, float]
    omega_body_frd_rad_s: tuple[float, float, float]
    position_variance_m2: tuple[float, float, float]
    orientation_variance_rad2: tuple[float, float, float]
    velocity_variance_m2_s2: tuple[float, float, float]
    reset_counter: int
    quality: int
    cdr_sha256: str
    eligible_for_live_capture: bool = False


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


def _geometry_vector(row: dict, name: str, size: int) -> tuple[float | None, ...]:
    value = row[name]
    if type(value) is not list or len(value) != size:
        raise ValueError(f"invalid geometry {name}")
    result = []
    for item in value:
        if item is None:
            result.append(None)
        elif (type(item) not in (int, float) or abs(item) > _MAX_FLOAT32
              or not math.isfinite(item)
              or ("variance" in name and item < 0)):
            raise ValueError(f"invalid geometry {name}")
        else:
            result.append(float(item))
    return tuple(result)


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
    schema = row.get("schema")
    if schema not in (SCHEMA, SCHEMA_V2):
        raise ValueError("journal sample schema mismatch")
    if schema == SCHEMA_V2:
        required |= _GEOMETRY.keys()
    if set(row) != required or row["kind"] != "sample":
        raise ValueError("journal sample schema mismatch")
    if schema == SCHEMA_V2:
        for name, size in _GEOMETRY.items():
            _geometry_vector(row, name, size)
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
        if row["schema"] != previous["schema"]:
            raise ValueError("journal sample schema changed")
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
    selected_schema = None
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
            if row.get("schema") not in (SCHEMA, SCHEMA_V2):
                raise ValueError("journal schema invalid")
            if selected_schema is None:
                selected_schema = row["schema"]
            elif row["schema"] != selected_schema:
                raise ValueError("journal schema changed")
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
                if (type(row["run_id"]) is not str
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
                if (type(row["run_id"]) is not str
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
        schema=terminal["schema"],
    )


def read_offline_odometry_geometry(path: str | Path) -> tuple[OfflineOdometryGeometry, ...]:
    """Extract complete v2 geometry for analysis, never for live capture."""
    path = Path(path)
    before = path.stat()
    audit = audit_source_journal(path)
    if audit.schema != SCHEMA_V2 or not audit.completed:
        raise ValueError("complete v2 journal required for offline geometry")
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(path.stat()) != identity(before):
        raise ValueError("journal changed between audit and geometry extraction")
    digest = hashlib.sha256()
    events = []
    rows = 0
    with path.open("rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("journal changed between audit and geometry extraction")
        while line := stream.readline(_MAX_LINE + 1):
            rows += 1
            if len(line) > _MAX_LINE or not line.endswith(b"\n"):
                raise ValueError("journal line truncated or oversized")
            if rows > audit.samples + 1:
                raise ValueError("journal changed between audit and geometry extraction")
            digest.update(line)
            row = json.loads(line, object_pairs_hook=_pairs_without_duplicates)
            if row["kind"] != "sample":
                continue
            vectors = {name: _geometry_vector(row, name, size)
                       for name, size in _GEOMETRY.items()}
            if any(value is None for vector in vectors.values() for value in vector):
                raise ValueError("invalid geometry for offline event")
            q = vectors["q_body_to_ned_wxyz"]
            if not .95 <= math.sqrt(sum(value * value for value in q)) <= 1.05:
                raise ValueError("invalid geometry quaternion norm")
            events.append(OfflineOdometryGeometry(
                run_id=row["run_id"], journal_sequence=row["journal_sequence"],
                journal_sha256=audit.journal_sha256,
                publisher_gid_hex=row["publisher_gid_hex"],
                rmw_implementation=row["rmw_implementation"],
                rmw_source_timestamp_ns=row["rmw_source_timestamp_ns"],
                rmw_received_timestamp_ns=row["rmw_received_timestamp_ns"],
                rmw_publication_sequence=row["rmw_publication_sequence"],
                rmw_reception_sequence=row["rmw_reception_sequence"],
                sample_us=row["px4_sample_us"], publication_us=row["px4_publication_us"],
                receipt_monotonic_ns=row["callback_steady_ns"],
                pose_frame=row["pose_frame"], velocity_frame=row["velocity_frame"],
                **vectors, reset_counter=row["reset_counter"], quality=row["quality"],
                cdr_sha256=row["cdr_sha256"],
            ))
    if (identity(path.stat()) != identity(before)
            or digest.hexdigest() != audit.journal_sha256
            or len(events) != audit.samples):
        raise ValueError("journal changed between audit and geometry extraction")
    return tuple(events)


def offline_geometry_to_event(
    value: OfflineOdometryGeometry, *, provisional_session_id: str,
    provisional_instance: int,
):
    """Adapt fixed geometry offline; the returned event has no source authority."""
    from .px4_odometry_adapter import VehicleOdometryEvent, _event

    if (type(value) is not OfflineOdometryGeometry
            or type(provisional_session_id) is not str
            or _RUN.fullmatch(provisional_session_id) is None):
        raise ValueError("offline geometry or provisional session invalid")
    _integer(provisional_instance, "provisional PX4 instance", maximum=255)
    return _event(VehicleOdometryEvent(
        topic=TOPIC, session_id=provisional_session_id,
        instance=provisional_instance, sample_us=value.sample_us,
        publication_us=value.publication_us,
        receipt_monotonic_ns=value.receipt_monotonic_ns,
        pose_frame=value.pose_frame, velocity_frame=value.velocity_frame,
        position_ned_m=value.position_ned_m,
        q_body_to_ned_wxyz=value.q_body_to_ned_wxyz,
        velocity_ned_m_s=value.velocity_ned_m_s,
        omega_body_frd_rad_s=value.omega_body_frd_rad_s,
        position_variance_m2=value.position_variance_m2,
        orientation_variance_rad2=value.orientation_variance_rad2,
        velocity_variance_m2_s2=value.velocity_variance_m2_s2,
        reset_counter=value.reset_counter, quality=value.quality,
    ))
