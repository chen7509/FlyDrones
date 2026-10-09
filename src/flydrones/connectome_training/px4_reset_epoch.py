"""Read-only EKF2 reset history for a future non-truth capture producer.

This audit has no source receipt, clock calibration or camera evidence and never
grants live capture eligibility.
"""

from __future__ import annotations

import numpy as np

_MAX_NS = np.iinfo(np.int64).max
_RESET_FIELDS = {
    "vehicle_local_position": (
        "xy_reset_counter", "z_reset_counter", "vxy_reset_counter",
        "vz_reset_counter", "heading_reset_counter",
    ),
    "vehicle_attitude": ("quat_reset_counter",),
}


def _integers(value: object, *, length: int | None = None,
              maximum: int, name: str) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be bounded integers") from exc
    if (array.ndim != 1 or array.dtype.kind not in "iu"
            or (length is not None and len(array) != length)
            or np.any(array < 0) or np.any(array > maximum)):
        raise ValueError(f"{name} must be bounded integers")
    return array.astype(np.int64, copy=True)


def _topic_arrays(name: str, source: object) -> dict[str, np.ndarray]:
    if not isinstance(source, dict) or any(
            field not in source for field in ("timestamp", "timestamp_sample", *_RESET_FIELDS[name])):
        raise ValueError(f"{name} required reset or time fields missing")
    publication = _integers(source["timestamp"], maximum=_MAX_NS // 1000,
                            name=f"{name} timestamp")
    count = len(publication)
    if not count or np.any(publication <= 0) or np.any(np.diff(publication) <= 0):
        raise ValueError(f"{name} publication times invalid")
    sample = _integers(source["timestamp_sample"], length=count,
                       maximum=_MAX_NS // 1000, name=f"{name} timestamp_sample")
    if (np.any(sample <= 0) or np.any(np.diff(sample) <= 0)
            or np.any(sample > publication)):
        raise ValueError(f"{name} sample times invalid")
    arrays = {"timestamp": publication, "timestamp_sample": sample}
    for field in _RESET_FIELDS[name]:
        arrays[field] = _integers(source[field], length=count, maximum=255,
                                  name=f"{name} {field}")
    return arrays


def audit_reset_epochs(frame_ns: list[int], topics: dict) -> dict:
    """Latch any published reset in the original source session.

    A new coordinate epoch requires a separately proven session and goal
    policy. A stable counter after a transition never clears this latch.
    """
    if (not isinstance(frame_ns, list) or not frame_ns
            or any(type(value) is not int or not 0 <= value <= _MAX_NS for value in frame_ns)
            or any(after <= before for before, after in zip(frame_ns, frame_ns[1:]))):
        raise ValueError("frame times must be bounded strictly increasing integers")
    if not isinstance(topics, dict) or any(name not in topics for name in _RESET_FIELDS):
        raise ValueError("both PX4 state topics are required")
    arrays = {name: _topic_arrays(name, topics[name]) for name in _RESET_FIELDS}
    transitions = []
    for name, data in arrays.items():
        for field in _RESET_FIELDS[name]:
            changed = np.flatnonzero(np.diff(data[field]) != 0) + 1
            for index in changed:
                transitions.append({
                    "topic": name, "field": field, "index": int(index),
                    "publication_us": int(data["timestamp"][index]),
                    "before": int(data[field][index - 1]),
                    "after": int(data[field][index]),
                })
    transitions.sort(key=lambda row: (row["publication_us"], row["topic"], row["field"]))
    first_transition_ns = (transitions[0]["publication_us"] * 1000
                           if transitions else None)
    records = []
    for frame in frame_ns:
        selected = {}
        reasons = []
        for name, data in arrays.items():
            index = int(np.searchsorted(data["timestamp"], frame // 1000, side="right")) - 1
            if index < 0:
                selected[name] = None
                reasons.append(f"{name}_missing")
            else:
                selected[name] = {
                    "index": index,
                    "publication_us": int(data["timestamp"][index]),
                    "sample_us": int(data["timestamp_sample"][index]),
                    "counters": {field: int(data[field][index]) for field in _RESET_FIELDS[name]},
                }
        unresolved = first_transition_ns is not None and frame >= first_transition_ns
        if unresolved:
            reasons.append("reset_epoch_unresolved")
        records.append({"frame_ns": frame, "selected": selected,
                        "reset_epoch_unresolved": unresolved,
                        "reasons": sorted(reasons)})
    return {
        "schema": "flydrones-px4-reset-epoch-audit-v1",
        "frame_count": len(records),
        "records": records,
        "transitions": transitions,
        "reset_epoch_unresolved_frames": sum(row["reset_epoch_unresolved"] for row in records),
        "eligible_for_live_capture": False,
        "missing_qualification": [
            "runtime_source_receipt", "clock_epoch", "camera_extrinsic",
            "estimator_health", "teacher_process", "goal_reset_policy",
        ],
    }
