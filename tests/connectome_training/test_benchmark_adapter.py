from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec

import numpy as np
import pytest

from flydrones.benchmark.contract import Observation
from flydrones.connectome_training.dataset import SequenceFrame
from flydrones.connectome_training.inference import ConnectomeInferenceController, InferenceLimits
from flydrones.connectome_training.inference_artifact import load_inference_core


def api():
    name = 'flydrones.connectome_training.benchmark_adapter'
    assert find_spec(name) is not None, 'offline benchmark observation adapter is missing'
    return import_module(name)


def observation(**changes):
    return replace(Observation(50_000_000, 50_000_000,
                               np.full((2, 3, 3), 117, np.uint8),
                               np.array([[2., 4., 8.], [2., 4., 8.]], np.float32),
                               (100., 200., 300., 1., 0., 0., 0.),
                               (1., 2., 3.), (.2, -.3, .4), 1.2, -.5, (4., 6., 8.)), **changes)


def loaded_core(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    return load_inference_core(source, folder, mode='tiny-fixture')


def test_observation_maps_si_fields_and_owns_arrays():
    obs = observation()
    result = api().observation_frame(obs)
    assert result.sim_ns == result.frame_ns == 50_000_000
    assert result.position_enu.tolist() == [1., 2., 3.]
    assert result.velocity_enu.tolist() == [.2, -.3, .4]
    assert result.goal_enu.tolist() == [4., 6., 8.]
    assert (result.yaw, result.yaw_rate) == (1.2, -.5)
    assert result.rgb[0, 0].tolist() == [117, 117, 117]
    assert result.depth_m[0].tolist() == [2., 4., 8.]
    obs.rgb[:] = 0
    obs.depth_m[:] = 1
    assert result.rgb[0, 0].tolist() == [117, 117, 117]
    assert result.depth_m[0].tolist() == [2., 4., 8.]


@pytest.mark.parametrize('source', ['synthetic', 'gazebo-model-truth'])
def test_actual_core_commands_recurrence_and_identity_preserved(tiny_artifacts, source):
    loaded = loaded_core(tiny_artifacts)
    controller = api().OfflineBenchmarkController(loaded, observation_source=source,
                                                  limits=InferenceLimits())
    direct = ConnectomeInferenceController(loaded)
    controller.reset(17)
    direct.reset(17)
    for index in range(3):
        stamp = (index + 1) * 50_000_000
        obs = observation(sim_ns=stamp, frame_ns=50_000_000 if index < 2 else stamp)
        reference = SequenceFrame(obs.sim_ns, obs.frame_ns, obs.rgb, obs.depth_m,
                                  np.array([1., 2., 3.]), np.array([.2, -.3, .4]),
                                  1.2, -.5, np.array([4., 6., 8.]))
        expected = direct.step(reference)
        got = controller.step(obs)
        assert got.command == expected.command
        assert got.evidence['raw_command'] == expected.evidence['raw_command']
        assert got.evidence['model_identity'] == loaded.provenance['model_identity']
        assert got.evidence['call_index'] == index + 1
        assert got.evidence['camera_reused'] == (index == 1)
        assert got.evidence['observation_source_declared'] == source
        assert got.evidence['input_source_verified'] is False
        assert got.evidence['flight_eligible'] is False
        assert got.evidence['training_success_verified'] is False
        assert got.evidence['policy_kind'] == 'offline-connectome-rate-core'
        assert got.elapsed_wall_s >= got.evidence['inference_elapsed_wall_s'] >= 0
    controller.close()


@pytest.mark.parametrize('source', ['', None, 'px4_ekf2', 'real-vio'])
def test_unverified_deployment_source_cannot_be_declared(tiny_artifacts, source):
    with pytest.raises(ValueError, match='source'):
        api().OfflineBenchmarkController(loaded_core(tiny_artifacts),
                                         observation_source=source, limits=InferenceLimits())


@pytest.mark.parametrize('bad', [object(), observation(depth_m=np.zeros((2, 3))),
                               observation(sim_ns=True), observation(yaw=float('nan'))])
def test_boundary_or_inference_failure_latches_until_explicit_reset(tiny_artifacts, bad):
    controller = api().OfflineBenchmarkController(loaded_core(tiny_artifacts),
                                                  observation_source='synthetic', limits=InferenceLimits())
    with pytest.raises((TypeError, ValueError)):
        controller.step(bad)
    with pytest.raises(RuntimeError, match='failed'):
        controller.step(observation())
    controller.reset(3)
    assert controller.step(observation()).evidence['call_index'] == 1
    controller.close()
    with pytest.raises(RuntimeError, match='closed'):
        controller.step(observation())
    with pytest.raises(RuntimeError, match='closed'):
        controller.reset(4)


def test_actual_limits_are_used_without_changing_enu_direction(tiny_artifacts):
    controller = api().OfflineBenchmarkController(
        loaded_core(tiny_artifacts), observation_source='synthetic',
        limits=InferenceLimits(speed_max_mps=.02, acceleration_max_mps2=.1, yaw_rate_max_radps=.001))
    result = controller.step(observation())
    assert np.linalg.norm(result.command.velocity_enu) == pytest.approx(.005)
    assert abs(result.command.yaw_rate) <= .001
    controller.close()
