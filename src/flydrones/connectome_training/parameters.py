from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path

import numpy as np

from flydrones.brain.connectome import Connectome

from .features import MASKED_FEATURE_NAMES

SCHEMA = "flydrones-connectome-parameters-v1"
ARRAY_KEYS = (
    "input_gain",
    "input_feature_index",
    "input_neuron_index",
    "output_neuron_index",
    "type_bias_mv",
    "tau_m_ms",
    "readout",
)
FULL_NEURONS = 166_700
FULL_CONNECTIONS = 25_582_837


@dataclass(frozen=True)
class StructureIdentity:
    label: str
    model_sha256: str
    topology_sha256: str
    neurons: int
    connections: int
    cell_types: tuple[str, ...]


@dataclass
class ParameterSet:
    identity: StructureIdentity
    input_features: tuple[str, ...]
    outputs: tuple[str, ...]
    input_gain: np.ndarray
    input_feature_index: np.ndarray
    input_neuron_index: np.ndarray
    output_neuron_index: np.ndarray
    type_bias_mv: np.ndarray
    tau_m_ms: float
    readout: np.ndarray


def parameter_mapping_digest(parameters: ParameterSet) -> str:
    """Preserve legacy identity while binding the ordered v3 feature profile."""
    digest = sha256()
    if parameters.input_features == MASKED_FEATURE_NAMES:
        digest.update(b"flydrones-feature-profile:depth-mask-v3\0")
        digest.update(json.dumps(MASKED_FEATURE_NAMES, separators=(",", ":")).encode("utf-8"))
    for value in (
        parameters.input_feature_index,
        parameters.input_neuron_index,
        parameters.output_neuron_index,
    ):
        array = np.ascontiguousarray(value, dtype="<i8")
        digest.update(array.tobytes())
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{name} must be a SHA-256 hex digest")


def _canonical_types(values: np.ndarray) -> tuple[np.ndarray, tuple[str, ...]]:
    ordered = np.asarray(
        [str(value) if str(value) else "__unknown__" for value in values], dtype=str
    )
    return ordered, tuple(sorted(set(ordered.tolist())))


def build_structure_identity(
    connectome: Connectome, model_sha256: str
) -> StructureIdentity:
    _validate_sha256("model_sha256", model_sha256)
    weights = connectome.weights.tocsc().astype(np.float32)
    weights.sum_duplicates()
    weights.eliminate_zeros()
    weights.sort_indices()
    if weights.shape[0] != weights.shape[1]:
        raise ValueError("connectome topology must be square")
    if weights.shape[0] != len(connectome.types):
        raise ValueError("neuron types must match topology size")
    if not np.isfinite(weights.data).all():
        raise ValueError("connectome weights contain non-finite values")

    ordered_types, cell_types = _canonical_types(connectome.types)
    digest = sha256()
    for array in (
        np.asarray(weights.shape, dtype="<i8"),
        np.asarray(weights.indptr, dtype="<i8"),
        np.asarray(weights.indices, dtype="<i8"),
        np.asarray(weights.data, dtype="<f4"),
    ):
        payload = np.ascontiguousarray(array).tobytes()
        digest.update(struct.pack("<Q", len(payload)))
        digest.update(payload)
    for value in ordered_types:
        payload = value.encode("utf-8")
        digest.update(struct.pack("<Q", len(payload)))
        digest.update(payload)
    return StructureIdentity(
        label=str(connectome.name),
        model_sha256=model_sha256.lower(),
        topology_sha256=digest.hexdigest(),
        neurons=int(weights.shape[0]),
        connections=int(weights.nnz),
        cell_types=cell_types,
    )


def _validate_full_identity(identity: StructureIdentity) -> None:
    if identity.label == "full-male-cns" and (
        identity.neurons != FULL_NEURONS
        or identity.connections != FULL_CONNECTIONS
    ):
        raise ValueError(
            "full-male-cns requires 166700 neurons and 25582837 connections"
        )


def _validate(parameters: ParameterSet) -> None:
    identity = parameters.identity
    _validate_sha256("model_sha256", identity.model_sha256)
    _validate_sha256("topology_sha256", identity.topology_sha256)
    _validate_full_identity(identity)
    if identity.neurons < 1 or identity.connections < 0 or not identity.cell_types:
        raise ValueError("structure identity has invalid dimensions")
    if not parameters.input_features or len(set(parameters.input_features)) != len(
        parameters.input_features
    ):
        raise ValueError("input_features must be non-empty and unique")
    if not parameters.outputs or len(set(parameters.outputs)) != len(parameters.outputs):
        raise ValueError("outputs must be non-empty and unique")
    input_gain = np.asarray(parameters.input_gain)
    input_feature_index = np.asarray(parameters.input_feature_index)
    input_neuron_index = np.asarray(parameters.input_neuron_index)
    output_neuron_index = np.asarray(parameters.output_neuron_index)
    type_bias = np.asarray(parameters.type_bias_mv)
    readout = np.asarray(parameters.readout)
    if input_gain.shape != (len(parameters.input_features),):
        raise ValueError("input_gain shape does not match input_features")
    if (
        input_feature_index.ndim != 1
        or input_neuron_index.shape != input_feature_index.shape
        or input_feature_index.size < 1
    ):
        raise ValueError("input feature and neuron mappings must be matching vectors")
    if np.any(input_feature_index < 0) or np.any(
        input_feature_index >= len(parameters.input_features)
    ):
        raise ValueError("input feature index is out of range")
    if (parameters.input_features == MASKED_FEATURE_NAMES
            and set(input_feature_index.tolist()) != set(range(len(MASKED_FEATURE_NAMES)))):
        raise ValueError("masked input feature coverage incomplete")
    if np.any(input_neuron_index < 0) or np.any(input_neuron_index >= identity.neurons):
        raise ValueError("input neuron index is out of range")
    if len(np.unique(input_neuron_index)) != len(input_neuron_index):
        raise ValueError("input neuron assignments must be unique")
    if type_bias.shape != (len(identity.cell_types),):
        raise ValueError("type_bias_mv shape does not match cell_types")
    if readout.ndim != 2 or readout.shape[0] != len(parameters.outputs):
        raise ValueError("readout shape does not match outputs")
    if readout.shape[1] < 1:
        raise ValueError("readout requires at least one output neuron")
    if output_neuron_index.shape != (readout.shape[1],):
        raise ValueError("output neuron mapping does not match readout")
    if np.any(output_neuron_index < 0) or np.any(
        output_neuron_index >= identity.neurons
    ):
        raise ValueError("output neuron index is out of range")
    if len(np.unique(output_neuron_index)) != len(output_neuron_index):
        raise ValueError("output neuron assignments must be unique")
    for name, value in (
        ("input_gain", input_gain),
        ("type_bias_mv", type_bias),
        ("tau_m_ms", np.asarray(parameters.tau_m_ms)),
        ("readout", readout),
    ):
        if not np.isfinite(value).all():
            raise ValueError(f"{name} contains non-finite values")
    if float(parameters.tau_m_ms) <= 0:
        raise ValueError("tau_m_ms must be positive")
    if np.any(input_gain <= 0):
        raise ValueError("input_gain must be positive")


