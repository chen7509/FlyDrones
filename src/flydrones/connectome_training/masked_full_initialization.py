"""Derive an untrained v3 input mapping from a frozen full-model initialization."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np

from .features import FEATURE_NAMES, MASKED_FEATURE_NAMES
from .parameters import (
    ParameterSet,
    _validate,
    initial_parameter_set,
    load_parameter_set,
    parameter_mapping_digest,
    save_parameter_set,
)

OUTPUT_NAMES = ("vx", "vy", "vz", "yaw_rate")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_masked_initialization(source: ParameterSet) -> ParameterSet:
    """Return new default parameters; never transfer trainable values from source."""
    _validate(source)
    if source.identity.label != "full-male-cns":
        raise ValueError("source must be a full-male-cns initialization")
    if source.input_features != FEATURE_NAMES or source.outputs != OUTPUT_NAMES:
        raise ValueError("source must have the frozen legacy feature and output order")
    count = int(source.input_neuron_index.size)
    if count < len(MASKED_FEATURE_NAMES) or not np.array_equal(
        source.input_feature_index, np.arange(count) % len(FEATURE_NAMES)
    ):
        raise ValueError("source sensory mapping is not the frozen legacy mapping")
    if (not np.array_equal(source.input_gain, np.ones(len(FEATURE_NAMES), np.float32))
            or not np.all(source.type_bias_mv == 0)
            or source.tau_m_ms != 20.0
            or not np.all(source.readout == 0)):
        raise ValueError("source contains modified or trained parameters")
    return initial_parameter_set(
        source.identity,
        MASKED_FEATURE_NAMES,
        source.outputs,
        source.output_neuron_index.copy(),
        input_feature_index=np.arange(count) % len(MASKED_FEATURE_NAMES),
        input_neuron_index=source.input_neuron_index.copy(),
    )


def create_masked_initialization(
    source_dir: Path,
    model_path: Path,
    destination: Path,
    *,
    expected_manifest_sha256: str,
    expected_parameters_sha256: str,
    expected_model_sha256: str,
) -> Path:
    """Verify pinned input bytes and create a separately named parameter artifact."""
    source_dir, model_path, destination = map(Path, (source_dir, model_path, destination))
    if destination.exists() or destination.with_name(destination.name + ".writing").exists():
        raise FileExistsError(destination)
    manifest_path = source_dir / "manifest.json"
    arrays_path = source_dir / "parameters.npz"
    for name, path, expected in (
        ("manifest", manifest_path, expected_manifest_sha256),
        ("parameters", arrays_path, expected_parameters_sha256),
        ("model", model_path, expected_model_sha256),
    ):
        if _sha256_file(path) != expected:
            raise ValueError(f"{name} hash does not match frozen source")
    source = load_parameter_set(source_dir)
    if source.identity.model_sha256 != expected_model_sha256:
        raise ValueError("model hash does not match parameter identity")
    result = derive_masked_initialization(source)
    if (_sha256_file(manifest_path) != expected_manifest_sha256
            or _sha256_file(arrays_path) != expected_parameters_sha256):
        raise ValueError("source changed during load")
    save_parameter_set(destination, result)
    reloaded = load_parameter_set(destination)
    if (reloaded.identity != result.identity
            or reloaded.input_features != MASKED_FEATURE_NAMES
            or parameter_mapping_digest(reloaded) != parameter_mapping_digest(result)):
        raise ValueError("saved masked parameter mapping did not verify")
    return destination
