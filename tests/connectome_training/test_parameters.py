import numpy as np
import pytest
from scipy import sparse

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
    load_parameter_set,
    save_parameter_set,
)


def tiny_connectome():
    weights = sparse.csc_matrix(
        np.array([[0, 2, 0], [-3, 0, 1], [0, 0, 0]], np.float32)
    )
    return Connectome(
        "tiny",
        weights,
        np.array(["A", "B", "A"]),
        np.array(["L", "R", "L"]),
    )


def test_identity_hashes_exact_signed_topology_and_type_order():
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    assert identity.neurons == 3
    assert identity.connections == 3
    assert identity.cell_types == ("A", "B")
    assert len(identity.topology_sha256) == 64
    changed = tiny_connectome()
    changed.weights.data[0] *= -1
    assert (
        build_structure_identity(changed, "a" * 64).topology_sha256
        != identity.topology_sha256
    )


def test_parameter_round_trip_is_hashed_and_tamper_evident(tmp_path):
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    params = initial_parameter_set(
        identity,
        ("depth_left", "goal_x"),
        ("vx", "yaw_rate"),
        output_neurons=2,
    )
    out = save_parameter_set(tmp_path / "params", params)
    loaded = load_parameter_set(out)
    assert loaded.identity == identity
    assert np.array_equal(loaded.type_bias_mv, params.type_bias_mv)
    arrays = out / "parameters.npz"
    arrays.write_bytes(arrays.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_parameter_set(out)


def test_full_identity_cannot_be_claimed_with_wrong_counts():
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    with pytest.raises(ValueError, match="full-male-cns requires"):
        initial_parameter_set(
            identity, ("depth",), ("vx",), 1, label="full-male-cns"
        )
