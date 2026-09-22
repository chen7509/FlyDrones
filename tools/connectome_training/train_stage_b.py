from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np
from scipy import sparse
import torch
import yaml

from flydrones.brain.connectome import Connectome, GroupSpec
from flydrones.config import load_config
from flydrones.connectome_training.checkpoint import save_checkpoint
from flydrones.connectome_training.dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
)
from flydrones.connectome_training.features import FEATURE_NAMES, sequence_tensors
from flydrones.connectome_training.governance import validate_dataset_partitions
from flydrones.connectome_training.losses import LossWeights
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
    save_parameter_set,
)
from flydrones.connectome_training.trainer import evaluate_sequences, train_epoch

OUTPUT_NAMES = ("vx", "vy", "vz", "yaw_rate")
FULL_MODEL_SHA256 = "b6be8b3dd901e2e0893303c04058a110d6e0fb9922a69022b26514efcf06100c"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--config", default="configs/connectome_training_stage_b_v1.yaml"
    )
    parser.add_argument("--output", default="results/connectome-training/stage-b")
    parser.add_argument("--initialize-full", action="store_true")
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("epochs must be positive")
    return args


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _toy_sequence(*, split: str, seed: int, world_sha256: str) -> TrainingSequence:
    provenance = SequenceProvenance(
        split,
        seed,
        "deterministic-teacher-v1",
        world_sha256,
        "e" * 64,
        "generated-training-world" if split == "train" else "generated-validation-world",
    )
    frames, targets = [], []
    variant = (seed % 19) / 100.0
    for index in range(8):
        phase = index / 7.0
        depth = np.full((6, 9), 1.5 + variant + 0.8 * phase, np.float32)
        frames.append(
            SequenceFrame(
                (index + 1) * 50_000_000,
                (index + 1) * 50_000_000,
                np.full((6, 9, 3), 40 + index * 3 + seed % 7, np.uint8),
                depth,
                np.array([phase, variant, 1.0], np.float32),
                np.array([0.2, 0.0, 0.0], np.float32),
                0.0,
                0.0,
                np.array([5.0, -variant, 1.0], np.float32),
            )
        )
        targets.append(
            TeacherTarget(
                np.array([0.35 + 0.05 * phase, variant, 0.0], np.float32),
                0.0,
                np.array([[1.0 + phase, 0.0, 1.0]], np.float32),
                0.75 + 0.1 * phase,
                index == 7,
            )
        )
    return TrainingSequence(provenance, frames, targets)


def _toy_model() -> tuple[ConnectomeConstrainedCore, str]:
    neurons = len(FEATURE_NAMES) + len(OUTPUT_NAMES)
    weights = sparse.eye(neurons, format="csc", dtype=np.float32)
    connectome = Connectome(
        "stage-b-smoke",
        weights,
        np.array(["sensory"] * len(FEATURE_NAMES) + ["descending"] * 4),
        np.array([""] * neurons),
    )
    identity = build_structure_identity(connectome, "c" * 64)
    parameters = initial_parameter_set(
        identity,
        FEATURE_NAMES,
        OUTPUT_NAMES,
        output_neurons=np.arange(neurons - 4, neurons),
    )
    model = ConnectomeConstrainedCore(connectome, parameters)
    return model, identity.topology_sha256


def _dataset_digest(sequences: list[TrainingSequence]) -> str:
    digest = sha256()
    for sequence in sequences:
        provenance = sequence.provenance
        digest.update(
            json.dumps(
                {
                    "split": provenance.split,
                    "seed": provenance.seed,
                    "world_sha256": provenance.world_sha256,
                    "teacher": provenance.teacher,
                },
                sort_keys=True,
            ).encode("utf-8")
        )
        for frame, target in zip(sequence.frames, sequence.targets):
            for value in (
                frame.rgb,
                frame.depth_m,
                frame.position_enu,
                frame.velocity_enu,
                frame.goal_enu,
                target.velocity_enu,
                target.horizon_enu,
            ):
                digest.update(np.ascontiguousarray(value).tobytes())
            digest.update(np.asarray([frame.sim_ns, frame.frame_ns], np.int64).tobytes())
            digest.update(
                np.asarray(
                    [
                        frame.yaw,
                        frame.yaw_rate,
                        target.yaw_rate,
                        target.minimum_clearance_m,
                    ],
                    np.float64,
                ).tobytes()
            )
            digest.update(np.asarray([target.terminal], np.uint8).tobytes())
    return digest.hexdigest()


def _feature_digest(sequences: list[TrainingSequence]) -> str:
    digest = sha256()
    for sequence in sequences:
        features, _, _ = sequence_tensors(sequence)
        digest.update(np.ascontiguousarray(features.numpy()).tobytes())
    return digest.hexdigest()


