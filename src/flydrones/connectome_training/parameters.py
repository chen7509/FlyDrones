from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import struct

import numpy as np

from flydrones.brain.connectome import Connectome

SCHEMA = "flydrones-connectome-parameters-v1"
ARRAY_KEYS = ("input_gain", "type_bias_mv", "tau_m_ms", "readout")
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
    type_bias_mv: np.ndarray
    tau_m_ms: float
    readout: np.ndarray


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
    type_bias = np.asarray(parameters.type_bias_mv)
    readout = np.asarray(parameters.readout)
    if input_gain.shape != (len(parameters.input_features),):
        raise ValueError("input_gain shape does not match input_features")
    if type_bias.shape != (len(identity.cell_types),):
        raise ValueError("type_bias_mv shape does not match cell_types")
    if readout.ndim != 2 or readout.shape[0] != len(parameters.outputs):
        raise ValueError("readout shape does not match outputs")
    if readout.shape[1] < 1:
        raise ValueError("readout requires at least one output neuron")
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
    output_neurons: int,
    *,
    label: str | None = None,
) -> ParameterSet:
    if output_neurons < 1:
        raise ValueError("output_neurons must be positive")
    if label is not None:
        identity = replace(identity, label=str(label))
    parameters = ParameterSet(
        identity=identity,
        input_features=tuple(input_features),
        outputs=tuple(outputs),
        input_gain=np.ones(len(input_features), np.float32),
        type_bias_mv=np.zeros(len(identity.cell_types), np.float32),
        tau_m_ms=20.0,
        readout=np.zeros((len(outputs), output_neurons), np.float32),
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
            type_bias_mv=arrays["type_bias_mv"].astype(np.float32, copy=True),
            tau_m_ms=float(arrays["tau_m_ms"]),
            readout=arrays["readout"].astype(np.float32, copy=True),
        )
    _validate(parameters)
    return parameters
