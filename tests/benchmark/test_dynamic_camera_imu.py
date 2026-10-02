"""Synthetic timing tests independent of Gazebo and image segmentation."""

import numpy as np
import pytest

from flydrones.benchmark.dynamic_camera_imu import fit_image_imu_lag


def test_fit_recovers_known_imu_timestamp_lag():
    true_t = np.arange(0, 3.001, .004)
    gyro = np.where(true_t < .3, 0., np.where(true_t < 1.2, .7,
                   np.where(true_t < 2.1, -.7, .5)))
    yaw = np.r_[0., np.cumsum((gyro[1:] + gyro[:-1]) * np.diff(true_t) / 2)]
    frames = np.arange(.2, 2.801, .1)
    image_yaw = np.interp(frames, true_t, yaw)
    result = fit_image_imu_lag(frames, image_yaw, true_t + .024, gyro)
    assert abs(result["best_imu_stamp_lag_ms"] - 24) <= 4
    assert result["best_rmse_rad"] < 1e-3


def test_fit_rejects_unexcited_imu():
    frames = np.arange(.1, 2.1, .1)
    imu_t = np.arange(0, 2.2, .004)
    with pytest.raises(ValueError, match="excitation"):
        fit_image_imu_lag(frames, np.zeros_like(frames), imu_t, np.zeros_like(imu_t))


def test_fit_uses_common_overlap_instead_of_boundary_biased_lag_scan():
    true_t = np.arange(0, 3.001, .004)
    gyro = np.where(true_t < .3, 0., np.where(true_t < 1.2, .7,
                   np.where(true_t < 2.1, -.7, .5)))
    yaw = np.r_[0., np.cumsum((gyro[1:] + gyro[:-1]) * np.diff(true_t) / 2)]
    frames = np.arange(.1, 3.001, .1)
    image_yaw = np.interp(frames, true_t, yaw)
    result = fit_image_imu_lag(frames, image_yaw, true_t + .024, gyro)
    assert abs(result["best_imu_stamp_lag_ms"] - 24) <= 4
    assert result["lag_scan"][0]["lag_ms"] == -100
    assert result["lag_scan"][-1]["lag_ms"] == 100