def _initialize_full(output: Path) -> None:
    model_path = Path("data/malecns_full.npz")
    model_hash = _sha256_file(model_path)
    if model_hash != FULL_MODEL_SHA256:
        raise ValueError("full MaleCNS model hash does not match the frozen source")
    connectome = Connectome.load(model_path)
    config = load_config("configs/forest-trained-v2.yaml")
    input_specs = {
        name: GroupSpec.from_dict(name, value)
        for name, value in config.get("inputs", {}).items()
    }
    output_specs = {
        name: GroupSpec.from_dict(name, value)
        for name, value in config.get("outputs", {}).items()
    }
    connectome.resolve_groups({**input_specs, **output_specs})
    input_neurons = np.unique(
        np.concatenate(
            [connectome.group(name) for name in input_specs]
            or [np.zeros(0, np.int64)]
        )
    )
    output_neurons = np.unique(
        np.concatenate(
            [connectome.group(name) for name in output_specs]
            or [np.zeros(0, np.int64)]
        )
    )
    if input_neurons.size == 0:
        raise ValueError("full MaleCNS input groups resolved to no neurons")
    if output_neurons.size == 0:
        raise ValueError("full MaleCNS output groups resolved to no neurons")
    identity = build_structure_identity(connectome, model_hash)
    parameters = initial_parameter_set(
        identity,
        FEATURE_NAMES,
        OUTPUT_NAMES,
        output_neurons,
        input_feature_index=np.arange(input_neurons.size) % len(FEATURE_NAMES),
        input_neuron_index=input_neurons,
        label="full-male-cns",
    )
    destination = output / "full-initialization"
    save_parameter_set(destination, parameters)
    print(
        json.dumps(
            {
                "output": str(destination),
                "initialized": True,
                "neurons": identity.neurons,
                "connections": identity.connections,
            }
        )
    )


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _run_smoke(args, config: dict, output: Path) -> None:
    seed = int(config["seed"] if args.seed is None else args.seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    train_sequences = [_toy_sequence(split="train", seed=101, world_sha256="1" * 64)]
    validation_sequences = [
        _toy_sequence(split="val", seed=202, world_sha256="2" * 64)
    ]
    validate_dataset_partitions(
        [sequence.provenance for sequence in train_sequences],
        [sequence.provenance for sequence in validation_sequences],
    )
    model, topology_hash = _toy_model()
    train_feature_hash = _feature_digest(train_sequences)
    validation_feature_hash = _feature_digest(validation_sequences)
    if train_feature_hash == validation_feature_hash:
        raise ValueError("training and validation features must be distinct")
    optimizer_name = str(config["optimizer"]["name"]).lower()
    if optimizer_name != "adam":
        raise ValueError(f"unsupported optimizer: {optimizer_name}")
    learning_rate = float(config["optimizer"]["learning_rate"])
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_weights = LossWeights(**config["loss"])
    truncate_steps = int(config["truncate_steps"])
    gradient_clip = float(config["optimizer"]["gradient_clip_norm"])
    initial_train = evaluate_sequences(
        model, train_sequences, truncate_steps, weights=loss_weights
    )
    initial_validation = evaluate_sequences(
        model, validation_sequences, truncate_steps, weights=loss_weights
    )
    started = time.perf_counter()
    final_train = initial_train
    for _ in range(args.epochs):
        final_train = train_epoch(
            model,
            train_sequences,
            optimizer,
            truncate_steps,
            weights=loss_weights,
            gradient_clip_norm=gradient_clip,
        )
    elapsed = time.perf_counter() - started
    final_validation = evaluate_sequences(
        model, validation_sequences, truncate_steps, weights=loss_weights
    )
    parameters_finite = all(
        torch.isfinite(parameter).all().item() for parameter in model.parameters()
    )
    loss_ratio = final_validation["total"] / initial_validation["total"]
    failures = []
    if loss_ratio > float(config["offline_gate"]["maximum_loss_ratio"]):
        failures.append("maximum_loss_ratio")
    if config["offline_gate"]["require_finite_parameters"] and not parameters_finite:
        failures.append("finite_parameters")
    passed = not failures
    dataset_hash = _dataset_digest(train_sequences + validation_sequences)
    output.mkdir(parents=True, exist_ok=True)
    save_checkpoint(
        output / "checkpoint",
        model_state=model.state_dict(),
        optimizer_state=optimizer.state_dict(),
        metadata={
            "epoch": args.epochs,
            "seed": seed,
            "dataset_sha256": dataset_hash,
            "topology_sha256": topology_hash,
        },
    )
    report = {
        "schema": "flydrones-connectome-stage-b-smoke-v1",
        "identity": "connectome-constrained-training-smoke",
        "scope": "Offline synthetic sequence learning gate; not a flight-success result.",
        "seed": seed,
        "epochs": args.epochs,
        "truncate_steps": truncate_steps,
        "topology_sha256": topology_hash,
        "dataset_sha256": dataset_hash,
        "train_feature_sha256": train_feature_hash,
        "validation_feature_sha256": validation_feature_hash,
        "trainable": [
            "input_gain",
            "type_bias_mv",
            "tau_m_ms",
            "descending_readout",
        ],
        "trainable_parameter_count": sum(
            parameter.numel() for parameter in model.parameters()
        ),
        "initial_train_loss": initial_train["total"],
        "final_train_loss": final_train["total"],
        "initial_validation_loss": initial_validation["total"],
        "final_validation_loss": final_validation["total"],
        "final_train_terms": final_train,
        "final_validation_terms": final_validation,
        "loss_ratio": loss_ratio,
        "gate_failures": failures,
        "passed_offline_gate": passed,
        "parameters_finite": parameters_finite,
        "torch_version": torch.__version__,
        "elapsed_wall_s": elapsed,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(output / "smoke_report.json", report)
    print(
        json.dumps(
            {
                "output": str(output / "smoke_report.json"),
                "passed": passed,
            }
        )
    )


def main():
    args = parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if config.get("schema") != "flydrones-connectome-training-stage-b-config-v1":
        raise ValueError("unsupported Stage B training config schema")
    output = Path(args.output)
    if args.initialize_full:
        _initialize_full(output)
    else:
        _run_smoke(args, config, output)


if __name__ == "__main__":
    main()
