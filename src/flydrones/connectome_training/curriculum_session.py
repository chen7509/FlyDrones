from __future__ import annotations

import json
import os
import random
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from hashlib import sha256
from itertools import chain
from pathlib import Path

import numpy as np
import torch
from scipy import sparse

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
from .features import FEATURE_NAMES, feature_profile_for_names, sequence_tensors
from .governance import validate_dataset_partitions
from .losses import LossWeights
from .model import (
    ConnectomeConstrainedCore,
    dynamics_identity_suffix,
    topology_identity_suffix,
    validate_dynamics_backend,
    validate_topology_backend,
)
from .parameters import (
    ParameterSet,
    build_structure_identity,
    initial_parameter_set,
    load_parameter_set,
    parameter_mapping_digest,
)
from .sequence_corpus import FileSequenceCorpus
from .trainer import evaluate_sequences, train_epoch
from .training_roles import (
    DEFAULT_LEARNING_PROFILE,
    capture_learning_initialization,
    configure_learning_roles,
    initialization_identity_suffix,
    learning_identity_suffix,
    learning_parameters,
    validate_learning_optimizer_state,
    validate_learning_setup,
    validate_learning_state,
)

OUTPUT_NAMES = ("vx", "vy", "vz", "yaw_rate")


def verify_source_digest(path: str | Path, expected_sha256: str) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256.lower():
        raise ValueError("complete MaleCNS source hash does not match parameter identity")
    return actual


def _peak_process_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        process = get_current_process()
        if not get_memory(process, ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize)
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if __import__("sys").platform == "darwin" else value * 1024


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError(f"unsupported device: {requested}")
    return torch.device(requested)


def _dataset_digest(
    datasets: dict[str, tuple[Iterable[TrainingSequence], Iterable[TrainingSequence]]],
    profile: str,
) -> str:
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
                for tensor in sequence_tensors(sequence, profile=profile):
                    digest.update(np.ascontiguousarray(tensor.numpy()).tobytes())
                del sequence, tensor
    return digest.hexdigest()


def _validate_profile_sequences(sequences: Iterable[TrainingSequence], profile: str) -> None:
    for sequence in sequences:
        try:
            sequence_tensors(sequence, profile=profile)
        except ValueError as exc:
            raise ValueError(f"{profile} sequence feature contract invalid") from exc
        del sequence


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
            [_synthetic_sequence(stage, "val", seed) for seed in stage.validation_seeds],
        )
        for stage in config.stages
    }
    return connectome, parameters, datasets


def _sequence_directories(paths: tuple[str, ...]) -> FileSequenceCorpus:
    return FileSequenceCorpus(paths, loader=load_sequence)


def _provenances(partition):
    if isinstance(partition, FileSequenceCorpus):
        return [row.provenance for row in partition.summaries]
    return [sequence.provenance for sequence in partition]


def _frame_count(partition):
    if isinstance(partition, FileSequenceCorpus):
        return partition.frame_count
    # Other reiterable protocols are used only by explicit software fixtures.
    if hasattr(partition, "frame_count"):
        return partition.frame_count
    return sum(len(sequence.frames) for sequence in partition)


