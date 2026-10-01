import numpy as np
import pytest

from flydrones.benchmark.contract import Observation
from flydrones.benchmark.sensors import (
    FrameCache,
    PoseHistory,
    camera_pose_from_model,
    camera_matrix,
    decode_observation,
    encode_observation,
    optical_to_body,
)


def test_optical_right_is_body_right():
    assert np.allclose(optical_to_body(np.array([1., 0., 0.])), [0., -1., 0.])


def test_duplicate_frame_not_reprojected():
    cache = FrameCache()
    rgb = np.zeros((120,160,3), np.uint8)
    depth = np.ones((120,160), np.float32)
    pose = (0.,0.,1.5,0.,0.,0.,1.)
    assert cache.add(100, rgb, depth, pose)
    assert not cache.add(100, rgb, depth, pose)
    with pytest.raises(ValueError):
        cache.add(200, rgb, depth, None)


def test_binary_roundtrip_and_truth_fields_rejected():
    obs = Observation(100, 90, np.zeros((2,3,3), np.uint8), np.full((2,3), np.nan, np.float32),
                      (0.,0.,0.,0.,0.,0.,1.), (0.,0.,1.), (0.,0.,0.), 0., 0., (1.,0.,1.))
    result = decode_observation(encode_observation(obs))
    assert np.array_equal(result.rgb, obs.rgb)
    assert np.all(np.isnan(result.depth_m))
    import json
    payload = json.loads(encode_observation(obs))
    payload['world'] = {'obstacles': []}
    with pytest.raises(ValueError):
        decode_observation(json.dumps(payload).encode())


def test_camera_matrix_matches_pixel_center():
    k = camera_matrix(160, 120, 1.274)
    assert k[0,2] == 79.5
    assert k[1,2] == 59.5
    assert k[0,0] == pytest.approx(160 / (2 * np.tan(1.274 / 2)))


def test_frame_pose_is_interpolated_at_capture_timestamp():
    history = PoseHistory()
    history.add(100, (0., 0., 1., 0., 0., 0., 1.))
    history.add(200, (2., 0., 1., 0., 0., 1., 0.))
    pose = history.at(150)
    assert np.allclose(pose[:3], (1., 0., 1.))
    assert np.allclose(np.abs(pose[3:]), (0., 0., np.sqrt(.5), np.sqrt(.5)))


def test_frame_pose_outside_history_is_rejected():
    history = PoseHistory()
    history.add(100, (0., 0., 1., 0., 0., 0., 1.))
    with pytest.raises(ValueError, match='bracket'):
        history.at(90)


def test_stopped_world_may_use_a_recent_pose_without_extrapolation():
    history = PoseHistory()
    pose = (1., 2., 3., 0., 0., 0., 1.)
    history.add(990, pose)
    assert history.latest_at_or_before(1000, max_age_ns=10) == pose
    with pytest.raises(ValueError, match='stale'):
        history.latest_at_or_before(1001, max_age_ns=10)
    with pytest.raises(ValueError, match='before'):
        history.latest_at_or_before(989, max_age_ns=10)


def test_capture_pose_interpolates_or_uses_recent_preceding_measurement():
    history = PoseHistory()
    history.add(100, (0., 0., 1., 0., 0., 0., 1.))
    history.add(200, (2., 0., 1., 0., 0., 0., 1.))
    assert history.at_or_recent_before(150, max_age_ns=10)[0] == pytest.approx(1.)
    assert history.at_or_recent_before(205, max_age_ns=5)[0] == pytest.approx(2.)
    with pytest.raises(ValueError, match='stale'):
        history.at_or_recent_before(206, max_age_ns=5)


def test_camera_pose_uses_optical_frame_at_capture_time():
    pose = camera_pose_from_model((0., 0., 0., 0., 0., 0., 1.))
    assert np.allclose(pose[:3], (.12, 0., .242))
    assert np.allclose(pose[3:], (.5, -.5, .5, -.5))
