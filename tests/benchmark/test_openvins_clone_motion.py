from __future__ import annotations

import numpy as np
import pytest

from tools.benchmark.audit_openvins_clone_motion import (
    compare_relative_motion,
    match_clone_poses,
    parse_clone_trace,
    score_attempt_geometry,
)


def _line(window: float, feature_id: int, obs_time: float, rotation=None, position=None) -> str:
    r = np.eye(3) if rotation is None else np.asarray(rotation)
    p = np.zeros(3) if position is None else np.asarray(position)
    fields = [f"FD_CLONE_POSE t={window:.9f} id={feature_id} cam=0 obs_t={obs_time:.9f}"]
    fields += [f"r{i}{j}={r[i, j]:.9f}" for i in range(3) for j in range(3)]
    fields += [f"p{i}={p[i]:.9f}" for i in range(3)]
    return " ".join(fields)


def test_clone_records_match_each_repeated_feature_attempt_exactly() -> None:
    attempts = [
        {"window_s": 1.0, "feature_id": 7,
         "observations": [{"camera_id": 0, "time_s": t} for t in (.9, 1.0)]},
        {"window_s": 1.1, "feature_id": 7,
         "observations": [{"camera_id": 0, "time_s": t} for t in (1.0, 1.1)]},
    ]
    trace = "\n".join([_line(1.0, 7, .9), _line(1.0, 7, 1.0),
                       _line(1.1, 7, 1.0), _line(1.1, 7, 1.1)])
    matched = match_clone_poses(attempts, parse_clone_trace(trace))
    assert len(matched) == 2
    assert all(len(group) == 2 for group in matched)
    assert matched[0][0][1] == pytest.approx(np.eye(3))
    with pytest.raises(ValueError, match="missing"):
        match_clone_poses(attempts, parse_clone_trace("\n".join(trace.splitlines()[:-1])))
    with pytest.raises(ValueError, match="duplicate"):
        parse_clone_trace(trace + "\n" + trace.splitlines()[0])
    with pytest.raises(ValueError, match="unexpected"):
        match_clone_poses(attempts, parse_clone_trace(trace + "\n" + _line(2.0, 9, 2.0)))


def test_clone_pose_requires_finite_proper_rotation() -> None:
    quarter_turn_global_to_camera = np.array([[0., -1., 0.],
                                              [1., 0., 0.],
                                              [0., 0., 1.]])
    parsed = parse_clone_trace(_line(1.0, 7, 1.0,
                                     rotation=quarter_turn_global_to_camera))
    assert parsed[0]["rotation_cam_to_global"] == pytest.approx(
        quarter_turn_global_to_camera.T)
    reflected = np.diag([-1, 1, 1])
    with pytest.raises(ValueError, match="rotation"):
        parse_clone_trace(_line(1.0, 7, 1.0, rotation=reflected))
    with pytest.raises(ValueError, match="finite"):
        parse_clone_trace(_line(1.0, 7, 1.0).replace("p0=0.000000000", "p0=nan"))


def test_relative_motion_is_invariant_to_common_global_gauge_without_scale_fit() -> None:
    turn = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    reference = [(np.zeros(3), np.eye(3)), (np.array([1., 0., 0.]), turn)]
    gauge = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    clones = [(gauge @ p + np.array([5., 6., 7.]), gauge @ r) for p, r in reference]
    equal = compare_relative_motion(clones, reference)
    assert equal["rotation_error_deg"] == pytest.approx(0, abs=1e-8)
    assert equal["translation_direction_error_deg"] == pytest.approx(0, abs=1e-8)
    assert equal["baseline_ratio"] == pytest.approx(1, abs=1e-8)
    doubled = [(clones[0][0], clones[0][1]),
               (clones[0][0] + 2 * (clones[1][0] - clones[0][0]), clones[1][1])]
    assert compare_relative_motion(doubled, reference)["baseline_ratio"] == pytest.approx(2)


def test_zero_baseline_keeps_rotation_but_marks_translation_unscored() -> None:
    poses = [(np.zeros(3), np.eye(3)), (np.zeros(3), np.eye(3))]
    result = compare_relative_motion(poses, poses)
    assert result["rotation_error_deg"] == pytest.approx(0)
    assert result["translation_direction_error_deg"] is None
    assert result["baseline_ratio"] is None


def test_reversed_clone_motion_is_reported_as_negative_depth_not_dropped() -> None:
    attempt = {"window_s": 1.0, "feature_id": 7,
               "observations": [{"camera_id": 0, "time_s": t,
                                 "u_norm": u, "v_norm": 0.0}
                                for t, u in zip((.8, .9, 1.0), (.2, 0.0, -.2))]}
    reference = [(np.array([x, 0, 0]), np.eye(3)) for x in (-1., 0., 1.)]
    reversed_clones = [(np.array([x, 0, 0]), np.eye(3)) for x in (1., 0., -1.)]
    result = score_attempt_geometry(attempt, reversed_clones, reference, focal_px=100)
    assert result["reference_status"] == "positive_depth"
    assert result["clone_status"] == "nonpositive_depth"
    assert result["clone_anchor_depth_m"] == pytest.approx(-5)
    assert result["translation_direction_error_deg"] == pytest.approx(180)
    assert result["baseline_ratio"] == pytest.approx(1)
