from __future__ import annotations

from dataclasses import replace
from math import atan2, cos, pi, sin

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from flydrones.connectome_training.px4_odometry_adapter import (
    CameraExtrinsic,
    CameraStamp,
    Px4OdometryCausalAdapter,
    VehicleOdometryEvent,
)


def _event(**changes):
    row = VehicleOdometryEvent(
        topic="/fmu/out/vehicle_odometry",
        session_id="owned-px4-1",
        instance=0,
        sample_us=10_000,
        publication_us=10_010,
        receipt_monotonic_ns=20_000_000,
        pose_frame=1,
        velocity_frame=1,
        position_ned_m=(1.0, 2.0, -3.0),
        q_body_to_ned_wxyz=(1.0, 0.0, 0.0, 0.0),
        velocity_ned_m_s=(4.0, 5.0, -6.0),
        omega_body_frd_rad_s=(0.0, 0.0, 1.0),
        position_variance_m2=(0.1, 0.1, 0.1),
        orientation_variance_rad2=(0.01, 0.01, 0.01),
        velocity_variance_m2_s2=(0.2, 0.2, 0.2),
        reset_counter=0,
        quality=0,
    )
    return replace(row, **changes)


def _extrinsic(**changes):
    row = CameraExtrinsic(
        position_body_frd_m=(0.0, 0.0, 0.0),
        q_camera_to_body_wxyz=(1.0, 0.0, 0.0, 0.0),
        artifact_sha256="a" * 64,
    )
    return replace(row, **changes)


def test_causal_candidate_preserves_event_and_does_not_grant_capture():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event())
    candidate = adapter.at_camera(CameraStamp(sample_us=10_020, receipt_monotonic_ns=25_000_000))
    assert candidate.event == _event()
    assert candidate.position_enu_m == (2.0, 1.0, 3.0)
    assert candidate.velocity_enu_m_s == (5.0, 4.0, 6.0)
    assert candidate.yaw_enu_rad == pytest.approx(pi / 2)
    assert candidate.yaw_rate_enu_rad_s == pytest.approx(-1.0)
    assert candidate.camera_pose_enu_xyzw[:3] == (2.0, 1.0, 3.0)
    expected = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]])
    assert np.allclose(Rotation.from_quat(candidate.camera_pose_enu_xyzw[3:]).as_matrix(), expected)
    assert candidate.eligible_for_live_capture is False
    assert "calibration_not_qualified" in candidate.missing_qualification


def test_rotated_body_moves_camera_lever_arm_in_enu():
    q = (cos(pi / 4), 0.0, 0.0, sin(pi / 4))
    adapter = Px4OdometryCausalAdapter(_extrinsic(position_body_frd_m=(1.0, 0.0, 0.0)))
    adapter.push(_event(q_body_to_ned_wxyz=q, position_ned_m=(0.0, 0.0, 0.0)))
    candidate = adapter.at_camera(CameraStamp(10_020, 25_000_000))
    assert candidate.camera_pose_enu_xyzw[:3] == pytest.approx((1.0, 0.0, 0.0))
    assert candidate.yaw_enu_rad == pytest.approx(0.0)


def test_valid_nonunit_source_quaternion_is_preserved_in_candidate():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event(q_body_to_ned_wxyz=(0.98, 0.0, 0.0, 0.0)))
    candidate = adapter.at_camera(CameraStamp(10_020, 25_000_000))
    assert candidate.event.q_body_to_ned_wxyz == (0.98, 0.0, 0.0, 0.0)
    assert np.allclose(Rotation.from_quat(candidate.camera_pose_enu_xyzw[3:]).as_matrix(),
                       np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]]))


