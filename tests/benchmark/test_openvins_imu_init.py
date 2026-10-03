from __future__ import annotations

import numpy as np
import pytest

from tools.benchmark.audit_openvins_imu_init import (
    compare_imu_rows,
    extract_static_init,
    score_ekf_init_velocity,
)


def _imu() -> tuple[dict, list[dict]]:
    source = {
        "timestamp": np.array([1_000_000, 1_004_000]),
        "accelerometer_timestamp_relative": np.array([0, 0]),
        "gyro_integral_dt": np.array([4000, 4000]),
        "accelerometer_integral_dt": np.array([4000, 4000]),
        "gyro_clipping": np.array([0, 0]),
        "accelerometer_clipping": np.array([0, 0]),
    }
    values = ((.1, .2, .3, 1., 2., -9.8), (.4, .5, .6, 3., 4., -9.7))
    for i, name in enumerate(("gyro_rad",) * 3 + ("accelerometer_m_s2",) * 3):
        axis = i if i < 3 else i - 3
        source[f"{name}[{axis}]"] = np.array([v[i] for v in values])
    rows = [dict(zip(("timestamp_us", "gx", "gy", "gz", "ax", "ay", "az"),
                     (str(t), *(str(v) for v in vals)), strict=True))
            for t, vals in zip(source["timestamp"], values, strict=True)]
    return source, rows


def test_imu_export_matches_every_axis_and_timestamp() -> None:
    source, rows = _imu()
    summary = compare_imu_rows(source, rows)
    assert summary["sample_count"] == 2
    assert summary["accelerometer_relative_offset_nonzero"] == 0
    assert summary["any_clipped_samples"] == 0
    assert summary["median_interval_us"] == 4000


def test_imu_export_rejects_single_changed_axis_or_timestamp() -> None:
    source, rows = _imu()
    with pytest.raises(ValueError, match="IMU value mismatch"):
        compare_imu_rows(source, [{**rows[0], "ay": "2.01"}, rows[1]])
    with pytest.raises(ValueError, match="IMU timestamp mismatch"):
        compare_imu_rows(source, [rows[0], {**rows[1], "timestamp_us": "1004001"}])
    with pytest.raises(ValueError, match="relative timestamp"):
        compare_imu_rows({**source, "accelerometer_timestamp_relative": np.array([0, 4])}, rows)


_INIT_LOG = "\n".join((
    "InertialInitializer.cpp:139 [init]: USING STATIC INITIALIZER METHOD!",
    "VioManagerHelper.cpp:136 [init]: successful initialization in 0.0001 seconds",
    "VioManagerHelper.cpp:137 [init]: orientation = -1.0000, -0.0000, 0.0001, 0.0001",
    "VioManagerHelper.cpp:139 [init]: bias gyro = 0.0001, -0.0032, 0.0001",
    "VioManagerHelper.cpp:141 [init]: velocity = 0.0000, 0.0000, 0.0000",
    "VioManagerHelper.cpp:142 [init]: bias accel = -0.0000, -0.0000, -0.1079",
))


def test_extract_static_init_requires_one_success_and_zero_logged_velocity() -> None:
    states = [{"image_ns": "26700000000", "initialized": "0"},
              {"image_ns": "26800000000", "initialized": "1"}]
    record = extract_static_init(_INIT_LOG, states)
    assert record["first_initialized_s"] == pytest.approx(26.8)
    assert record["method"] == "static"
    assert record["initial_velocity_m_s"] == [0., 0., 0.]
    assert record["bias_accel_m_s2"] == [0., 0., -.1079]
    with pytest.raises(ValueError, match="successful initialization"):
        extract_static_init(
            _INIT_LOG + "\nVioManagerHelper.cpp:136 [init]: successful initialization in 0.1 seconds",
            states)


def _velocity() -> dict:
    return {
        "timestamp": np.array([1_000_000, 1_010_000, 1_020_000]),
        "vx": np.array([.2, .2, .2]), "vy": np.zeros(3), "vz": np.zeros(3),
        "v_xy_valid": np.ones(3), "v_z_valid": np.ones(3),
        "vxy_reset_counter": np.zeros(3), "vz_reset_counter": np.zeros(3),
    }


def test_low_excitation_can_coexist_with_nonzero_ekf_velocity() -> None:
    rows, summary = score_ekf_init_velocity(_velocity(), 1., 1.02)
    assert len(rows) == 3
    assert summary["median_speed_m_s"] == pytest.approx(.2)
    assert summary["reference_moving_over_0_1_mps"] is True


@pytest.mark.parametrize("change,match", [
    ({"v_xy_valid": np.array([1, 0, 1])}, "invalid"),
    ({"vxy_reset_counter": np.array([0, 1, 1])}, "reset"),
    ({"timestamp": np.array([1_000_000, 1_010_000, 1_040_000])}, "gap"),
])
def test_ekf_window_rejects_invalid_reset_or_gap(change: dict, match: str) -> None:
    data = {**_velocity(), **change}
    with pytest.raises(ValueError, match=match):
        score_ekf_init_velocity(data, 1., 1.04 if match == "gap" else 1.02)
