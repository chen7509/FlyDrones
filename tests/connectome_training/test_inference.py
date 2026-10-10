from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest
import torch

from flydrones.connectome_training.dataset import SequenceFrame
from flydrones.connectome_training.features import MASKED_FEATURE_NAMES, frame_features
from flydrones.connectome_training.inference import ConnectomeInferenceController, InferenceLimits
from flydrones.connectome_training.inference_artifact import load_inference_core
from flydrones.connectome_training.model import RecurrentState


def frame(time_ns=50_000_000, **changes):
    original = SequenceFrame(time_ns, time_ns, np.zeros((2, 3, 3), np.uint8),
                             np.ones((2, 3), np.float32), np.zeros(3),
                             np.zeros(3), 0., 0., np.array([2., 0., 0.]))
    return replace(original, **changes)


def controller(tiny_artifacts, **kwargs):
    source, folder, _, _ = tiny_artifacts(**kwargs)
    loaded = load_inference_core(source, folder, mode="tiny-fixture")
    return ConnectomeInferenceController(loaded), loaded


@pytest.mark.parametrize("yaw", [0., np.pi / 2])
def test_analytic_zero_topology_prediction_and_enu_intent(tiny_artifacts, yaw):
    adapter, loaded = controller(tiny_artifacts, zero=True)
    # dt=50ms, tau=20ms -> alpha=1. Depth drives [1,1,1], luminance=0.
    rates = np.array([1 / (1 + np.exp(-1))] * 3 + [.5])
    expected = np.tanh(rates * [0.3, -0.2, 0.4, 0.1])
    result = adapter.step(frame(yaw=yaw))
    assert result.evidence["raw_command"] == pytest.approx(expected)
    vector = expected[:3] / np.linalg.norm(expected[:3]) * .06
    assert result.command.velocity_enu == pytest.approx(vector)
    assert result.command.yaw_rate == pytest.approx(expected[3])
    assert result.evidence["flight_eligible"] is False
    assert result.evidence["training_success_verified"] is False
    assert result.evidence["parameter_origin"] == "initialization-only"
    assert not loaded.core.training


def test_continuous_state_matches_direct_core_and_explicit_reset(tiny_artifacts):
    adapter, loaded = controller(tiny_artifacts)
    state = loaded.core.initial_state(1)
    outputs = []
    with torch.inference_mode():
        for index in range(3):
            sample = frame((index + 1) * 50_000_000)
            expected, state = loaded.core.forward_step(torch.from_numpy(frame_features(sample))[None, :], state, .05)
            decision = adapter.step(sample)
            assert decision.evidence["raw_command"] == pytest.approx(expected[0].numpy())
            outputs.append(decision.evidence["raw_command"])
    assert outputs[0] != outputs[1]
    adapter.reset(17)
    first = adapter.step(frame())
    assert first.evidence["raw_command"] == pytest.approx(outputs[0])
    assert first.evidence["call_index"] == 1
    assert first.evidence["session_index"] == 2
    assert all(value.grad is None for value in loaded.core.parameters())


def test_masked_controller_matches_direct_core_and_refuses_legacy_frame(tiny_artifacts):
    adapter, loaded = controller(tiny_artifacts, feature_names=MASKED_FEATURE_NAMES)
    depth = np.array([[1.0, np.nan, 2.0], [1.0, 3.0, 2.0]], np.float32)
    sample = frame(depth_m=depth, depth_valid=np.isfinite(depth))
    with torch.inference_mode():
        expected, _ = loaded.core.forward_step(
            torch.from_numpy(frame_features(sample, profile="depth-mask-v3"))[None, :],
            loaded.core.initial_state(1), .05,
        )
    result = adapter.step(sample)
    assert result.evidence["raw_command"] == pytest.approx(expected[0].tolist())
    assert result.evidence["feature_profile"] == "depth-mask-v3"
    adapter.reset(0)
    with pytest.raises(ValueError, match="depth_valid"):
        adapter.step(frame())
    assert adapter.failure is not None


