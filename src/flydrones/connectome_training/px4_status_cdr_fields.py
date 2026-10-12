"""Optional independent status CDR decode, never live-source/capture authority."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from importlib.metadata import version
from io import BytesIO
from pathlib import Path

from .px4_status_source_journal import (
    MAX_LINE,
    MAX_SAMPLES,
    MESSAGE_SHA256,
    RATIOS,
    RESETS,
    ROS_TYPE,
    audit_status_source_journal,
)

ROSBAGS_VERSION = "0.11.5"
PROFILE = "px4-d6f12ad-status-cdr-fields-v1"
MAX_JOURNAL_BYTES = (MAX_SAMPLES + 2) * MAX_LINE
INTEGER_FIELDS = {
    "px4_publication_us": "timestamp", "px4_sample_us": "timestamp_sample",
    "control_mode_flags": "control_mode_flags", "filter_fault_flags": "filter_fault_flags",
    "gps_check_fail_flags": "gps_check_fail_flags", "solution_status_flags": "solution_status_flags",
}
ACCURACY_FIELDS = ("pos_horiz_accuracy", "pos_vert_accuracy")


def _typestore(definition: bytes):
    if type(definition) is not bytes or hashlib.sha256(definition).hexdigest() != MESSAGE_SHA256:
        raise ValueError("pinned status message definition changed")
    try:
        if version("rosbags") != ROSBAGS_VERSION:
            raise RuntimeError("rosbags 0.11.5 is required for status CDR field audit")
        from rosbags.typesys import Stores, get_types_from_msg, get_typestore
    except ImportError as exc:
        raise RuntimeError("rosbags 0.11.5 is required for status CDR field audit") from exc
    store = get_typestore(Stores.EMPTY)
    store.register(get_types_from_msg(definition.decode("utf-8"), ROS_TYPE))
    return store


def _audited_bytes(path: Path, expected_sha256: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("status journal must remain a regular file")
    with path.open("rb") as stream:
        data = stream.read(MAX_JOURNAL_BYTES + 1)
    if len(data) > MAX_JOURNAL_BYTES:
        raise ValueError("status journal exceeds bounded decode size")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("status journal changed between structural and CDR audit")
    return data


def _same_f32(written, decoded, name: str) -> None:
    try:
        equal = struct.pack("<f", written) == struct.pack("<f", decoded)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError(f"invalid status CDR field {name}") from exc
    if not equal:
        raise ValueError(f"status CDR field mismatch: {name}")


def _compare_fields(row: dict, decoded) -> None:
    for written, actual in INTEGER_FIELDS.items():
        if row[written] != getattr(decoded, actual):
            raise ValueError(f"status CDR field mismatch: {written}")
    for name in ACCURACY_FIELDS:
        _same_f32(row[name], getattr(decoded, name), name)
    for name in sorted(RATIOS):
        value = getattr(decoded, name)
        available = math.isfinite(value)
        if row["innovation_ratio_available"][name] is not available:
            raise ValueError(f"status CDR field availability mismatch: {name}")
        if available:
            _same_f32(row["innovation_test_ratios"][name], value, name)
        elif row["innovation_test_ratios"][name] is not None:
            raise ValueError(f"unknown status CDR field must be null: {name}")
    for name in sorted(RESETS):
        if row["reset_counters"][name] != getattr(decoded, name):
            raise ValueError(f"status CDR field mismatch: {name}")


def audit_status_cdr_fields(
    path: str | Path, message_definition: bytes, *, observed_writer_exit_code: int | None = None,
) -> dict:
    """Decode exactly the structurally audited bytes under the fixed type.

    Reading twice is bound by the first audit's SHA, never by a label or path
    alone. No identity of a PX4/Agent publisher or clock relation is granted.
    """
    store = _typestore(message_definition)
    audited = audit_status_source_journal(path, observed_writer_exit_code=observed_writer_exit_code)
    data = _audited_bytes(Path(path), audited.journal_sha256)
    records = []
    for line in BytesIO(data):
        row = json.loads(line)
        if row["kind"] != "sample":
            continue
        raw = bytes.fromhex(row["cdr_hex"])
        if raw[:4] != b"\x00\x01\x00\x00":
            raise ValueError("unobserved status CDR representation/options")
        try:
            decoded = store.deserialize_cdr(raw, ROS_TYPE)
            canonical = bytes(store.serialize_cdr(decoded, ROS_TYPE))
        except Exception as exc:
            raise ValueError("invalid status CDR") from exc
        if raw != canonical:
            raise ValueError("noncanonical status CDR bytes")
        _compare_fields(row, decoded)
        records.append({
            "journal_sequence": row["journal_sequence"], "cdr_bytes": len(raw),
            "raw_cdr_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_cdr_sha256": hashlib.sha256(canonical).hexdigest(),
        })
    if len(records) != audited.samples:
        raise ValueError("status CDR audit sample count mismatch")
    return {
        "profile": PROFILE, "run_id": audited.run_id, "samples": len(records),
        "journal_sha256": audited.journal_sha256, "message_sha256": MESSAGE_SHA256,
        "rosbags_version": ROSBAGS_VERSION, "canonical_cdr_verified": bool(records),
        "logged_fields_verified": bool(records), "sample_records": records,
        "checked_scalar_fields": sorted((*INTEGER_FIELDS, *ACCURACY_FIELDS, *RATIOS, *RESETS)),
        "writer_completed": audited.completed,
        "unavailable_ratios": sorted(audited.unavailable_innovation_ratios),
        "live_source_authenticated": False, "upstream_loss_qualified": False,
        "clock_epoch_qualified": False, "camera_calibration_qualified": False,
        "fusion_qualified": False, "training_eligible": False,
    }