def test_noncommuting_camera_and_body_rotations_compose_in_source_order():
    body = Rotation.from_euler("xyz", (0.2, -0.3, 0.4))
    optical = Rotation.from_euler("xyz", (-0.4, 0.2, 0.1))
    body_q = body.as_quat()
    optical_q = optical.as_quat()
    adapter = Px4OdometryCausalAdapter(_extrinsic(
        q_camera_to_body_wxyz=(optical_q[3], *optical_q[:3])))
    adapter.push(_event(q_body_to_ned_wxyz=(body_q[3], *body_q[:3])))
    candidate = adapter.at_camera(CameraStamp(10_020, 25_000_000))
    ned_to_enu = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]])
    expected = ned_to_enu @ body.as_matrix() @ optical.as_matrix()
    actual = Rotation.from_quat(candidate.camera_pose_enu_xyzw[3:]).as_matrix()
    assert np.allclose(actual, expected, atol=1e-12)


def test_tilted_body_yaw_rate_matches_small_rotation_oracle():
    body = Rotation.from_euler("xyz", [0.3, -0.2, 0.4])
    omega = np.array([0.2, -0.4, 0.7])
    qxyzw = body.as_quat()
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event(q_body_to_ned_wxyz=(qxyzw[3], *qxyzw[:3]),
                        omega_body_frd_rad_s=tuple(omega)))
    candidate = adapter.at_camera(CameraStamp(10_020, 25_000_000))
    dt = 1e-6
    next_body = body * Rotation.from_rotvec(omega * dt)
    def yaw_enu(rotation):
        matrix = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]]) @ rotation.as_matrix()
        return atan2(matrix[1, 0], matrix[0, 0])
    delta = (yaw_enu(next_body) - yaw_enu(body) + pi) % (2 * pi) - pi
    assert candidate.yaw_rate_enu_rad_s == pytest.approx(delta / dt, abs=1e-6)


def test_publication_and_receipt_after_camera_are_never_selected():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event())
    adapter.push(_event(sample_us=20_000, publication_us=20_010,
                        receipt_monotonic_ns=40_000_000))
    assert adapter.at_camera(CameraStamp(20_005, 30_000_000)).event.sample_us == 10_000
    assert adapter.at_camera(CameraStamp(25_000, 35_000_000)).event.sample_us == 10_000
    assert adapter.at_camera(CameraStamp(25_001, 45_000_001)).event.sample_us == 20_000


def test_camera_time_regression_latches_after_a_valid_pair():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event())
    adapter.at_camera(CameraStamp(10_020, 25_000_000))
    with pytest.raises(ValueError, match="camera time regressed"):
        adapter.at_camera(CameraStamp(10_019, 26_000_000))
    assert adapter.failure_reason == "camera time regressed"
    with pytest.raises(ValueError, match="latched"):
        adapter.at_camera(CameraStamp(10_030, 30_000_000))


def test_reset_and_source_identity_changes_latch_forever():
    for changed in ({"reset_counter": 1}, {"reset_counter": 0, "session_id": "new"},
                    {"instance": 1}):
        adapter = Px4OdometryCausalAdapter(_extrinsic())
        adapter.push(_event(reset_counter=255 if changed.get("reset_counter") == 0 else 0))
        with pytest.raises(ValueError):
            adapter.push(_event(sample_us=20_000, publication_us=20_010,
                                receipt_monotonic_ns=40_000_000, **changed))
        with pytest.raises(ValueError):
            adapter.at_camera(CameraStamp(25_000, 45_000_000))
        assert adapter.failure_reason is not None


def test_reset_counter_wrap_alone_latches():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event(reset_counter=255))
    with pytest.raises(ValueError, match="coordinate reset unresolved"):
        adapter.push(_event(sample_us=20_000, publication_us=20_010,
                            receipt_monotonic_ns=40_000_000, reset_counter=0))
    assert adapter.failure_reason == "PX4 coordinate reset unresolved"


