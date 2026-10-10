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


def audit_state_sample_times(frame_ns: list[int], topics: dict) -> dict:
    """Separate publication from state sample age under an unqualified epoch.

    A publication timestamp is only an earliest-availability bound, not host
    receipt evidence. This diagnostic never grants capture/flight eligibility.
    A timing discontinuity poisons subsequent samples in that topic: callers
    need a separately evidenced new session, not implicit clock recovery.
    """
    max_ns = np.iinfo(np.int64).max
    if (not isinstance(frame_ns, list) or not frame_ns
            or any(type(t) is not int or not 0 <= t <= max_ns for t in frame_ns)
            or any(b <= a for a, b in zip(frame_ns, frame_ns[1:]))):
        raise ValueError("frame timestamps must be bounded, strictly increasing integers")
    if not isinstance(topics, dict):
        raise ValueError("topics must be a mapping")
    verified = {}
    coverage = {}
    for name in ("vehicle_local_position", "vehicle_attitude"):
        data = topics.get(name)
        arrays = {}
        for field in ("timestamp", "timestamp_sample"):
            if not isinstance(data, dict) or field not in data:
                raise ValueError(f"{name} {field} missing")
            values = np.asarray(data[field])
            if (values.ndim != 1 or not np.issubdtype(values.dtype, np.integer)
                    or np.any(values < 0) or np.any(values > max_ns // 1000)):
                raise ValueError(f"{name} {field} invalid")
            arrays[field] = values.astype(np.int64) * 1000
        pub, sample = arrays["timestamp"], arrays["timestamp_sample"]
        if np.any(np.diff(pub) <= 0):
            raise ValueError(f"{name} timestamp nonincreasing")
        if pub.shape != sample.shape:
            raise ValueError(f"{name} timestamp_sample length mismatch")
        faults = {
            "sample_zero": sample == 0,
            "sample_after_publication": sample > pub,
            "sample_nonincreasing": np.r_[False, np.diff(sample) <= 0]
            if len(sample) else np.array([], dtype=bool),
        }
        bad = np.zeros(len(pub), dtype=bool)
        for mask in faults.values():
            bad |= mask
        invalid_history = np.maximum.accumulate(bad)
        verified[name] = pub, sample, faults, invalid_history
        coverage[name] = {"samples": len(pub), "fault_counts": {
            reason: int(np.count_nonzero(mask)) for reason, mask in faults.items()}}

    records = []
    false_fresh_count = 0
    usable_count = 0
    for frame in frame_ns:
        selected = {}
        reasons = []
        publication_timely = True
        sample_times = []
        for name, (pub, sample, faults, history) in verified.items():
            index = int(np.searchsorted(pub, frame, side="right")) - 1
            if index < 0:
                selected[name] = None
                publication_timely = False
                reasons.append(f"{name}_missing")
                continue
            p, s = int(pub[index]), int(sample[index])
            selected[name] = {
                "index": index, "publication_ns": p, "sample_ns": s,
                "publication_age_ns": frame - p, "sample_age_ns": frame - s,
                "publication_minus_sample_ns": p - s,
            }
            sample_times.append(s)
            if frame - p > _FAST_MAX_AGE_NS:
                publication_timely = False
                reasons.append(f"{name}_publication_stale")
            if frame - s > _FAST_MAX_AGE_NS:
                reasons.append(f"{name}_sample_stale")
            for reason, mask in faults.items():
                if mask[index]:
                    reasons.append(f"{name}_{reason}")
            if history[index]:
                reasons.append(f"{name}_sample_history_invalid")
        skew = abs(sample_times[0] - sample_times[1]) if len(sample_times) == 2 else None
        if skew is not None and skew > 50_000_000:
            reasons.append("state_sample_skew")
        usable = not reasons
        false_fresh_count += int(publication_timely and not usable)
        usable_count += int(usable)
        records.append({"frame_ns": frame, "topics": selected,
                        "publication_timely": publication_timely,
                        "sample_timing_usable": usable, "sample_skew_ns": skew,
                        "reasons": sorted(reasons)})
    return {
        "schema": "flydrones-ekf2-state-sample-time-v1", "frame_count": len(frame_ns),
        "records": records, "topic_coverage": coverage,
        "sample_timing_usable_count": usable_count,
        "publication_only_false_fresh_count": false_fresh_count,
        "thresholds_ns": {"estimate": _FAST_MAX_AGE_NS, "state_sample_skew": 50_000_000},
        "time_epoch_assumption": "Gazebo frame_ns and PX4 timestamps share simulated epoch; uncalibrated",
        "clock_epoch_qualified": False, "eligible_for_live_capture": False,
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
    healthy_source_counts: Counter[str] = Counter()
    timely_estimate_count = 0
    healthy_estimate_count = 0
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
            gnss_value = flags["cs_gnss_pos"][flags_index]
            vision_value = flags["cs_ev_pos"][flags_index]
            if gnss_value not in (0, 1) or vision_value not in (0, 1):
                reasons.append("source_flag_invalid")
            else:
                gnss = gnss_value == 1
                vision = vision_value == 1
                record["source"] = ("mixed" if gnss and vision else
                                    "gnss" if gnss else
                                    "external_vision" if vision else "none")

        record["estimate_timely"] = all(
            indices[topic] is not None
            and f"{_TIME_NAMES[topic]}_stale" not in reasons
            for topic in ("vehicle_local_position", "vehicle_attitude", "estimator_status")
        )
        estimate_reasons = [
            reason for reason in reasons
            if not reason.startswith("source_flags_") and reason != "source_flag_invalid"
        ]
        record["estimate_healthy"] = record["estimate_timely"] and not estimate_reasons
        timely_estimate_count += record["estimate_timely"]
        healthy_estimate_count += record["estimate_healthy"]
        if record["estimate_healthy"]:
            healthy_source_counts[record["source"]] += 1

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
        "source_counts_healthy_estimates": dict(sorted(healthy_source_counts.items())),
        "timely_estimate_count": timely_estimate_count,
        "healthy_estimate_count": healthy_estimate_count,
        "topic_coverage": coverage,
        "thresholds_ns": {"estimate": _FAST_MAX_AGE_NS, "source_flags": _SOURCE_MAX_AGE_NS},
        "time_epoch_assumption": "Gazebo frame_ns and PX4 ULog timestamp share simulated epoch; uncalibrated",
        "eligible_for_live_capture": False,
    }
