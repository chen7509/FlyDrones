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
from .model import ConnectomeConstrainedCore
from .parameters import FULL_CONNECTIONS, FULL_NEURONS, load_parameter_set, parameter_mapping_digest

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
) -> LoadedInferenceCore:
    """Ordinary file-drift detection, not hostile-concurrent-mutation protection.

    Returned model/provenance are owned by one offline caller, not a security
    boundary against a caller mutating Python objects after loading.
    """
    if mode not in {"full-male-cns", "tiny-fixture"}:
        raise ValueError("unsupported inference mode")
    if (checkpoint_path is None) != (checkpoint_identity is None):
        raise ValueError("checkpoint path and identity must be supplied together")
    if checkpoint_identity is not None and not isinstance(checkpoint_identity, CheckpointIdentity):
        raise ValueError("checkpoint identity must be CheckpointIdentity")
    source, parameters_path = Path(model_path), Path(parameters_path)
    files = {"source": source, "parameters": parameters_path / "parameters.npz",
             "parameter_manifest": parameters_path / "manifest.json"}
    if checkpoint_path is not None:
        checkpoint_path = Path(checkpoint_path)
        files.update(checkpoint=checkpoint_path / "checkpoint.pt",
                     checkpoint_manifest=checkpoint_path / "manifest.json")
    before = {role: sha256_file(path) for role, path in files.items()}
    parameters = load_parameter_set(parameters_path)
    identity = parameters.identity
    if before["source"] != identity.model_sha256:
        raise ValueError("source hash does not match parameter identity")
    if mode == "full-male-cns":
        if (identity.label != "full-male-cns" or identity.neurons != FULL_NEURONS
                or identity.connections != FULL_CONNECTIONS):
            raise ValueError("full MaleCNS identity required")
    elif identity.label == "full-male-cns" or identity.neurons > 1024:
        raise ValueError("tiny fixture requires a non-full model of at most 1024 neurons")
    if parameters.outputs != OUTPUT_NAMES:
        raise ValueError("feature/output order does not match inference contract")
    feature_profile = feature_profile_for_names(parameters.input_features)
    mapping = parameter_mapping_digest(parameters)
    model_mode = "full-male-cns" if mode == "full-male-cns" else "tiny-connectome"
    model_identity = f"{model_mode}:{identity.model_sha256}:{identity.topology_sha256}:{mapping}:device=cpu"
    checkpoint = None
    if checkpoint_identity is not None:
        if before["checkpoint"] != checkpoint_identity.checkpoint_sha256:
            raise ValueError("checkpoint hash does not match pinned identity")
        checkpoint = load_checkpoint(checkpoint_path, expected_metadata={
            "config_digest": checkpoint_identity.config_digest,
            "dataset_sha256": checkpoint_identity.dataset_sha256,
            "model_identity": model_identity,
            "topology_sha256": identity.topology_sha256,
            "parameter_mapping_sha256": mapping,
        })
    # Construction verifies the signed topology and neuron type order against
    # the parameter identity. No checkpoint can provide these fixed buffers.
    core = ConnectomeConstrainedCore(Connectome.load(source), parameters)
    named = dict(core.named_parameters())
    if checkpoint is not None:
        values = checkpoint["model_state"]
        if not isinstance(values, dict) or set(values) != set(named):
            raise ValueError("checkpoint parameter names do not match core")
        for name, value in values.items():
            if (not isinstance(value, torch.Tensor) or value.device.type != "cpu"
                    or value.layout != torch.strided or value.dtype != named[name].dtype
                    or value.shape != named[name].shape or not torch.isfinite(value).all()):
                raise ValueError(f"checkpoint parameter invalid: {name}")
        with torch.no_grad():
            for name, value in values.items():
                named[name].copy_(value)
    if (not all(torch.isfinite(value).all().item() for value in core.parameters())
            or not torch.isfinite(core.input_gain).all() or not torch.all(core.input_gain > 0)
            or not torch.isfinite(core.tau_m_ms).all() or not torch.all(core.tau_m_ms > 1)):
        raise ValueError("effective core parameters are invalid")
    core.eval()
    core.requires_grad_(False)
    after = {role: sha256_file(path) for role, path in files.items()}
    if after != before:
        raise ValueError("inference input files changed while loading")
    return LoadedInferenceCore(core, {
        "core_kind": "connectome-constrained-rate-core",
        "mode": mode, "model_identity": model_identity,
        "neurons": identity.neurons, "connections": identity.connections,
        "model_sha256": identity.model_sha256,
        "topology_sha256": identity.topology_sha256,
        "parameter_mapping_sha256": mapping,
        "feature_profile": feature_profile,
        "full_topology": mode == "full-male-cns",
        "parameter_origin": "checkpoint-parameters" if checkpoint is not None else "initialization-only",
        "checkpoint_sha256": before.get("checkpoint"),
        "files": {role: {"path": str(path.resolve()), "sha256": before[role]} for role, path in files.items()},
        "files_stable": True, "training_success_verified": False,
        "flight_eligible": False, "torch_version": torch.__version__,
    })
