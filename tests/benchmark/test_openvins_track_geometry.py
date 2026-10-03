from __future__ import annotations

import numpy as np
import pytest

from tools.benchmark.audit_openvins_track_geometry import (
    assert_config_digest,
    audit_attempts,
    camera_pose_ned,
    parse_trace,
    sample_attitude,
    sample_position,
    triangulate_bearings,
    validate_trace_stages,
)


def test_reused_feature_id_is_preserved_as_two_update_attempts() -> None:
    trace = "\n".join([
        "FD_TRACK_START t=1.000000000 id=7 n=2",
        "FD_TRACK_OBS t=1.000000000 id=7 cam=0 obs_t=0.900000000 u=0.100000000 v=-0.200000000",
        "FD_TRACK_OBS t=1.000000000 id=7 cam=0 obs_t=1.000000000 u=0.080000000 v=-0.190000000",
        "FD_TRACK_START t=1.100000000 id=7 n=2",
        "FD_TRACK_OBS t=1.100000000 id=7 cam=0 obs_t=1.000000000 u=0.080000000 v=-0.190000000",
        "FD_TRACK_OBS t=1.100000000 id=7 cam=0 obs_t=1.100000000 u=0.070000000 v=-0.180000000",
    ])
    attempts = parse_trace(trace)
    assert len(attempts) == 2
    assert attempts[0]["feature_id"] == attempts[1]["feature_id"] == 7
    assert attempts[0]["window_s"] == 1.0
    assert attempts[1]["window_s"] == 1.1
    assert attempts[0]["observations"][0] == {
        "camera_id": 0, "time_s": 0.9, "u_norm": 0.1, "v_norm": -0.2,
    }


@pytest.mark.parametrize("bad_line", [
    "FD_TRACK_OBS t=1.000000000 id=7 cam=0 obs_t=0.900000000 u=nan v=0.0",
    "FD_TRACK_OBS t=1.000000000 id=7 cam=0 obs_t=1.100000000 u=0.0 v=0.0",
    "FD_TRACK_OBS t=1.000000000 id=8 cam=0 obs_t=0.900000000 u=0.0 v=0.0",
])
def test_malformed_track_observation_is_rejected(bad_line: str) -> None:
    trace = "\n".join([
        "FD_TRACK_START t=1.000000000 id=7 n=2",
        "FD_TRACK_OBS t=1.000000000 id=7 cam=0 obs_t=0.900000000 u=0.0 v=0.0",
        bad_line,
    ])
    with pytest.raises(ValueError):
        parse_trace(trace)


def test_camera_optical_forward_rotates_from_body_forward_into_ned_east() -> None:
    yaw_quarter_turn = np.array([2 ** -.5, 0, 0, 2 ** -.5])
    camera_to_body = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    position, rotation = camera_pose_ned(
        np.zeros(3), yaw_quarter_turn, camera_to_body,
        np.array([.12, 0, -.002]),
    )
    assert position == pytest.approx([0, .12, -.002], abs=1e-12)
    assert rotation @ np.array([0, 0, 1]) == pytest.approx([0, 1, 0], abs=1e-12)


def test_valid_pose_interpolation_and_reset_gates() -> None:
    times = np.array([1.0, 1.01])
    positions = np.array([[0, 0, 0], [1, 0, 0]])
    zero = np.array([1, 0, 0, 0])
    yaw = np.array([2 ** -.5, 0, 0, 2 ** -.5])
    assert sample_position(1.005, times, positions, np.array([1, 1]),
                           np.array([1, 1]), np.array([0, 0]),
                           np.array([0, 0])) == pytest.approx([.5, 0, 0])
    halfway = sample_attitude(1.005, times, np.array([zero, yaw]),
                              np.array([0, 0]))
    assert camera_pose_ned(np.zeros(3), halfway, np.eye(3), np.zeros(3))[1] @ np.array([1, 0, 0]) == pytest.approx(
        [2 ** -.5, 2 ** -.5, 0], abs=1e-12,
    )
    with pytest.raises(ValueError, match="reset"):
        sample_position(1.005, times, positions, np.array([1, 1]),
                        np.array([1, 1]), np.array([0, 1]),
                        np.array([0, 0]))
    with pytest.raises(ValueError, match="invalid"):
        sample_position(1.005, times, positions, np.array([1, 0]),
                        np.array([1, 1]), np.array([0, 0]),
                        np.array([0, 0]))
    with pytest.raises(ValueError, match="gap"):
        sample_attitude(1.5, np.array([1.0, 2.0]), np.array([zero, yaw]),
                        np.array([0, 0]))


