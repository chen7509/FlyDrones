from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import random

import numpy as np
from scipy import sparse
import torch

from flydrones.brain.connectome import Connectome

from .checkpoint import load_checkpoint, restore_rng_state, save_checkpoint
from .curriculum_config import CurriculumConfig, CurriculumStage
from .dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    load_sequence,
)
from .features import FEATURE_NAMES, sequence_tensors
from .governance import validate_dataset_partitions
from .losses import LossWeights
from .model import ConnectomeConstrainedCore
from .parameters import ParameterSet, build_structure_identity, initial_parameter_set, load_parameter_set
from .trainer import evaluate_sequences, train_epoch

OUTPUT_NAMES = ("vx", "vy", "vz", "yaw_rate")


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError(f"unsupported device: {requested}")
    return torch.device(requested)


def _mapping_digest(parameters: ParameterSet) -> str:
    digest = sha256()
    for value in (
        parameters.input_feature_index,
        parameters.input_neuron_index,
        parameters.output_neuron_index,
    ):
        array = np.ascontiguousarray(value, dtype="<i8")
        digest.update(array.tobytes())
    return digest.hexdigest()


def _dataset_digest(datasets: dict[str, tuple[list[TrainingSequence], list[TrainingSequence]]]) -> str:
    digest = sha256()
    for stage_id in sorted(datasets):
        digest.update(stage_id.encode("utf-8"))
        for partition in datasets[stage_id]:
            for sequence in partition:
                digest.update(
                    json.dumps(
                        {
                            "split": sequence.provenance.split,
                            "seed": sequence.provenance.seed,
                            "world_sha256": sequence.provenance.world_sha256,
                            "teacher": sequence.provenance.teacher,
                        },
                        sort_keys=True,
                    ).encode("utf-8")
                )
                for tensor in sequence_tensors(sequence):
                    digest.update(np.ascontiguousarray(tensor.numpy()).tobytes())
    return digest.hexdigest()


def _synthetic_sequence(stage: CurriculumStage, split: str, seed: int) -> TrainingSequence:
    variant = (seed % 23) / 100.0
    stage_offset = stage.order * 0.015
    frames = []
    targets = []
    for index in range(8):
        phase = index / 7.0
        frames.append(
            SequenceFrame(
                (index + 1) * 50_000_000,
                (index + 1) * 50_000_000,
                np.full((6, 9, 3), 35 + index * 3 + seed % 11, np.uint8),
                np.full((6, 9), 1.4 + variant + phase * 0.7, np.float32),
                np.array([phase, variant, 1.0], np.float32),
                np.array([0.2, 0.0, 0.0], np.float32),
                stage_offset,
                0.0,
                np.array([5.0, -variant, 1.0], np.float32),
            )
        )
        targets.append(
            TeacherTarget(
                np.array(
                    [0.32 + phase * 0.06, variant + stage_offset, 0.0],
                    np.float32,
                ),
                stage_offset,
                np.array([[1.0 + phase, 0.0, 1.0]], np.float32),
                0.75 + phase * 0.1,
                index == 7,
            )
        )
    provenance = SequenceProvenance(
        split,
        seed,
        "deterministic-curriculum-smoke-v1",
        sha256(f"{stage.id}:{split}:{seed}:world".encode()).hexdigest(),
        sha256(f"{stage.id}:{split}:config".encode()).hexdigest(),
        "synthetic-connectome-curriculum-smoke",
    )
    return TrainingSequence(provenance, frames, targets)


def _smoke_components(
    config: CurriculumConfig,
) -> tuple[Connectome, ParameterSet, dict[str, tuple[list[TrainingSequence], list[TrainingSequence]]]]:
    neurons = len(FEATURE_NAMES) + len(OUTPUT_NAMES)
    connectome = Connectome(
        "curriculum-smoke",
        sparse.eye(neurons, format="csc", dtype=np.float32),
        np.array(["sensory"] * len(FEATURE_NAMES) + ["descending"] * 4),
        np.array([""] * neurons),
    )
    identity = build_structure_identity(connectome, "c" * 64)
    parameters = initial_parameter_set(
        identity,
        FEATURE_NAMES,
        OUTPUT_NAMES,
        np.arange(neurons - 4, neurons),
    )
    datasets = {
        stage.id: (
            [_synthetic_sequence(stage, "train", seed) for seed in stage.train_seeds],
            [
                _synthetic_sequence(stage, "val", seed)
                for seed in stage.validation_seeds
            ],
        )
        for stage in config.stages
    }
    return connectome, parameters, datasets


def _sequence_directories(paths: tuple[str, ...]) -> list[TrainingSequence]:
    sequence_paths: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"sequence evidence path does not exist: {path}")
        if (path / "manifest.json").is_file():
            sequence_paths.append(path)
        elif path.is_dir():
            sequence_paths.extend(
                sorted(item.parent for item in path.rglob("manifest.json"))
            )
    if not sequence_paths:
        raise ValueError("sequence evidence paths contain no sequence manifests")
    return [load_sequence(path) for path in sequence_paths]


