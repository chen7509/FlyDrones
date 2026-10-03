"""ULog estimates are audit data, not a live camera-pose source."""

import copy

import numpy as np
import pytest

from flydrones.benchmark.ekf2_shadow import audit_shadow_frames


def _topics():
    fast = np.array([50_000, 150_000, 350_000], np.int64)
    return {
        "vehicle_local_position": {
            "timestamp": fast.copy(),
            "x": np.array([1., 2., 3.]), "y": np.array([4., 5., 6.]),
            "z": np.array([-1., -2., -3.]),
            "vx": np.array([.1, .2, .3]), "vy": np.array([.4, .5, .6]),
            "vz": np.array([-.1, -.2, -.3]),
            "xy_valid": np.array([1, 1, 1]), "z_valid": np.array([1, 1, 1]),
            "v_xy_valid": np.array([1, 1, 1]), "v_z_valid": np.array([1, 1, 1]),
            "heading_good_for_control": np.array([1, 1, 1]),
            "dead_reckoning": np.array([0, 0, 0]),
        },
        "vehicle_attitude": {
            "timestamp": fast.copy(),
            "q[0]": np.ones(3), "q[1]": np.zeros(3),
            "q[2]": np.zeros(3), "q[3]": np.zeros(3),
        },
        "estimator_status": {
            "timestamp": fast.copy(),
            "filter_fault_flags": np.zeros(3, np.int64),
        },
        "estimator_status_flags": {
            "timestamp": np.array([0, 300_000], np.int64),
            "cs_gnss_pos": np.array([1, 0]),
            "cs_ev_pos": np.array([0, 1]),
        },
    }


def test_preserves_all_frames_and_never_uses_future_px4_state():
    report = audit_shadow_frames([0, 100_000_000, 200_000_000, 400_000_000], _topics())
    assert report["schema"] == "flydrones-ekf2-ulog-shadow-v1"
    assert report["frame_count"] == len(report["records"]) == 4
    assert report["records"][0]["status"] == "missing"
    assert "local_position_missing" in report["records"][0]["reasons"]
    assert report["records"][0]["local_position_timestamp_us"] is None
    assert [record["status"] for record in report["records"][1:]] == ["valid"] * 3
    assert report["records"][1]["local_position_age_ns"] == 50_000_000
    assert report["records"][1]["position_ned_m"] == [1., 4., -1.]
    assert report["records"][1]["position_enu_m"] == [4., 1., 1.]
    assert report["records"][1]["velocity_enu_mps"] == [.4, .1, .1]
    assert [record["source"] for record in report["records"][1:]] == [
        "gnss", "gnss", "external_vision"]
    assert report["eligible_for_live_capture"] is False


def test_stale_and_invalid_health_reasons_are_distinct_and_retained():
    topics = _topics()
    topics["vehicle_local_position"]["xy_valid"][1] = 0
    topics["vehicle_local_position"]["dead_reckoning"][1] = 1
    topics["estimator_status"]["filter_fault_flags"][1] = 4
    report = audit_shadow_frames([200_000_000, 500_000_000, 2_500_000_000], topics)
    first = report["records"][0]
    assert first["status"] == "invalid"
    assert {"xy_invalid", "dead_reckoning", "filter_fault"} <= set(first["reasons"])
    second = report["records"][1]
    assert second["status"] == "invalid"
    assert "local_position_stale" in second["reasons"]
    assert "attitude_stale" in second["reasons"]
    assert "estimator_status_stale" in second["reasons"]
    assert report["records"][2]["source"] == "unknown"
    assert "source_flags_stale" in report["records"][2]["reasons"]
    assert report["counts"] == {"valid": 0, "invalid": 3, "missing": 0}


def test_bad_numeric_sample_is_marked_invalid_without_dropping_frame():
    topics = _topics()
    topics["vehicle_local_position"]["x"][0] = np.nan
    topics["vehicle_attitude"]["q[0]"][1] = 0.
    report = audit_shadow_frames([100_000_000, 200_000_000, 400_000_000], topics)
    assert [record["status"] for record in report["records"]] == [
        "invalid", "invalid", "valid"]
    assert "nonfinite_local_position" in report["records"][0]["reasons"]
    assert "invalid_attitude_quaternion" in report["records"][1]["reasons"]


@pytest.mark.parametrize("mutate", [
    lambda topics: topics["vehicle_local_position"].pop("x"),
    lambda topics: topics["vehicle_attitude"]["timestamp"].__setitem__(1, -1),
    lambda topics: topics["estimator_status_flags"]["cs_ev_pos"].resize(1, refcheck=False),
    lambda topics: topics["vehicle_local_position"].update(x=np.array(["1", "2", "3"])),
])
def test_rejects_missing_fields_bad_width_or_topic_clock_rollback(mutate):
    topics = copy.deepcopy(_topics())
    mutate(topics)
    with pytest.raises(ValueError):
        audit_shadow_frames([100_000_000], topics)


def test_rejects_duplicate_or_reversed_frame_times():
    with pytest.raises(ValueError, match="frame"):
        audit_shadow_frames([100_000_000, 100_000_000], _topics())
    with pytest.raises(ValueError, match="frame"):
        audit_shadow_frames([200_000_000, 100_000_000], _topics())
