"""Exploratory image-versus-raw-IMU timing fit for a controlled Gazebo yaw probe."""

from __future__ import annotations

import numpy as np


def fit_image_imu_lag(
    frame_s: np.ndarray, image_yaw_rad: np.ndarray,
    imu_stamp_s: np.ndarray, imu_z_rad_s: np.ndarray,
    *, max_lag_ms: int = 100, step_ms: int = 4,
) -> dict:
    """Find IMU timestamp delay relative to image, fitting one angle intercept.

    This is a fixture diagnostic, not an estimator of physical camera/IMU
    time offset. Camera yaw is derived from a known, static colored target.
    """
    frame = np.asarray(frame_s, dtype=float)
    yaw = np.asarray(image_yaw_rad, dtype=float)
    imu = np.asarray(imu_stamp_s, dtype=float)
    gyro = np.asarray(imu_z_rad_s, dtype=float)
    if (frame.ndim != 1 or imu.ndim != 1 or yaw.shape != frame.shape or gyro.shape != imu.shape
            or len(frame) < 10 or len(imu) < 100 or not np.all(np.isfinite(frame))
            or not np.all(np.isfinite(yaw)) or not np.all(np.isfinite(imu))
            or not np.all(np.isfinite(gyro)) or np.any(np.diff(frame) <= 0)
            or np.any(np.diff(imu) <= 0)):
        raise ValueError("finite increasing image and IMU streams are required")
    if np.ptp(yaw) < .15 or np.ptp(gyro) < .4:
        raise ValueError("insufficient yaw excitation to assess timing")
    if max_lag_ms <= 0 or step_ms <= 0 or max_lag_ms % step_ms:
        raise ValueError("lag search must have positive integral grid")
    original_image_count = len(frame)
    margin = max_lag_ms / 1_000
    common = (frame >= imu[0] + margin) & (frame <= imu[-1] - margin)
    frame, yaw = frame[common], yaw[common]
    if len(frame) < 10 or np.ptp(yaw) < .15:
        raise ValueError("insufficient common image/IMU overlap and excitation")
    integral = np.r_[0., np.cumsum((gyro[1:] + gyro[:-1]) * np.diff(imu) / 2.)]
    candidates = []
    for lag_ms in range(-max_lag_ms, max_lag_ms + 1, step_ms):
        sample_t = frame + lag_ms / 1_000
        if sample_t[0] < imu[0] or sample_t[-1] > imu[-1]:
            continue
        predicted = np.interp(sample_t, imu, integral)
        residual = yaw - predicted
        residual -= np.mean(residual)
        candidates.append((lag_ms, float(np.sqrt(np.mean(residual**2)))))
    if not candidates:
        raise ValueError("no complete image/IMU time overlap for lag scan")
    best_lag, best_rmse = min(candidates, key=lambda item: item[1])
    zero = next((rmse for lag, rmse in candidates if lag == 0), None)
    return {
        "schema": "flydrones-controlled-image-imu-lag-fit-v1",
        "best_imu_stamp_lag_ms": best_lag,
        "best_rmse_rad": best_rmse,
        "zero_lag_rmse_rad": zero,
        "image_count": len(frame),
        "image_count_before_common_window": original_image_count,
        "imu_count": len(imu),
        "image_yaw_span_rad": float(np.ptp(yaw)),
        "imu_gyro_span_rad_s": float(np.ptp(gyro)),
        "lag_grid_ms": step_ms,
        "lag_scan": [{"lag_ms": lag, "rmse_rad": rmse} for lag, rmse in candidates],
    }