def _full_components(
    config: CurriculumConfig,
    connectome_path: Path,
    parameters_path: Path,
) -> tuple[Connectome, ParameterSet, dict[str, tuple[list[TrainingSequence], list[TrainingSequence]]]]:
    datasets = {}
    for stage in config.stages:
        train = _sequence_directories(stage.train_paths)
        validation = _sequence_directories(stage.validation_paths)
        if {item.provenance.seed for item in train} != set(stage.train_seeds):
            raise ValueError(f"stage {stage.id} training sequence seeds do not match config")
        if {item.provenance.seed for item in validation} != set(stage.validation_seeds):
            raise ValueError(f"stage {stage.id} validation sequence seeds do not match config")
        validate_dataset_partitions(
            [item.provenance for item in train],
            [item.provenance for item in validation],
        )
        datasets[stage.id] = (train, validation)
    if not connectome_path.is_file():
        raise FileNotFoundError(f"connectome source does not exist: {connectome_path}")
    parameters = load_parameter_set(parameters_path)
    if parameters.identity.label != "full-male-cns":
        raise ValueError("complete curriculum requires a full-male-cns parameter artifact")
    connectome = Connectome.load(connectome_path)
    return connectome, parameters, datasets


class ConnectomeCurriculumSession:
    def __init__(
        self,
        config: CurriculumConfig,
        *,
        device: str | None = None,
        learning_rate: float = 0.03,
        truncate_steps: int = 4,
        connectome_path: str | Path = "data/malecns_full.npz",
        parameters_path: str | Path = "results/connectome-training/stage-b/full-initialization",
    ):
        if learning_rate <= 0 or truncate_steps < 1:
            raise ValueError("learning rate and truncate steps must be positive")
        if config.profile.data_mode == "synthetic-smoke":
            connectome, parameters, datasets = _smoke_components(config)
        else:
            connectome, parameters, datasets = _full_components(
                config, Path(connectome_path), Path(parameters_path)
            )
        for train, validation in datasets.values():
            validate_dataset_partitions(
                [item.provenance for item in train],
                [item.provenance for item in validation],
            )
        self.config = config
        self.datasets = datasets
        self.parameters = parameters
        self.device = resolve_device(device or config.profile.device)
        self.model = ConnectomeConstrainedCore(connectome, parameters).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        self.truncate_steps = truncate_steps
        self.loss_weights = LossWeights()
        self.dataset_sha256 = _dataset_digest(datasets)
        self.mapping_sha256 = _mapping_digest(parameters)
        self.model_identity = (
            f"{config.profile.model_mode}:{parameters.identity.topology_sha256}:"
            f"{self.mapping_sha256}:device={self.device.type}"
        )
        self.initial_losses = {
            stage.id: evaluate_sequences(
                self.model,
                datasets[stage.id][1],
                self.truncate_steps,
                weights=self.loss_weights,
            )["total"]
            for stage in config.stages
        }

    def train_batch(self, stage: CurriculumStage, seed: int) -> dict[str, int | float]:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        # Rehearse every completed skill while learning the current one. The
        # coordinator still evaluates and gates each stage independently.
        train = [
            sequence
            for configured in self.config.stages
            if configured.order <= stage.order
            for sequence in self.datasets[configured.id][0]
        ]
        metrics = {}
        for _ in range(stage.epochs_per_batch):
            metrics = train_epoch(
                self.model,
                train,
                self.optimizer,
                self.truncate_steps,
                weights=self.loss_weights,
            )
        frames = sum(len(sequence.frames) for sequence in train)
        return {
            "updates": stage.epochs_per_batch,
            "environment_steps": frames * stage.epochs_per_batch,
            "train_loss": float(metrics["total"]),
        }

    def evaluate(self, stage: CurriculumStage) -> dict[str, float | bool]:
        result = evaluate_sequences(
            self.model,
            self.datasets[stage.id][1],
            self.truncate_steps,
            weights=self.loss_weights,
        )
        finite = all(
            torch.isfinite(parameter).all().item()
            for parameter in self.model.parameters()
        )
        return {
            "validation_loss": float(result["total"]),
            "initial_validation_loss": float(self.initial_losses[stage.id]),
            "parameters_finite": finite,
        }

    def save_checkpoint(self, path: Path, metadata: dict) -> None:
        enriched = {
            **metadata,
            "epoch": int(metadata["stage_index"]) * 100_000
            + int(metadata["batch_index"])
            + 1,
            "dataset_sha256": self.dataset_sha256,
            "topology_sha256": self.parameters.identity.topology_sha256,
            "parameter_mapping_sha256": self.mapping_sha256,
        }
        trainable = {
            name: parameter.detach().cpu().clone()
            for name, parameter in self.model.named_parameters()
        }
        save_checkpoint(
            path,
            model_state=trainable,
            optimizer_state=self.optimizer.state_dict(),
            metadata=enriched,
        )

    def restore_checkpoint(self, path: Path) -> None:
        payload = load_checkpoint(
            path,
            expected_metadata={
                "config_digest": self.config.digest,
                "model_identity": self.model_identity,
                "dataset_sha256": self.dataset_sha256,
                "topology_sha256": self.parameters.identity.topology_sha256,
                "parameter_mapping_sha256": self.mapping_sha256,
            },
        )
        named = dict(self.model.named_parameters())
        if set(payload["model_state"]) != set(named):
            raise ValueError("checkpoint trainable parameter names do not match model")
        with torch.no_grad():
            for name, value in payload["model_state"].items():
                if named[name].shape != value.shape:
                    raise ValueError(f"checkpoint parameter shape mismatch: {name}")
                named[name].copy_(value.to(named[name].device))
        self.optimizer.load_state_dict(payload["optimizer_state"])
        restore_rng_state(payload["rng_state"])
