"""Read-only ULog topic prerequisite for a later DDS/ULog source comparison.

No result from this module authenticates an owned PX4 or admits capture data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real

_SCALARS = (
    "timestamp", "timestamp_sample", "pose_frame", "velocity_frame",
    "reset_counter", "quality",
)
_VECTORS = (
    ("position", 3), ("q", 4), ("velocity", 3),
    ("angular_velocity", 3), ("position_variance", 3),
    ("orientation_variance", 3), ("velocity_variance", 3),
)
REQUIRED_FIELDS = frozenset(_SCALARS) | frozenset(
    f"{name}[{index}]" for name, size in _VECTORS for index in range(size)
)


@dataclass(frozen=True)
class OdometryTopicAudit:
    reason: str
    samples: int
    usable_for_exact_crosscheck: bool
    eligible_for_live_capture: bool = False


def _refusal(reason: str) -> OdometryTopicAudit:
    return OdometryTopicAudit(reason, 0, False)


def audit_topic(datasets: object) -> OdometryTopicAudit:
    """Check whether one complete instance-zero VehicleOdometry dataset exists.

    This only checks ULog availability and structure. It does not compare a
    single ROS message, calibrate a clock, or establish source ownership.
    """
    matches = [item for item in datasets if getattr(item, "name", None) == "vehicle_odometry"]
    if not matches:
        return _refusal("vehicle_odometry_not_logged")
    if len(matches) != 1 or type(getattr(matches[0], "multi_id", None)) is not int or matches[0].multi_id != 0:
        return _refusal("odometry_instance_ambiguous")
    columns = matches[0].data
    if not isinstance(columns, dict) or not REQUIRED_FIELDS <= columns.keys():
        return _refusal("odometry_fields_missing")
    try:
        count = len(columns["timestamp"])
        if count == 0 or any(len(columns[name]) != count for name in REQUIRED_FIELDS):
            return _refusal("odometry_column_length")
        publication = columns["timestamp"]
        sample = columns["timestamp_sample"]
        if any(
            not isinstance(pub, Integral) or isinstance(pub, bool)
            or not isinstance(stamp, Integral) or isinstance(stamp, bool)
            or not 0 < stamp <= pub
            or index > 0 and (pub <= publication[index - 1]
                              or stamp <= sample[index - 1])
            for index, (pub, stamp) in enumerate(zip(publication, sample, strict=True))
        ):
            return _refusal("odometry_time_order")
        for name in ("pose_frame", "velocity_frame", "reset_counter", "quality"):
            limits = {"pose_frame": (0, 2), "velocity_frame": (0, 3),
                      "reset_counter": (0, 255), "quality": (-128, 127)}[name]
            if any(not isinstance(value, Integral) or isinstance(value, bool)
                   or not limits[0] <= value <= limits[1]
                   for value in columns[name]):
                return _refusal("odometry_value_type")
        for name, size in _VECTORS:
            for index in range(size):
                for value in columns[f"{name}[{index}]"]:
                    if (not isinstance(value, Real) or isinstance(value, bool)
                            or "variance" in name and math.isfinite(value) and value < 0):
                        return _refusal("odometry_value_type")
    except (TypeError, ValueError, OverflowError):
        return _refusal("odometry_column_length")
    return OdometryTopicAudit("topic_schema_present_only", count, True)