def test_known_static_point_triangulates_without_scale_fit_and_outlier_is_visible() -> None:
    poses = [(np.array([x, 0, 0]), np.eye(3)) for x in (-1.0, 0.0, 1.0)]
    bearings = [(.2, 0.0), (0.0, 0.0), (-.2, 0.0)]
    good = triangulate_bearings(bearings, poses, focal_px=100)
    assert good["point_ned_m"] == pytest.approx([0, 0, 5], abs=1e-10)
    assert good["anchor_depth_m"] == pytest.approx(5, abs=1e-10)
    assert good["reprojection_rmse_px"] == pytest.approx(0, abs=1e-10)
    bad = triangulate_bearings([bearings[0], (.5, .5), bearings[2]],
                               poses, focal_px=100)
    assert bad["reprojection_rmse_px"] > 10


def test_audit_preserves_unscored_and_degenerate_attempts() -> None:
    attempts = [{"window_s": 1.01, "feature_id": feature_id,
                 "observations": [{"camera_id": 0, "time_s": time,
                                   "u_norm": 0.0, "v_norm": 0.0}
                                  for time in (1.0, 1.01)]}
                for feature_id in (7, 8)]
    attitude = {"times": np.array([1.0, 1.01]),
                "quaternions": np.array([[1, 0, 0, 0], [1, 0, 0, 0]]),
                "reset": np.array([0, 0])}
    position = {"times": np.array([1.0, 1.01]),
                "positions": np.zeros((2, 3)),
                "xy_valid": np.array([1, 1]), "z_valid": np.array([1, 1]),
                "xy_reset": np.array([0, 0]), "z_reset": np.array([0, 0])}
    rows = audit_attempts(attempts, attitude, position, np.eye(3),
                          np.zeros(3), focal_px=100)
    assert len(rows) == 2
    assert [row["attempt_index"] for row in rows] == [0, 1]
    assert all(row["status"] == "geometry_rejected" for row in rows)
    assert all(row["reason"] == "degenerate track geometry" for row in rows)
    position["xy_valid"][0] = 0
    rows = audit_attempts(attempts, attitude, position, np.eye(3),
                          np.zeros(3), focal_px=100)
    assert len(rows) == 2
    assert all(row["status"] == "unscored" for row in rows)
    assert all("invalid" in row["reason"] for row in rows)


def test_calibration_digest_rejects_changed_yaml_even_if_expected_lines_remain() -> None:
    import hashlib

    original = b"T_imu_cam: fixed\nintrinsics: fixed\n"
    expected = hashlib.sha256(original).hexdigest()
    assert_config_digest(original, expected)
    with pytest.raises(ValueError, match="config SHA-256"):
        assert_config_digest(original + b"extra_override: changed\n", expected)


def test_each_trace_window_must_match_one_stage_count() -> None:
    attempts = [{"window_s": 1.0, "feature_id": 7, "observations": []},
                {"window_s": 2.0, "feature_id": 8, "observations": []}]
    matching = "\n".join(["FD_MSCKF_STAGE t=1.000000000 input=2 clean=1 tri=0",
                          "FD_MSCKF_STAGE t=2.000000000 input=2 clean=1 tri=0"])
    assert validate_trace_stages(matching, attempts) == 2
    compensated = "\n".join(["FD_MSCKF_STAGE t=1.000000000 input=2 clean=0 tri=0",
                             "FD_MSCKF_STAGE t=2.000000000 input=2 clean=2 tri=0"])
    with pytest.raises(ValueError, match="window"):
        validate_trace_stages(compensated, attempts)
    with pytest.raises(ValueError, match="duplicate"):
        validate_trace_stages(matching + "\n" + matching.splitlines()[0], attempts)
