import numpy as np
import pytest

from tools.benchmark.audit_prearm_static import assess_prearm_windows


def test_prearm_window_and_late_moving_initialization_remain_distinct():
    stamps = np.arange(0, 10_000_001, 8_000, dtype=np.int64)
    velocity = np.where(stamps < 7_000_000, 0.01, 0.4)
    local = {
        'timestamp': stamps, 'vx': velocity, 'vy': np.zeros(len(stamps)),
        'vz': np.zeros(len(stamps)), 'v_xy_valid': np.ones(len(stamps), bool),
        'v_z_valid': np.ones(len(stamps), bool),
        'vxy_reset_counter': np.zeros(len(stamps), int),
        'vz_reset_counter': np.zeros(len(stamps), int),
    }
    result = {
        'rgb_capture_accepted': True, 'camera_info_capture_accepted': True,
        'px4_ulog_capture_accepted': True, 'evidence_failures': [],
        'development_prearm_stationary': {
            'requested_s': 4., 'start_sim_ns': 2_000_000_000,
            'end_sim_ns': 6_000_000_000, 'status': 'completed',
        },
    }
    frames_ns = list(range(0, 10_000_000_001, 100_000_000))
    imu_us = list(range(0, 10_000_001, 4_000))
    summary, windows = assess_prearm_windows(result, frames_ns, imu_us, local, 9.)
    assert summary['prearm_static_window']['median_speed_m_s'] == pytest.approx(.01)
    assert summary['initialization_window']['median_speed_m_s'] == pytest.approx(.4)
    assert summary['prearm_sensor_coverage']['passed'] is True
    assert summary['full_prearm_sensor_coverage']['passed'] is True
    assert summary['initialization_inside_prearm'] is False
    assert len(windows['prearm']) > 100


def test_full_prearm_coverage_exposes_early_camera_gap():
    stamps = np.arange(0, 10_000_001, 8_000, dtype=np.int64)
    local = {
        'timestamp': stamps, 'vx': np.full(len(stamps), .01),
        'vy': np.zeros(len(stamps)), 'vz': np.zeros(len(stamps)),
        'v_xy_valid': np.ones(len(stamps), bool),
        'v_z_valid': np.ones(len(stamps), bool),
        'vxy_reset_counter': np.zeros(len(stamps), int),
        'vz_reset_counter': np.zeros(len(stamps), int),
    }
    result = {
        'rgb_capture_accepted': True, 'camera_info_capture_accepted': True,
        'px4_ulog_capture_accepted': True, 'evidence_failures': [],
        'development_prearm_stationary': {
            'requested_s': 4., 'start_sim_ns': 2_000_000_000,
            'end_sim_ns': 6_000_000_000, 'status': 'completed',
        },
    }
    frames_ns = list(range(4_000_000_000, 10_000_000_001, 100_000_000))
    imu_us = list(range(0, 10_000_001, 4_000))
    summary, _ = assess_prearm_windows(result, frames_ns, imu_us, local, 9.)
    assert summary['prearm_sensor_coverage']['passed'] is True
    assert summary['full_prearm_sensor_coverage']['passed'] is False


def test_prearm_audit_rejects_incomplete_capture():
    with pytest.raises(ValueError, match='capture'):
        assess_prearm_windows({'rgb_capture_accepted': False}, [], [], {}, 9.)
