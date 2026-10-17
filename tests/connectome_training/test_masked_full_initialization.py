from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest

from flydrones.connectome_training.features import FEATURE_NAMES, MASKED_FEATURE_NAMES
from flydrones.connectome_training.masked_full_initialization import (
    create_masked_initialization,
    derive_masked_initialization,
)
from flydrones.connectome_training.parameters import (
    StructureIdentity,
    initial_parameter_set,
    load_parameter_set,
    save_parameter_set,
)


def _legacy(model_sha: str = "a" * 64):
    identity = StructureIdentity(
        "full-male-cns", model_sha, "b" * 64, 166_700, 25_582_837, ("A", "B")
    )
    return initial_parameter_set(
        identity, FEATURE_NAMES, ("vx", "vy", "vz", "yaw_rate"),
        np.array([100, 101], np.int64),
        input_feature_index=np.arange(30) % len(FEATURE_NAMES),
        input_neuron_index=np.arange(30, dtype=np.int64) + 10,
    )


def test_derivation_is_new_untrained_v3_mapping_with_same_neurons():
    source = _legacy()
    result = derive_masked_initialization(source)
    assert result.identity == source.identity
    assert result.input_features == MASKED_FEATURE_NAMES
    assert result.outputs == source.outputs
    assert np.array_equal(result.input_neuron_index, source.input_neuron_index)
    assert np.array_equal(result.output_neuron_index, source.output_neuron_index)
    assert np.array_equal(result.input_feature_index, np.arange(30) % 15)
    assert set(result.input_feature_index.tolist()) == set(range(15))
    assert np.all(result.input_gain == 1)
    assert np.all(result.type_bias_mv == 0)
    assert np.all(result.readout == 0)
    assert result.tau_m_ms == 20.0
    assert source.input_features == FEATURE_NAMES


@pytest.mark.parametrize("change", [
    lambda p: replace(p, input_features=MASKED_FEATURE_NAMES),
    lambda p: replace(p, input_gain=np.full(12, 1.1, np.float32)),
    lambda p: replace(p, type_bias_mv=np.array([0.0, 0.1], np.float32)),
    lambda p: replace(p, tau_m_ms=19.0),
    lambda p: replace(p, readout=np.ones((4, 2), np.float32)),
    lambda p: replace(p, input_feature_index=np.arange(30) % 11),
    lambda p: replace(p, identity=replace(p.identity, label="synthetic")),
    lambda p: replace(p, type_bias_mv=np.zeros(0, np.float32)),
    lambda p: replace(p, readout=np.zeros((1, 1), np.float32)),
])
def test_derivation_refuses_wrong_or_modified_source(change):
    with pytest.raises(ValueError):
        derive_masked_initialization(change(_legacy()))


def test_frozen_source_hashes_and_destination_are_enforced(tmp_path):
    model = tmp_path / "model.npz"
    model.write_bytes(b"frozen model bytes")
    model_sha = sha256(model.read_bytes()).hexdigest()
    source = save_parameter_set(tmp_path / "legacy", _legacy(model_sha))
    expected = {
        "expected_manifest_sha256": sha256((source / "manifest.json").read_bytes()).hexdigest(),
        "expected_parameters_sha256": sha256((source / "parameters.npz").read_bytes()).hexdigest(),
        "expected_model_sha256": sha256(model.read_bytes()).hexdigest(),
    }
    destination = tmp_path / "v3"
    result = create_masked_initialization(source, model, destination, **expected)
    assert result == destination
    assert load_parameter_set(destination).input_features == MASKED_FEATURE_NAMES
    with pytest.raises(FileExistsError):
        create_masked_initialization(source, model, destination, **expected)
    with pytest.raises(ValueError, match="model.*hash"):
        create_masked_initialization(source, model, tmp_path / "wrong-model",
                                     **{**expected, "expected_model_sha256": "f" * 64})
    with pytest.raises(ValueError, match="manifest.*hash"):
        create_masked_initialization(source, model, tmp_path / "wrong-manifest",
                                     **{**expected, "expected_manifest_sha256": "f" * 64})
    with pytest.raises(ValueError, match="parameters.*hash"):
        create_masked_initialization(source, model, tmp_path / "wrong-parameters",
                                     **{**expected, "expected_parameters_sha256": "f" * 64})
