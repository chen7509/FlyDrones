import numpy as np
import pytest
import torch
from scipy import sparse

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.model import (
    ConnectomeConstrainedCore,
    _compact_csr_topology,
)
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
)


def fixture_model(*, topology_format="coo_reference"):
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
    if topology_format == "coo_reference":
        model = ConnectomeConstrainedCore(connectome, params)
    else:
        model = ConnectomeConstrainedCore(
            connectome, params, topology_format=topology_format
        )
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


def test_compact_csr_has_same_signed_topology_without_redundant_edge_buffers():
    _, reference = fixture_model()
    _, compact = fixture_model(topology_format="csr_compact_v1")
    assert compact.fixed_topology.layout == torch.sparse_csr
    assert compact.fixed_topology.crow_indices().dtype == torch.int32
    assert compact.fixed_topology.col_indices().dtype == torch.int32
    assert torch.equal(compact.fixed_topology.to_dense(), reference.fixed_topology.to_dense())
    assert not compact.fixed_topology.requires_grad
    assert not {"edge_row", "edge_column", "edge_sign", "edge_magnitude"} & set(
        compact.state_dict()
    )
    assert set(dict(compact.named_parameters())) == set(dict(reference.named_parameters()))


def test_compact_csr_preserves_truncated_sequence_and_allowed_gradients():
    _, reference = fixture_model()
    _, compact = fixture_model(topology_format="csr_compact_v1")
    with torch.no_grad():
        reference.readout.fill_(0.3)
        compact.readout.copy_(reference.readout)
    features = torch.tensor(
        [[[.25, -.5], [1., .3], [-.1, .7], [.8, -.2], [0., .1]]]
    )
    expected, expected_state = reference.forward_sequence(
        features, truncate_steps=2, dt_s=0.005
    )
    actual, actual_state = compact.forward_sequence(
        features, truncate_steps=2, dt_s=0.005
    )
    assert torch.allclose(actual, expected, atol=1e-7, rtol=0)
    assert torch.allclose(actual_state.voltage, expected_state.voltage, atol=1e-7, rtol=0)
    expected.square().sum().backward()
    actual.square().sum().backward()
    for name, parameter in reference.named_parameters():
        other = dict(compact.named_parameters())[name]
        assert parameter.grad is not None and other.grad is not None
        assert torch.count_nonzero(parameter.grad) > 0
        assert torch.allclose(other.grad, parameter.grad, atol=1e-7, rtol=0)


def test_compact_csr_coalesces_duplicates_and_eliminates_explicit_zero():
    weights = sparse.csc_matrix(
        (np.array([-1., -2., 0., 2., 1.], np.float32),
         np.array([1, 1, 2, 0, 1]), np.array([0, 3, 4, 5])),
        shape=(3, 3),
    )
    connectome = Connectome(
        "duplicates", weights, np.array(["A", "B", "A"]),
        np.array(["L", "R", "L"]),
    )
    identity = build_structure_identity(connectome, "a" * 64)
    params = initial_parameter_set(
        identity, ("depth", "goal_x"), ("vx", "yaw_rate"), np.array([1, 2])
    )
    source_data = connectome.weights.data.copy()
    reference = ConnectomeConstrainedCore(connectome, params)
    compact = ConnectomeConstrainedCore(
        connectome, params, topology_format="csr_compact_v1"
    )
    assert np.array_equal(connectome.weights.data, source_data)
    assert compact.fixed_topology._nnz() == identity.connections
    assert torch.allclose(compact.fixed_topology.to_dense(), reference.fixed_topology.to_dense())


def test_compact_csr_rejects_nonfinite_and_index_overflow():
    weights = sparse.csc_matrix(np.array([[float("inf")]], dtype=np.float32))
    connectome = Connectome(
        "invalid", weights, np.array(["A"]), np.array(["L"])
    )
    with pytest.raises(ValueError, match="non-finite"):
        _compact_csr_topology(connectome, 1)
    with pytest.raises(ValueError, match="int32 index range"):
        _compact_csr_topology(connectome, np.iinfo(np.int32).max + 1)


def test_compact_csr_preserves_raw_absolute_denominator_with_signed_duplicates():
    weights = sparse.csc_matrix(
        (
            np.array([2.0, -1.0, 1.0], dtype=np.float32),
            np.array([1, 1, 1]),
            np.array([0, 2, 3, 3]),
        ),
        shape=(3, 3),
    )
    connectome = Connectome(
        "signed_duplicates", weights, np.array(["A", "B", "A"]),
        np.array(["L", "R", "L"]),
    )
    identity = build_structure_identity(connectome, "a" * 64)
    params = initial_parameter_set(
        identity, ("depth",), ("vx",), np.array([1])
    )
    reference = ConnectomeConstrainedCore(connectome, params)
    compact = ConnectomeConstrainedCore(
        connectome, params, topology_format="csr_compact_v1"
    )
    assert torch.allclose(
        compact.fixed_topology.to_dense(), reference.fixed_topology.to_dense()
    )


def test_compact_csr_rejects_unknown_format():
    weights = sparse.csc_matrix(np.eye(2, dtype=np.float32))
    connectome = Connectome(
        "tiny", weights, np.array(["A", "B"]), np.array(["L", "R"])
    )
    identity = build_structure_identity(connectome, "a" * 64)
    params = initial_parameter_set(
        identity, ("depth",), ("vx",), np.array([1])
    )
    with pytest.raises(ValueError, match="topology format"):
        ConnectomeConstrainedCore(connectome, params, topology_format="unknown")