def _full_components(
    config: CurriculumConfig,
    connectome_path: Path,
    parameters_path: Path,
) -> tuple[Connectome, ParameterSet, dict[str, tuple[FileSequenceCorpus, FileSequenceCorpus]]]:
    datasets = {}
    for stage in config.stages:
        train = _sequence_directories(stage.train_paths)
        validation = _sequence_directories(stage.validation_paths)
        if Counter(item.seed for item in _provenances(train)) != Counter(stage.train_seeds):
            raise ValueError(f"stage {stage.id} requires exactly one sequence per training seed")
        if Counter(item.seed for item in _provenances(validation)) != Counter(stage.validation_seeds):
            raise ValueError(f"stage {stage.id} requires exactly one sequence per validation seed")
        validate_dataset_partitions(
            _provenances(train),
            _provenances(validation),
        )
        datasets[stage.id] = (train, validation)
    if not connectome_path.is_file():
        raise FileNotFoundError(f"connectome source does not exist: {connectome_path}")
    parameters = load_parameter_set(parameters_path)
    if parameters.identity.label != "full-male-cns":
        raise ValueError("complete curriculum requires a full-male-cns parameter artifact")
    profile = feature_profile_for_names(parameters.input_features)
    for train, validation in datasets.values():
        _validate_profile_sequences(chain(train, validation), profile)
    verify_source_digest(connectome_path, parameters.identity.model_sha256)
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
        learning_profile: str = DEFAULT_LEARNING_PROFILE,
        topology_format: str = "coo_reference",
        dynamics_format: str = "clipped-euler-v1",
    ):
        learning_parameters(learning_profile)
        topology_suffix = topology_identity_suffix(topology_format)
        self._topology_format = topology_format
        dynamics_suffix = dynamics_identity_suffix(dynamics_format)
        self._dynamics_format = dynamics_format
        if learning_rate <= 0 or truncate_steps < 1:
            raise ValueError("learning rate and truncate steps must be positive")
        if config.profile.data_mode == "synthetic-smoke":
            connectome, parameters, datasets = _smoke_components(config)
        else:
            connectome, parameters, datasets = _full_components(config, Path(connectome_path), Path(parameters_path))
        for train, validation in datasets.values():
            validate_dataset_partitions(
                _provenances(train),
                _provenances(validation),
            )
        self.config = config
        self.datasets = datasets
        self.parameters = parameters
        self.feature_profile = feature_profile_for_names(parameters.input_features)
        self.device = resolve_device(device or config.profile.device)
        backend = {} if topology_format == "coo_reference" else {"topology_format": topology_format}
        if dynamics_format != "clipped-euler-v1":
            backend["dynamics_format"] = dynamics_format
        self.model = ConnectomeConstrainedCore(connectome, parameters, **backend).to(self.device)
        self.learning_roles = configure_learning_roles(self.model, learning_profile)
        self.learning_initialization = capture_learning_initialization(self.model)
        self._initialization_json = json.dumps(self.learning_initialization, sort_keys=True, allow_nan=False)
        named = dict(self.model.named_parameters())
        self.optimizer = torch.optim.Adam([named[name] for name in self.learning_roles["trainable"]], lr=learning_rate)
        self.truncate_steps = truncate_steps
        self.loss_weights = LossWeights()
        self.dataset_sha256 = _dataset_digest(datasets, self.feature_profile)
        self.mapping_sha256 = parameter_mapping_digest(parameters)
        self.model_identity = (
            (
                f"{config.profile.model_mode}:{parameters.identity.model_sha256}:"
                f"{parameters.identity.topology_sha256}:"
                f"{self.mapping_sha256}:device={self.device.type}"
            )
            + topology_suffix
            + dynamics_suffix
            + learning_identity_suffix(self.learning_roles)
            + initialization_identity_suffix(self.learning_initialization)
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
        self._validation_baseline_json = self._baseline_json()

    def _baseline_json(self) -> str:
        return json.dumps(
            dict(
                schema="connectome-validation-baseline-v1",
                initial_losses=self.initial_losses,
                truncate_steps=self.truncate_steps,
                loss_weights=asdict(self.loss_weights),
            ),
            sort_keys=True,
            allow_nan=False,
        )

    def _validate_baseline(self) -> None:
        validate_topology_backend(self.model, self._topology_format)
        validate_dynamics_backend(self.model, self._dynamics_format)
        if (
            self._baseline_json() != self._validation_baseline_json
            or json.dumps(self.learning_initialization, sort_keys=True, allow_nan=False) != self._initialization_json
        ):
            raise ValueError("learning initialization/validation baseline changed")

    def train_batch(self, stage: CurriculumStage, seed: int) -> dict[str, object]:
        self._validate_baseline()
        validate_learning_setup(self.model, self.optimizer, self.learning_roles)
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
            torch.cuda.reset_peak_memory_stats(self.device)
        started = time.perf_counter()
        # Rehearse every completed skill while learning the current one. The
        # coordinator still evaluates and gates each stage independently.
        partitions = [self.datasets[configured.id][0] for configured in self.config.stages if configured.order <= stage.order]
        metrics = {}
        for _ in range(stage.epochs_per_batch):
            metrics = train_epoch(
                self.model,
                chain.from_iterable(partitions),
                self.optimizer,
                self.truncate_steps,
                weights=self.loss_weights,
            )
        frames = sum(_frame_count(partition) for partition in partitions)
        validate_learning_setup(self.model, self.optimizer, self.learning_roles)
        return {
            "learning_roles": self.learning_roles,
            "updates": stage.epochs_per_batch,
            "environment_steps": frames * stage.epochs_per_batch,
            "train_loss": float(metrics["total"]),
            "elapsed_wall_s": time.perf_counter() - started,
            "peak_process_memory_bytes": _peak_process_memory_bytes(),
            "peak_cuda_memory_bytes": (int(torch.cuda.max_memory_allocated(self.device)) if self.device.type == "cuda" else 0),
            "device": self.device.type,
            "torch_version": torch.__version__,
        }

    def evaluate(self, stage: CurriculumStage) -> dict[str, float | bool]:
        self._validate_baseline()
        result = evaluate_sequences(
            self.model,
            self.datasets[stage.id][1],
            self.truncate_steps,
            weights=self.loss_weights,
        )
        finite = all(torch.isfinite(parameter).all().item() for parameter in self.model.parameters())
        return {
            "validation_loss": float(result["total"]),
            "initial_validation_loss": float(self.initial_losses[stage.id]),
            "parameters_finite": finite,
        }

    def save_checkpoint(self, path: Path, metadata: dict) -> None:
        self._validate_baseline()
        if "dynamics_format" in metadata and metadata["dynamics_format"] != self._dynamics_format:
            raise ValueError("checkpoint metadata mismatch: dynamics_format")
        validate_learning_setup(self.model, self.optimizer, self.learning_roles)
        validate_learning_optimizer_state(self.model, self.optimizer, self.optimizer.state_dict(), self.learning_roles)
        enriched = {
            **metadata,
            "epoch": int(metadata["stage_index"]) * 100_000 + int(metadata["batch_index"]) + 1,
            "dataset_sha256": self.dataset_sha256,
            "topology_sha256": self.parameters.identity.topology_sha256,
            "parameter_mapping_sha256": self.mapping_sha256,
            "learning_roles": self.learning_roles,
            "learning_initialization": json.loads(self._initialization_json),
            "validation_baseline": json.loads(self._validation_baseline_json),
            **({"topology_format": self._topology_format} if self._topology_format != "coo_reference" else {}),
            **({"dynamics_format": self._dynamics_format} if self._dynamics_format != "clipped-euler-v1" else {}),
        }
        if self._dynamics_format == "clipped-euler-v1":
            enriched.pop("dynamics_format", None)
        trainable = {name: parameter.detach().cpu().clone() for name, parameter in self.model.named_parameters()}
        save_checkpoint(
            path,
            model_state=trainable,
            optimizer_state=self.optimizer.state_dict(),
            metadata=enriched,
        )

    def restore_checkpoint(self, path: Path) -> None:
        self._validate_baseline()
        validate_learning_setup(self.model, self.optimizer, self.learning_roles)
        payload = load_checkpoint(
            path,
            expected_metadata={
                "config_digest": self.config.digest,
                "model_identity": self.model_identity,
                "dataset_sha256": self.dataset_sha256,
                "topology_sha256": self.parameters.identity.topology_sha256,
                "parameter_mapping_sha256": self.mapping_sha256,
                "learning_roles": self.learning_roles,
                "learning_initialization": json.loads(self._initialization_json),
                "validation_baseline": json.loads(self._validation_baseline_json),
                **({"topology_format": self._topology_format} if self._topology_format != "coo_reference" else {}),
                **({"dynamics_format": self._dynamics_format} if self._dynamics_format != "clipped-euler-v1" else {}),
            },
        )
        if payload["metadata"].get("topology_format", "coo_reference") != self._topology_format:
            raise ValueError("checkpoint metadata mismatch: topology_format")
        if payload["metadata"].get("dynamics_format", "clipped-euler-v1") != self._dynamics_format:
            raise ValueError("checkpoint metadata mismatch: dynamics_format")
        named = dict(self.model.named_parameters())
        validate_learning_state(self.model, payload["model_state"], self.learning_roles)
        validate_learning_optimizer_state(self.model, self.optimizer, payload["optimizer_state"], self.learning_roles)
        if set(payload["model_state"]) != set(named):
            raise ValueError("checkpoint trainable parameter names do not match model")
        with torch.no_grad():
            for name, value in payload["model_state"].items():
                if named[name].shape != value.shape:
                    raise ValueError(f"checkpoint parameter shape mismatch: {name}")
                named[name].copy_(value.to(named[name].device))
        self.optimizer.load_state_dict(payload["optimizer_state"])
        restore_rng_state(payload["rng_state"])