def initial_parameter_set(
    identity: StructureIdentity,
    input_features: tuple[str, ...],
    outputs: tuple[str, ...],
    output_neurons: int | np.ndarray,
    *,
    input_feature_index: np.ndarray | None = None,
    input_neuron_index: np.ndarray | None = None,
    label: str | None = None,
) -> ParameterSet:
    if np.isscalar(output_neurons):
        output_count = int(output_neurons)
        if output_count < 1:
            raise ValueError("output_neurons must be positive")
        output_neuron_index = np.arange(output_count, dtype=np.int64)
    else:
        output_neuron_index = np.asarray(output_neurons, np.int64)
        if output_neuron_index.ndim != 1 or output_neuron_index.size < 1:
            raise ValueError("output_neurons must be a non-empty vector")
        output_count = int(output_neuron_index.size)
    if input_feature_index is None:
        input_feature_index = np.arange(len(input_features), dtype=np.int64)
    if input_neuron_index is None:
        input_neuron_index = np.arange(len(input_features), dtype=np.int64)
    if label is not None:
        identity = replace(identity, label=str(label))
    parameters = ParameterSet(
        identity=identity,
        input_features=tuple(input_features),
        outputs=tuple(outputs),
        input_gain=np.ones(len(input_features), np.float32),
        input_feature_index=np.asarray(input_feature_index, np.int64),
        input_neuron_index=np.asarray(input_neuron_index, np.int64),
        output_neuron_index=output_neuron_index,
        type_bias_mv=np.zeros(len(identity.cell_types), np.float32),
        tau_m_ms=20.0,
        readout=np.zeros((len(outputs), output_count), np.float32),
    )
    _validate(parameters)
    return parameters


def save_parameter_set(path: str | Path, parameters: ParameterSet) -> Path:
    _validate(parameters)
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    if path.exists() or temporary.exists():
        raise FileExistsError(path if path.exists() else temporary)
    temporary.mkdir(parents=True)
    arrays = temporary / "parameters.npz"
    np.savez_compressed(
        arrays,
        input_gain=np.asarray(parameters.input_gain, np.float32),
        input_feature_index=np.asarray(parameters.input_feature_index, np.int64),
        input_neuron_index=np.asarray(parameters.input_neuron_index, np.int64),
        output_neuron_index=np.asarray(parameters.output_neuron_index, np.int64),
        type_bias_mv=np.asarray(parameters.type_bias_mv, np.float32),
        tau_m_ms=np.asarray(parameters.tau_m_ms, np.float32),
        readout=np.asarray(parameters.readout, np.float32),
    )
    manifest = {
        "schema": SCHEMA,
        "identity": asdict(parameters.identity),
        "input_features": list(parameters.input_features),
        "outputs": list(parameters.outputs),
        "parameters_sha256": _file_digest(arrays),
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(path)
    return path


def load_parameter_set(path: str | Path) -> ParameterSet:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    arrays_path = path / "parameters.npz"
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported connectome parameter schema")
    if manifest.get("parameters_sha256") != _file_digest(arrays_path):
        raise ValueError("parameters.npz hash mismatch")
    identity_data = dict(manifest["identity"])
    identity_data["cell_types"] = tuple(identity_data["cell_types"])
    identity = StructureIdentity(**identity_data)
    with np.load(arrays_path, allow_pickle=False) as arrays:
        if set(arrays.files) != set(ARRAY_KEYS):
            raise ValueError("parameters.npz keys do not match the parameter contract")
        parameters = ParameterSet(
            identity=identity,
            input_features=tuple(manifest["input_features"]),
            outputs=tuple(manifest["outputs"]),
            input_gain=arrays["input_gain"].astype(np.float32, copy=True),
            input_feature_index=arrays["input_feature_index"].astype(np.int64, copy=True),
            input_neuron_index=arrays["input_neuron_index"].astype(np.int64, copy=True),
            output_neuron_index=arrays["output_neuron_index"].astype(np.int64, copy=True),
            type_bias_mv=arrays["type_bias_mv"].astype(np.float32, copy=True),
            tau_m_ms=float(arrays["tau_m_ms"]),
            readout=arrays["readout"].astype(np.float32, copy=True),
        )
    _validate(parameters)
    return parameters
