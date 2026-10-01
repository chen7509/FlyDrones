import json
from pathlib import Path

import numpy as np
import pytest

from flydrones.benchmark.contract import Observation
from flydrones.benchmark.ego import track_reference, validate_reference


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_reference_tracking_is_explicit():
    cmd = track_reference((1., 0., 1.5), (.2, 0., 0.), (0., 0., 1.5), 0., .5)
    assert np.allclose(cmd.velocity_enu, [.7, 0., 0.])


def test_stale_and_invalid_reference_messages_are_rejected():
    valid = {'sim_ns': 100, 'upstream_stamp_ns': 123456, 'position_ref': [1., 0., 1.5], 'velocity_ref': [.2, 0., 0.], 'yaw_rate': 0.}
    assert validate_reference(valid, observation_sim_ns=100, max_age_ns=50)['sim_ns'] == 100
    with pytest.raises(ValueError, match='stale'):
        validate_reference({**valid, 'sim_ns': 49}, observation_sim_ns=100, max_age_ns=50)
    with pytest.raises(ValueError, match='fields'):
        validate_reference({**valid, 'global_cloud': []}, observation_sim_ns=100, max_age_ns=50)
    with pytest.raises(ValueError, match='finite'):
        validate_reference({**valid, 'velocity_ref': [np.nan, 0., 0.]}, observation_sim_ns=100, max_age_ns=50)


def test_future_reference_is_rejected():
    message = {'sim_ns': 101, 'upstream_stamp_ns': 123456, 'position_ref': [1., 0., 1.5], 'velocity_ref': [.2, 0., 0.], 'yaw_rate': 0.}
    with pytest.raises(ValueError, match='future'):
        validate_reference(message, observation_sim_ns=100, max_age_ns=50)


def test_ros_adapter_uses_depth_only_and_launches_no_truth_map_nodes():
    launch = (REPO_ROOT / 'tools/benchmark/ego.launch.py').read_text()
    node = (REPO_ROOT / 'tools/benchmark/ego_node.py').read_text()
    assert "executable='ego_planner_node'" in launch
    assert "executable='traj_server'" in launch
    for forbidden in ('map_generator', 'mockamap', 'fake_drone', 'pcl_render'):
        assert forbidden not in launch
    assert "encoding = '32FC1'" in node
    assert "'/traj_start_trigger'" in node
    assert 'self.trigger_pub.publish' in node
    assert "'upstream_stamp_ns'" in node
    assert 'self.latest_observation_sim_ns' in node
    assert 'PointCloud2' not in node
    assert 'global_cloud' not in node
