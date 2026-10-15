"""Load a CPU learned core without an optimizer or flight authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import torch

from flydrones.benchmark.provenance import sha256_file
from flydrones.brain.connectome import Connectome

from .checkpoint import load_checkpoint
from .features import feature_profile_for_names
from .model import (
    ConnectomeConstrainedCore,
    dynamics_identity_suffix,
    topology_identity_suffix,
    validate_dynamics_backend,
    validate_topology_backend,
)
from .parameters import FULL_CONNECTIONS, FULL_NEURONS, load_parameter_set, parameter_mapping_digest
from .training_roles import (
    capture_learning_initialization,
    configure_learning_roles,
    initialization_identity_suffix,
    learning_identity_suffix,
    learning_parameters,
    validate_learning_state,
)

OUTPUT_NAMES = ("vx", "vy", "vz", "yaw_rate")


@dataclass(frozen=True)
class CheckpointIdentity:
    checkpoint_sha256: str
    config_digest: str
    dataset_sha256: str

    def __post_init__(self):
        for value in (self.checkpoint_sha256, self.config_digest, self.dataset_sha256):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("checkpoint identity requires lowercase SHA256 hashes")


@dataclass(frozen=True)
class LoadedInferenceCore:
    core: ConnectomeConstrainedCore
    provenance: dict


def load_inference_core(
    model_path: str | Path,
    parameters_path: str | Path,
    *,
    mode: str = "full-male-cns",
    checkpoint_path: str | Path | None = None,
    checkpoint_identity: CheckpointIdentity | None = None,
    learning_profile: str | None = None,
    topology_format: str = "coo_reference",
    dynamics_format: str = "clipped-euler-v1",
) -> LoadedInferenceCore:
    """Ordinary file-drift detection, not hostile-concurrent-mutation protection.

    Returned model/provenance are owned by one offline caller, not a security
    boundary against a caller mutating Python objects after loading.
    """
    topology_suffix = topology_identity_suffix(topology_format)
    dynamics_suffix = dynamics_identity_suffix(dynamics_format)
    if mode not in {"full-male-cns", "tiny-fixture"}:
        raise ValueError("unsupported inference mode")
    if learning_profile is not None:
        learning_parameters(learning_profile)
        if checkpoint_path is None:
            raise ValueError("learning profile requires a role-bound checkpoint")
    if (checkpoint_path is None) != (checkpoint_identity is None):
        raise ValueError("checkpoint path and identity must be supplied together")
    if checkpoint_identity is not None and not isinstance(checkpoint_identity, CheckpointIdentity):
        raise ValueError("checkpoint identity must be CheckpointIdentity")
    source, parameters_path = Path(model_path), Path(parameters_path)
    files = {
        "source": source,
        "parameters": parameters_path / "parameters.npz",
        "parameter_manifest": parameters_path / "manifest.json",
    }
    if checkpoint_path is not None:
        checkpoint_path = Path(checkpoint_path)
        files.update(checkpoint=checkpoint_path / "checkpoint.pt", checkpoint_manifest=checkpoint_path / "manifest.json")
    before = {role: sha256_file(path) for role, path in files.items()}
    parameters = load_parameter_set(parameters_path)
    identity = parameters.identity
    if before["source"] != identity.model_sha256:
        raise ValueError("source hash does not match parameter identity")
    if mode == "full-male-cns":
        if identity.label != "full-male-cns" or identity.neurons != FULL_NEURONS or identity.connections != FULL_CONNECTIONS:
            raise ValueError("full MaleCNS identity required")
    elif identity.label == "full-male-cns" or identity.neurons > 1024:
        raise ValueError("tiny fixture requires a non-full model of at most 1024 neurons")
    if parameters.outputs != OUTPUT_NAMES:
        raise ValueError("feature/output order does not match inference contract")
    feature_profile = feature_profile_for_names(parameters.input_features)
    mapping = parameter_mapping_digest(parameters)
    model_mode = "full-male-cns" if mode == "full-male-cns" else "tiny-connectome"
    model_identity = (
        f"{model_mode}:{identity.model_sha256}:{identity.topology_sha256}:{mapping}:device=cpu"
        + topology_suffix
        + dynamics_suffix
    )
    checkpoint = None
    if checkpoint_identity is not None:
        if before["checkpoint"] != checkpoint_identity.checkpoint_sha256:
            raise ValueError("checkpoint hash does not match pinned identity")
        expected_metadata = {
            "config_digest": checkpoint_identity.config_digest,
            "dataset_sha256": checkpoint_identity.dataset_sha256,
            "topology_sha256": identity.topology_sha256,
            "parameter_mapping_sha256": mapping,
            **({"topology_format": topology_format} if topology_format != "coo_reference" else {}),
            **({"dynamics_format": dynamics_format} if dynamics_format != "clipped-euler-v1" else {}),
        }
        if learning_profile is None:
            expected_metadata["model_identity"] = model_identity
        checkpoint = load_checkpoint(checkpoint_path, expected_metadata=expected_metadata)
        if checkpoint["metadata"].get("topology_format", "coo_reference") != topology_format:
            raise ValueError("checkpoint metadata mismatch: topology_format")
        if checkpoint["metadata"].get("dynamics_format", "clipped-euler-v1") != dynamics_format:
            raise ValueError("checkpoint metadata mismatch: dynamics_format")
        if learning_profile is not None:
            declared = checkpoint["metadata"].get("learning_roles")
            if not isinstance(declared, dict) or declared.get("profile") != learning_profile:
                raise ValueError("checkpoint metadata mismatch: learning_roles")
    # Construction verifies the signed topology and neuron type order against
    # the parameter identity. No checkpoint can provide these fixed buffers.
    backend = {} if topology_format == "coo_reference" else {"topology_format": topology_format}
    if dynamics_format != "clipped-euler-v1":
        backend["dynamics_format"] = dynamics_format
    core = ConnectomeConstrainedCore(Connectome.load(source), parameters, **backend)
    validate_topology_backend(core, topology_format)
    validate_dynamics_backend(core, dynamics_format)
    roles = None
    initialization = None
    if learning_profile is not None:
        roles = configure_learning_roles(core, learning_profile)
        model_identity += learning_identity_suffix(roles)
        if "learning_initialization" in checkpoint["metadata"]:
            initialization = capture_learning_initialization(core)
            if checkpoint["metadata"]["learning_initialization"] != initialization:
                raise ValueError("checkpoint metadata mismatch: learning_initialization")
            model_identity += initialization_identity_suffix(initialization)
        for key, value in {"model_identity": model_identity, "learning_roles": roles}.items():
            if checkpoint["metadata"].get(key) != value:
                raise ValueError(f"checkpoint metadata mismatch: {key}")
    named = dict(core.named_parameters())
    if checkpoint is not None:
        values = checkpoint["model_state"]
        if roles is not None:
            validate_learning_state(core, values, roles)
        if not isinstance(values, dict) or set(values) != set(named):
            raise ValueError("checkpoint parameter names do not match core")
        for name, value in values.items():
            if (
                not isinstance(value, torch.Tensor)
                or value.device.type != "cpu"
                or value.layout != torch.strided
                or value.dtype != named[name].dtype
                or value.shape != named[name].shape
                or not torch.isfinite(value).all()
            ):
                raise ValueError(f"checkpoint parameter invalid: {name}")
        with torch.no_grad():
            for name, value in values.items():
                named[name].copy_(value)
    if (
        not all(torch.isfinite(value).all().item() for value in core.parameters())
        or not torch.isfinite(core.input_gain).all()
        or not torch.all(core.input_gain > 0)
        or not torch.isfinite(core.tau_m_ms).all()
        or not torch.all(core.tau_m_ms > 1)
    ):
        raise ValueError("effective core parameters are invalid")
    core.eval()
    core.requires_grad_(False)
    after = {role: sha256_file(path) for role, path in files.items()}
    if after != before:
        raise ValueError("inference input files changed while loading")
    frozen_coefficients_prepared = core.prepare_frozen_inference()
    return LoadedInferenceCore(
        core,
        {
            "core_kind": "connectome-constrained-rate-core",
            "mode": mode,
            "topology_format": topology_format,
            "dynamics_format": dynamics_format,
            "model_identity": model_identity,
            "neurons": identity.neurons,
            "connections": identity.connections,
            "model_sha256": identity.model_sha256,
            "topology_sha256": identity.topology_sha256,
            "parameter_mapping_sha256": mapping,
            "feature_profile": feature_profile,
            "full_topology": mode == "full-male-cns",
            "parameter_origin": "checkpoint-parameters" if checkpoint is not None else "initialization-only",
            "learning_profile": learning_profile
            if roles is not None
            else ("legacy-unspecified" if checkpoint is not None else None),
            "learning_roles": roles,
            "learning_initialization": initialization,
            "validation_baseline_verified": False,  # Offline coefficient loading has no validation dataset.
            "checkpoint_sha256": before.get("checkpoint"),
            "files": {role: {"path": str(path.resolve()), "sha256": before[role]} for role, path in files.items()},
            "files_stable": True,
            "frozen_coefficients_prepared": frozen_coefficients_prepared,
            "training_success_verified": False,
            "flight_eligible": False,
            "torch_version": torch.__version__,
        },
    )