@pytest.mark.parametrize("changed", [
    {"topic": "/fmu/out/vehicle_visual_odometry"},
    {"pose_frame": 2}, {"velocity_frame": 3},
    {"position_ned_m": (float("nan"), 0.0, 0.0)},
    {"q_body_to_ned_wxyz": (0.0, 0.0, 0.0, 0.0)},
    {"velocity_variance_m2_s2": (-1.0, 0.0, 0.0)},
    {"sample_us": 10_011}, {"sample_us": True},
    {"reset_counter": -1}, {"quality": True},
])
def test_bad_odometry_callback_is_refused(changed):
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    with pytest.raises(ValueError):
        adapter.push(_event(**changed))
    assert adapter.failure_reason is not None


def test_regression_and_sample_gap_latch_source():
    for changed in (
        {"sample_us": 9_999, "publication_us": 20_010, "receipt_monotonic_ns": 40_000_000},
        {"sample_us": 20_000, "publication_us": 10_009, "receipt_monotonic_ns": 40_000_000},
        {"sample_us": 20_000, "publication_us": 20_010, "receipt_monotonic_ns": 19_999_999},
        {"sample_us": 110_001, "publication_us": 110_010, "receipt_monotonic_ns": 40_000_000},
    ):
        adapter = Px4OdometryCausalAdapter(_extrinsic())
        adapter.push(_event())
        with pytest.raises(ValueError):
            adapter.push(_event(**changed))
        assert adapter.failure_reason is not None


def test_missing_stale_and_future_camera_queries_refuse():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    with pytest.raises(ValueError):
        adapter.at_camera(CameraStamp(10_020, 25_000_000))
    for stamp in (CameraStamp(10_009, 25_000_000),
                  CameraStamp(110_001, 25_000_000),
                  CameraStamp(10_020, 120_000_001),
                  CameraStamp(10_020, 19_000_000)):
        adapter = Px4OdometryCausalAdapter(_extrinsic())
        adapter.push(_event())
        with pytest.raises(ValueError):
            adapter.at_camera(stamp)


@pytest.mark.parametrize("stale_camera", [
    CameraStamp(110_001, 25_000_000),
    CameraStamp(10_020, 120_000_001),
])
def test_stale_px4_source_latches_until_new_adapter(stale_camera):
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event())
    with pytest.raises(ValueError, match="PX4 state stale at camera"):
        adapter.at_camera(stale_camera)
    assert adapter.failure_reason == "PX4 state stale at camera"
    with pytest.raises(ValueError, match="latched"):
        adapter.push(_event(sample_us=110_000, publication_us=110_010,
                            receipt_monotonic_ns=121_000_000))
    with pytest.raises(ValueError, match="latched"):
        adapter.at_camera(CameraStamp(111_000, 125_000_000))
    new_session = Px4OdometryCausalAdapter(_extrinsic())
    new_session.push(_event(sample_us=110_000, publication_us=110_010,
                            receipt_monotonic_ns=121_000_000))
    assert new_session.at_camera(CameraStamp(111_000, 125_000_000)).event.sample_us == 110_000


def test_startup_without_a_px4_state_can_wait_for_first_state():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    with pytest.raises(ValueError, match="no causal PX4 state"):
        adapter.at_camera(CameraStamp(9_000, 19_000_000))
    assert adapter.failure_reason is None
    adapter.push(_event())
    assert adapter.at_camera(CameraStamp(10_020, 25_000_000)).event.sample_us == 10_000


def test_px4_source_at_both_exact_age_limits_is_still_accepted():
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    adapter.push(_event())
    assert adapter.at_camera(CameraStamp(110_000, 120_000_000)).event.sample_us == 10_000
    assert adapter.failure_reason is None


def test_bad_extrinsic_or_near_vertical_heading_refuses():
    with pytest.raises(ValueError):
        Px4OdometryCausalAdapter(_extrinsic(artifact_sha256="unverified"))
    adapter = Px4OdometryCausalAdapter(_extrinsic())
    q = Rotation.from_euler("y", pi / 2).as_quat()
    adapter.push(_event(q_body_to_ned_wxyz=(q[3], *q[:3])))
    with pytest.raises(ValueError):
        adapter.at_camera(CameraStamp(10_020, 25_000_000))
