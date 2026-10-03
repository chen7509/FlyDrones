"""Read-only, non-future alignment of RGB frames to saved PX4 ULog estimates."""

from __future__ import annotations

from collections import Counter

import numpy as np

_FAST_MAX_AGE_NS = 100_000_000
_SOURCE_MAX_AGE_NS = 2_000_000_000
_REQUIRED = {
    "vehicle_local_position": (
        "timestamp", "x", "y", "z", "vx", "vy", "vz", "xy_valid",
        "z_valid", "v_xy_valid", "v_z_valid", "heading_good_for_control",
        "dead_reckoning",
    ),
    "vehicle_attitude": ("timestamp", "q[0]", "q[1]", "q[2]", "q[3]"),
    "estimator_status": ("timestamp", "filter_fault_flags"),
    "estimator_status_flags": ("timestamp", "cs_gnss_pos", "cs_ev_pos"),
}
_TIME_NAMES = {
    "vehicle_local_position": "local_position",
    "vehicle_attitude": "attitude",
    "estimator_status": "estimator_status",
    "estimator_status_flags": "source_flags",
}


def _validated_topics(topics: dict) -> dict[str, tuple[dict, np.ndarray]]:
    if not isinstance(topics, dict):
        raise ValueError("topics must be a mapping")
    result = {}
    for name, fields in _REQUIRED.items():
        data = topics.get(name)
        if not isinstance(data, dict) or any(field not in data for field in fields):
            raise ValueError(f"{name} required fields missing")
        times = np.asarray(data["timestamp"])
        if (times.ndim != 1 or not np.issubdtype(times.dtype, np.integer)
                or np.any(times < 0) or np.any(times > np.iinfo(np.int64).max // 1000)
                or np.any(np.diff(times.astype(np.int64)) <= 0)):
            raise ValueError(f"{name} timestamps invalid")
        for field in fields:
            values = np.asarray(data[field])
            if values.shape != times.shape:
                raise ValueError(f"{name} field length mismatch")
            if field != "timestamp" and not (
                    np.issubdtype(values.dtype, np.integer)
                    or np.issubdtype(values.dtype, np.floating)
                    or np.issubdtype(values.dtype, np.bool_)):
                raise ValueError(f"{name} {field} must be real numeric")
        result[name] = data, times.astype(np.int64) * 1000
    return result


def _sample(data: dict, times_ns: np.ndarray, frame_ns: int, *, max_age_ns: int,
            name: str, reasons: list[str], record: dict) -> int | None:
    index = int(np.searchsorted(times_ns, frame_ns, side="right")) - 1
    if index < 0:
        reasons.append(f"{name}_missing")
        record[f"{name}_timestamp_us"] = None
        record[f"{name}_age_ns"] = None
        return None
    age_ns = frame_ns - int(times_ns[index])
    record[f"{name}_timestamp_us"] = int(data["timestamp"][index])
    record[f"{name}_age_ns"] = age_ns
    if age_ns > max_age_ns:
        reasons.append(f"{name}_stale")
    return index


def _finite_three(data: dict, index: int, names: tuple[str, str, str]) -> list[float] | None:
    try:
        values = [float(data[name][index]) for name in names]
    except (TypeError, ValueError, OverflowError):
        return None
    return values if np.all(np.isfinite(values)) else None


def audit_shadow_frames(frame_ns: list[int], topics: dict[str, dict[str, np.ndarray]]) -> dict:
    """Audit every original frame; never consume a later PX4 state.

    The ULog and Gazebo frame timestamp epoch is an uncalibrated simulation
    assumption. This report cannot authorize live student capture.
    """
    if (not isinstance(frame_ns, list) or not frame_ns
            or any(type(value) is not int or value < 0 for value in frame_ns)
            or any(after <= before for before, after in zip(frame_ns, frame_ns[1:]))):
        raise ValueError("frame timestamps must be nonnegative and strictly increasing")
    verified = _validated_topics(topics)
    records = []
    counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for frame in frame_ns:
        reasons: list[str] = []
        record: dict = {"frame_ns": frame, "source": "unknown"}
        indices = {}
        for topic, (data, times) in verified.items():
            name = _TIME_NAMES[topic]
            indices[topic] = _sample(
                data, times, frame,
                max_age_ns=(_SOURCE_MAX_AGE_NS if topic == "estimator_status_flags"
                            else _FAST_MAX_AGE_NS),
                name=name, reasons=reasons, record=record,
            )

        local_index = indices["vehicle_local_position"]
        if local_index is not None:
            local = verified["vehicle_local_position"][0]
            for field, reason in (
                    ("xy_valid", "xy_invalid"), ("z_valid", "z_invalid"),
                    ("v_xy_valid", "horizontal_velocity_invalid"),
                    ("v_z_valid", "vertical_velocity_invalid"),
                    ("heading_good_for_control", "heading_invalid")):
                if local[field][local_index] != 1:
                    reasons.append(reason)
            if local["dead_reckoning"][local_index] != 0:
                reasons.append("dead_reckoning")
            position = _finite_three(local, local_index, ("x", "y", "z"))
            velocity = _finite_three(local, local_index, ("vx", "vy", "vz"))
            if position is None or velocity is None:
                reasons.append("nonfinite_local_position")
            else:
                record["position_ned_m"] = position
                record["velocity_ned_mps"] = velocity
                record["position_enu_m"] = [position[1], position[0], -position[2]]
                record["velocity_enu_mps"] = [velocity[1], velocity[0], -velocity[2]]

        attitude_index = indices["vehicle_attitude"]
        if attitude_index is not None:
            attitude = verified["vehicle_attitude"][0]
            quaternion = np.asarray([
                attitude[f"q[{axis}]"][attitude_index] for axis in range(4)
            ])
            try:
                norm = float(np.linalg.norm(quaternion.astype(float)))
            except (TypeError, ValueError, OverflowError):
                norm = float("nan")
            if not np.isfinite(norm) or not .95 <= norm <= 1.05:
                reasons.append("invalid_attitude_quaternion")

        status_index = indices["estimator_status"]
        if status_index is not None:
            status = verified["estimator_status"][0]
            if status["filter_fault_flags"][status_index] != 0:
                reasons.append("filter_fault")

        flags_index = indices["estimator_status_flags"]
        if flags_index is not None and "source_flags_stale" not in reasons:
            flags = verified["estimator_status_flags"][0]
            gnss = flags["cs_gnss_pos"][flags_index] == 1
            vision = flags["cs_ev_pos"][flags_index] == 1
            record["source"] = ("mixed" if gnss and vision else
                                "gnss" if gnss else
                                "external_vision" if vision else "none")

        record["reasons"] = sorted(set(reasons))
        record["status"] = ("missing" if any(reason.endswith("_missing") for reason in reasons)
                            else "invalid" if reasons else "valid")
        records.append(record)
        counts[record["status"]] += 1
        reason_counts.update(record["reasons"])
        source_counts[record["source"]] += 1
    coverage = {
        name: {"samples": len(times),
               "first_timestamp_us": (int(times[0] // 1000) if len(times) else None),
               "last_timestamp_us": (int(times[-1] // 1000) if len(times) else None)}
        for name, (_, times) in verified.items()
    }
    return {
        "schema": "flydrones-ekf2-ulog-shadow-v1",
        "frame_count": len(frame_ns),
        "records": records,
        "counts": {name: counts[name] for name in ("valid", "invalid", "missing")},
        "reason_counts": dict(sorted(reason_counts.items())),
        "source_counts_all_frames": dict(sorted(source_counts.items())),
        "topic_coverage": coverage,
        "thresholds_ns": {"estimate": _FAST_MAX_AGE_NS, "source_flags": _SOURCE_MAX_AGE_NS},
        "time_epoch_assumption": "Gazebo frame_ns and PX4 ULog timestamp share simulated epoch; uncalibrated",
        "eligible_for_live_capture": False,
    }
