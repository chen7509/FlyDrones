import numpy as np
import pytest
from scipy import sparse
import torch

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
)


def fixture_model():
    weights = sparse.csc_matrix(
        np.array([[0, 2, 0], [-3, 0, 1], [0, 0, 0]], np.float32)
    )
    connectome = Connectome(
        "tiny",
        weights,
        np.array(["A", "B", "A"]),
        np.array(["L", "R", "L"]),
    )
    identity = build_structure_identity(connectome, "a" * 64)
    params = initial_parameter_set(
        identity,
        ("depth", "goal_x"),
        ("vx", "yaw_rate"),
        np.array([1, 2]),
    )
    model = ConnectomeConstrainedCore(connectome, params)
    return weights, model


def test_only_declared_shared_parameters_are_trainable():
    weights, model = fixture_model()
    assert set(dict(model.named_parameters())) == {
        "raw_input_gain",
        "type_bias_mv",
        "raw_tau_m",
        "readout",
    }
    coo = weights.tocoo()
    order = np.lexsort((coo.col, coo.row))
    assert np.array_equal(model.edge_sign.cpu().numpy(), np.sign(coo.data[order]))
    assert not model.edge_sign.requires_grad
    assert not model.edge_magnitude.requires_grad


def test_state_is_carried_within_sequence_and_reset_between_sequences():
    _, model = fixture_model()
    x = torch.tensor([[1.0, 0.5]])
    first, state1 = model.forward_step(x, model.initial_state(1), 0.05)
    second, state2 = model.forward_step(x, state1, 0.05)
    reset, reset_state = model.forward_step(x, model.initial_state(1), 0.05)
    assert not torch.allclose(state2.voltage, reset_state.voltage)
    assert torch.allclose(first, reset)


def test_truncated_sequence_backprop_reaches_only_allowed_parameters():
    _, model = fixture_model()
    prediction, _ = model.forward_sequence(
        torch.ones(1, 5, 2), truncate_steps=2
    )
    prediction.square().sum().backward()
    assert all(parameter.grad is not None for parameter in model.parameters())


def test_non_finite_features_are_rejected():
    _, model = fixture_model()
    with pytest.raises(ValueError, match="features contain non-finite"):
        model.forward_sequence(
            torch.tensor([[[float("nan"), 0.0]]]), truncate_steps=1
        )