def test_legacy_controller_refuses_masked_frame(tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    sample = frame(depth_valid=np.ones((2, 3), np.bool_))
    with pytest.raises(ValueError, match="masked depth"):
        adapter.step(sample)
    assert adapter.failure is not None


def test_legacy_image_digest_is_unchanged(tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    sample = frame()
    digest = sha256()
    for value in (sample.rgb, sample.depth_m):
        digest.update(str((value.shape, value.dtype.str)).encode("ascii"))
        digest.update(np.ascontiguousarray(value).tobytes())
    assert adapter.step(sample).evidence["image_sha256"] == digest.hexdigest()


def test_held_camera_is_labeled_reused_not_new_estimate(tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    adapter.step(frame())
    second = adapter.step(frame(100_000_000, frame_ns=50_000_000))
    assert second.evidence["camera_reused"] is True
    assert second.evidence["frame_age_ns"] == 50_000_000
    adapter.step(frame(150_000_000, frame_ns=50_000_000))  # inclusive age boundary
    with pytest.raises(ValueError, match="age"):
        adapter.step(frame(200_000_000, frame_ns=50_000_000))


@pytest.mark.parametrize("changes", [
    {"rgb": np.ones((2, 3, 3), np.uint8)},
    {"depth_m": np.full((2, 3), 2., np.float32)},
])
def test_reused_timestamp_with_changed_pixels_refuses(changes, tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    adapter.step(frame())
    with pytest.raises(ValueError, match="reused"):
        adapter.step(frame(100_000_000, frame_ns=50_000_000, **changes))


@pytest.mark.parametrize("sample", [
    frame(50_000_000), frame(49_000_000), frame(150_000_000),
    frame(100_000_000, frame_ns=100_000_001), frame(100_000_000, frame_ns=49_000_000),
    frame(True), frame(100_000_000., frame_ns=100_000_000), frame(2**63),
    frame(100_000_000, rgb=np.zeros((0, 3, 3), np.uint8), depth_m=np.zeros((0, 3))),
    frame(100_000_000, rgb=np.zeros((2, 3, 3), np.float32)),
    frame(100_000_000, depth_m=np.zeros((2, 3))),
    frame(100_000_000, velocity_enu=np.array([float("inf"), 0, 0])),
])
def test_invalid_input_latches_without_committing_state(sample, tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    adapter.step(frame())
    voltage = adapter._state.voltage.clone()
    previous = adapter._previous
    with pytest.raises(ValueError):
        adapter.step(sample)
    assert adapter.call_index == 1
    assert adapter.last_sim_ns == 50_000_000
    assert torch.equal(adapter._state.voltage, voltage)
    assert adapter._previous == previous
    assert adapter.failure is not None
    with pytest.raises(RuntimeError, match="failed"):
        adapter.step(frame(100_000_000))
    adapter.reset(0)
    assert adapter.step(frame()).evidence["call_index"] == 1


@pytest.mark.parametrize("bad_state", [False, True])
def test_nonfinite_native_core_result_is_rejected_before_commit(tiny_artifacts, monkeypatch, bad_state):
    adapter, loaded = controller(tiny_artifacts)
    adapter.step(frame())
    voltage = adapter._state.voltage.clone()
    previous = adapter._previous
    real = loaded.core.forward_step
    def bad(*args):
        output, state = real(*args)
        if bad_state:
            return output, RecurrentState(torch.full_like(state.voltage, float("nan")))
        return torch.full_like(output, float("nan")), state
    monkeypatch.setattr(loaded.core, "forward_step", bad)
    with pytest.raises(ValueError, match="core"):
        adapter.step(frame(100_000_000))
    assert adapter.call_index == 1
    assert adapter.last_sim_ns == 50_000_000
    assert torch.equal(adapter._state.voltage, voltage)
    assert adapter._previous == previous
    assert adapter.failure is not None


def test_close_is_terminal_and_reset_cannot_reopen(tiny_artifacts):
    adapter, _ = controller(tiny_artifacts)
    adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        adapter.step(frame())
    with pytest.raises(RuntimeError, match="closed"):
        adapter.reset(0)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_bad_limits_refuse(value):
    with pytest.raises(ValueError):
        InferenceLimits(speed_max_mps=value)
