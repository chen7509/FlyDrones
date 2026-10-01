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
