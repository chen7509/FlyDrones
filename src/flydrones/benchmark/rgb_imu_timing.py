"""Preflight timing comparison for simulated RGB and PX4 ULog IMU samples."""

from __future__ import annotations

import numpy as np


def analyze_timing(frame_ns: list[int], imu_timestamp_us: list[int]) -> dict:
    """Compare nearest samples without shifting either timebase to force a pass."""
    frames = np.asarray(frame_ns, dtype=np.int64)
    imu_us = np.asarray(imu_timestamp_us, dtype=np.int64)
    if not len(frames) or np.any(frames <= 0) or np.any(np.diff(frames) <= 0):
        raise ValueError("frame timestamps must be positive and strictly increasing")
    if not len(imu_us) or np.any(imu_us <= 0) or np.any(np.diff(imu_us) <= 0):
        raise ValueError("IMU timestamps must be positive and strictly increasing")
    imu = imu_us * 1_000
    if np.any(imu // 1_000 != imu_us):
        raise ValueError("IMU timestamp overflow")
    indices = np.searchsorted(imu, frames)
    left = imu[np.maximum(indices - 1, 0)]
    right = imu[np.minimum(indices, len(imu) - 1)]
    nearest_delta_ms = np.minimum(np.abs(frames - left), np.abs(frames - right)) / 1_000_000
    inside = (frames >= imu[0]) & (frames <= imu[-1])
    intervals = np.diff(frames)
    return {
        "schema": "flydrones-rgb-imu-timing-v1",
        "assumption": "Gazebo image and PX4 ULog timestamps share simulation epoch; not calibrated",
        "frame_count": len(frames),
        "imu_count": len(imu),
        "first_frame_ns": int(frames[0]),
        "last_frame_ns": int(frames[-1]),
        "first_imu_ns": int(imu[0]),
        "last_imu_ns": int(imu[-1]),
        "frames_inside_imu_range": int(np.count_nonzero(inside)),
        "frames_outside_imu_range": int(np.count_nonzero(~inside)),
        "median_frame_rate_hz": float(1_000_000_000 / np.median(intervals)) if len(intervals) else None,
        "nearest_imu_delta_ms_median": float(np.median(nearest_delta_ms)),
        "nearest_imu_delta_ms_p95": float(np.percentile(nearest_delta_ms, 95)),
        "nearest_imu_delta_ms_max": float(np.max(nearest_delta_ms)),
        "nearest_imu_delta_ms_p95_inside_range": float(np.percentile(nearest_delta_ms[inside], 95)) if np.any(inside) else None,
    }


def analyze_decision_window(
    frame_ns: list[int], imu_timestamp_us: list[int], decisions: list[dict],
    *, max_gap_ms: float = 20.0,
) -> dict:
    """Audit data availability over observed controller frames, preserving raw gaps."""
    # Validate both complete input streams before selecting the decision interval.
    full = analyze_timing(frame_ns, imu_timestamp_us)
    if not np.isfinite(max_gap_ms) or max_gap_ms <= 0:
        raise ValueError("max_gap_ms must be finite and positive")
    if len(decisions) < 2:
        raise ValueError("decision window needs at least two decisions")
    stamps = [item.get("sim_ns") for item in decisions]
    observed = [item.get("frame_ns") for item in decisions]
    if (any(type(value) is not int for value in stamps + observed)
            or any(a >= b for a, b in zip(stamps, stamps[1:]))
            or any(a > b for a, b in zip(observed, observed[1:]))
            or any(frame > sim for frame, sim in zip(observed, stamps))):
        raise ValueError("decision timestamps must increase and observed frames cannot advance ahead of simulation")
    frames = np.asarray(frame_ns, dtype=np.int64)
    if not set(observed).issubset(set(frame_ns)):
        raise ValueError("decision refers to an unrecorded RGB frame")
    start_ns, end_ns = observed[0], observed[-1]
    selected = frames[(frames >= start_ns) & (frames <= end_ns)]
    if len(selected) < 2:
        raise ValueError("decision window needs at least two distinct RGB frames")
    timing = analyze_timing(selected.tolist(), imu_timestamp_us)
    imu = np.asarray(imu_timestamp_us, dtype=np.int64) * 1_000
    covered_imu = imu[(imu >= start_ns) & (imu <= end_ns)]
    imu_gap_ms_max = (float(np.max(np.diff(covered_imu))) / 1_000_000
                      if len(covered_imu) >= 2 else None)
    accepted = (
        timing["frames_outside_imu_range"] == 0
        and timing["nearest_imu_delta_ms_max"] <= max_gap_ms
        and imu_gap_ms_max is not None and imu_gap_ms_max <= max_gap_ms
    )
    return {
        "schema": "flydrones-rgb-imu-decision-window-v1",
        "window_start_ns": int(start_ns),
        "window_end_ns": int(end_ns),
        "decision_count": len(decisions),
        "raw_frame_count": full["frame_count"],
        "raw_frames_before_window": int(np.count_nonzero(frames < start_ns)),
        "raw_frames_after_window": int(np.count_nonzero(frames > end_ns)),
        "raw_frames_outside_imu_range": full["frames_outside_imu_range"],
        "window_frame_count": len(selected),
        "window_imu_count": len(covered_imu),
        "window_frames_outside_imu_range": timing["frames_outside_imu_range"],
        "window_nearest_imu_delta_ms_max": timing["nearest_imu_delta_ms_max"],
        "window_imu_gap_ms_max": imu_gap_ms_max,
        "max_gap_ms_limit": float(max_gap_ms),
        "coverage_accepted": bool(accepted),
    }
