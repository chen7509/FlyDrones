"""Read-only same-message PX4 ULog/ROS journal comparison without source grants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np

from .px4_ros2_source_journal import OfflineOdometryGeometry
from .px4_ulog_odometry_preflight import audit_topic

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ARRAYS = {
    "position": "position_ned_m", "q": "q_body_to_ned_wxyz",
    "velocity": "velocity_ned_m_s", "angular_velocity": "omega_body_frd_rad_s",
    "position_variance": "position_variance_m2",
    "orientation_variance": "orientation_variance_rad2",
    "velocity_variance": "velocity_variance_m2_s2",
}
_SCALARS = ("pose_frame", "velocity_frame", "reset_counter", "quality")
_SIZES = {"position_ned_m": 3, "q_body_to_ned_wxyz": 4,
          "velocity_ned_m_s": 3, "omega_body_frd_rad_s": 3,
          "position_variance_m2": 3, "orientation_variance_rad2": 3,
          "velocity_variance_m2_s2": 3}
_MAX_US = (2**63 - 1) // 1000


@dataclass(frozen=True)
class OdometryCrosscheckAudit:
    reason: str
    journal_samples: int
    ulog_samples: int
    matched_samples: int
    unmatched_ulog_samples: int
    matching_samples_only: bool
    source_authenticated: bool = False
    capture_eligible: bool = False
    training_eligible: bool = False


def _outcome(reason: str, journal: int, ulog: int, matched: int) -> OdometryCrosscheckAudit:
    return OdometryCrosscheckAudit(
        reason, journal, ulog, matched, max(0, ulog - matched),
        reason == "matching_samples_only",
    )


def _float32_bits(value: object) -> int | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            number = np.float32(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(number):
        return None
    return int(np.asarray([number], dtype=np.float32).view(np.uint32)[0])


def _journal_reason(rows: tuple[OfflineOdometryGeometry, ...]) -> str | None:
    if type(rows) is not tuple or len(rows) < 2 or len(rows) > 8192:
        return "journal_count_invalid"
    first = rows[0]
    if (type(first) is not OfflineOdometryGeometry
            or type(first.journal_sha256) is not str
            or _SHA.fullmatch(first.journal_sha256) is None
            or type(first.cdr_sha256) is not str
            or _SHA.fullmatch(first.cdr_sha256) is None
            or type(first.run_id) is not str or not first.run_id
            or type(first.publisher_gid_hex) is not str
            or re.fullmatch(r"[0-9a-f]{48}", first.publisher_gid_hex) is None
            or type(first.rmw_implementation) is not str
            or not first.rmw_implementation):
        return "journal_identity_invalid"
    previous = None
    for sequence, row in enumerate(rows, 1):
        if (type(row) is not OfflineOdometryGeometry
                or row.eligible_for_live_capture is not False
                or type(row.run_id) is not str
                or type(row.journal_sha256) is not str
                or type(row.publisher_gid_hex) is not str
                or type(row.rmw_implementation) is not str
                or type(row.cdr_sha256) is not str
                or _SHA.fullmatch(row.cdr_sha256) is None
                or (row.run_id, row.journal_sha256, row.publisher_gid_hex,
                    row.rmw_implementation) != (
                    first.run_id, first.journal_sha256, first.publisher_gid_hex,
                    first.rmw_implementation)
                or type(row.journal_sequence) is not int or row.journal_sequence != sequence):
            return "journal_identity_invalid"
        if (type(row.sample_us) is not int or type(row.publication_us) is not int
                or not 0 < row.sample_us <= row.publication_us <= _MAX_US
                or type(row.receipt_monotonic_ns) is not int
                or row.receipt_monotonic_ns <= 0
                or type(row.pose_frame) is not int or row.pose_frame != 1
                or type(row.velocity_frame) is not int or row.velocity_frame != 1
                or type(row.reset_counter) is not int or not 0 <= row.reset_counter <= 255
                or type(row.quality) is not int or row.quality != 0
                or any(type(getattr(row, name)) is not tuple
                       or len(getattr(row, name)) != size
                       or any(_float32_bits(value) is None for value in getattr(row, name))
                       for name, size in _SIZES.items())):
            return "journal_values_invalid"
        if previous is not None:
            if row.reset_counter != previous.reset_counter:
                return "journal_reset_changed"
            if (row.sample_us <= previous.sample_us
                    or row.publication_us <= previous.publication_us
                    or row.receipt_monotonic_ns <= previous.receipt_monotonic_ns):
                return "journal_time_regressed"
        previous = row
    return None


def compare_odometry_to_ulog(
    journal: tuple[OfflineOdometryGeometry, ...], datasets: list,
) -> OdometryCrosscheckAudit:
    """Compare same timestamped fields; never attest runtime ownership or capture."""
    if type(datasets) is not list or len(datasets) > 10_000:
        return _outcome("ulog_datasets_invalid", len(journal) if type(journal) is tuple else 0, 0, 0)
    try:
        topic = audit_topic(datasets)
    except (TypeError, ValueError, OverflowError):
        return _outcome("ulog_datasets_invalid", len(journal) if type(journal) is tuple else 0, 0, 0)
    if not topic.usable_for_exact_crosscheck:
        return _outcome(topic.reason, len(journal) if type(journal) is tuple else 0, topic.samples, 0)
    reason = _journal_reason(journal)
    if reason is not None:
        return _outcome(reason, len(journal) if type(journal) is tuple else 0, topic.samples, 0)
    columns = next(item.data for item in datasets if getattr(item, "name", None) == "vehicle_odometry")
    index = {(int(sample), int(publication)): position for position, (sample, publication)
             in enumerate(zip(columns["timestamp_sample"], columns["timestamp"], strict=True))}
    if len(index) != topic.samples:
        return _outcome("ulog_time_ambiguous", len(journal), topic.samples, 0)
    matched = 0
    for row in journal:
        position = index.get((row.sample_us, row.publication_us))
        if position is None:
            return _outcome("missing_logged_sample", len(journal), topic.samples, matched)
        for field in _SCALARS:
            value = columns[field][position]
            if (not isinstance(value, Integral) or isinstance(value, bool)
                    or int(value) != getattr(row, field)):
                return _outcome(f"field_mismatch:{field}", len(journal), topic.samples, matched)
        for name, attribute in _ARRAYS.items():
            values = getattr(row, attribute)
            for axis, expected in enumerate(values):
                field = f"{name}[{axis}]"
                actual_bits = _float32_bits(columns[field][position])
                expected_bits = _float32_bits(expected)
                if actual_bits is None or expected_bits is None:
                    return _outcome(f"invalid_float:{field}", len(journal), topic.samples, matched)
                if actual_bits != expected_bits:
                    return _outcome(f"field_mismatch:{field}", len(journal), topic.samples, matched)
        matched += 1
    return _outcome("matching_samples_only", len(journal), topic.samples, matched)
