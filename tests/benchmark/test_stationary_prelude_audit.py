from __future__ import annotations

import numpy as np
import pytest

from tools.benchmark.audit_stationary_prelude import assess_prelude


def _result() -> dict:
    return {
        "development_hover_prelude": {
            "requested_steps": 80, "actual_steps": 80,
            "start_sim_ns": 29_000_000_000, "end_sim_ns": 33_000_000_000,
            "terminal_status": None,
        },
        "decisions": [{"sim_ns": 33_000_000_000}],
        "rgb_capture_accepted": True,
        "camera_info_capture_accepted": True,
        "px4_ulog_capture_accepted": True,
    }


def _velocity(speed: float = .05) -> dict:
    stamps = np.arange(30_990_000, 33_010_001, 10_000, dtype=np.int64)
    n = len(stamps)
    return {
        "timestamp": stamps, "vx": np.full(n, speed),
        "vy": np.zeros(n), "vz": np.zeros(n),
        "v_xy_valid": np.ones(n), "v_z_valid": np.ones(n),
        "vxy_reset_counter": np.zeros(n), "vz_reset_counter": np.zeros(n),
    }


def _frames() -> list[int]:
    return list(range(29_000_000_000, 33_100_000_000, 100_000_000))


def test_quiet_prelude_passes_with_complete_sensor_window() -> None:
    rows, summary = assess_prelude(_result(), _velocity(), _frames())
    assert len(rows) > 100
    assert summary["gate_passed"] is True
    assert summary["window_start_s"] == 31.0
    assert summary["window_end_s"] == 33.0
    assert summary["velocity"]["median_speed_m_s"] == pytest.approx(.05)


@pytest.mark.parametrize("speed", [.1, .4])
def test_moving_prelude_fails_gate(speed: float) -> None:
    _, summary = assess_prelude(_result(), _velocity(speed), _frames())
    assert summary["gate_passed"] is False
    assert "speed_not_below_0_1_m_s" in summary["failures"]


def test_missing_camera_window_fails_gate() -> None:
    frames = [n for n in _frames() if n < 31_000_000_000]
    _, summary = assess_prelude(_result(), _velocity(), frames)
    assert "rgb_missing_in_velocity_window" in summary["failures"]


def test_missing_or_misaligned_prelude_fails_closed() -> None:
    result = _result()
    result["decisions"] = []
    with pytest.raises(ValueError, match="first policy decision"):
        assess_prelude(result, _velocity(), _frames())
    result = _result()
    result["decisions"][0]["sim_ns"] += 50_000_000
    with pytest.raises(ValueError, match="prelude end"):
        assess_prelude(result, _velocity(), _frames())


def test_invalid_velocity_flags_or_reset_fails_closed() -> None:
    velocity = _velocity()
    velocity["v_xy_valid"][100] = 0
    with pytest.raises(ValueError, match="invalid EKF2 velocity"):
        assess_prelude(_result(), velocity, _frames())
    velocity = _velocity()
    velocity["vxy_reset_counter"][100:] = 1
    with pytest.raises(ValueError, match="reset"):
        assess_prelude(_result(), velocity, _frames())


def test_incomplete_evidence_fails_closed() -> None:
    result = _result()
    result["px4_ulog_capture_accepted"] = False
    with pytest.raises(ValueError, match="capture evidence"):
        assess_prelude(result, _velocity(), _frames())
