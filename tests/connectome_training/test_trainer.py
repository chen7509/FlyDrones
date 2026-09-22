from dataclasses import replace

import numpy as np
from scipy import sparse
import torch

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
)
from flydrones.connectome_training.features import FEATURE_NAMES, sequence_tensors
from flydrones.connectome_training.losses import LossWeights, sequence_loss
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
)
from flydrones.connectome_training.trainer import evaluate_sequences, train_epoch


def toy_sequence(clearance=0.8):
    provenance = SequenceProvenance(
        "train", 11, "teacher@test", "a" * 64, "b" * 64, "training-world"
    )
    frames, targets = [], []
    for i in range(6):
        depth = np.full((4, 6), 2.0 + i * 0.1, np.float32)
        frames.append(
            SequenceFrame(
                (i + 1) * 50_000_000,
                (i + 1) * 50_000_000,
                np.full((4, 6, 3), 32 + i, np.uint8),
                depth,
                np.array([0, 0, 1], np.float32),
                np.zeros(3, np.float32),
                0.0,
                0.0,
                np.array([5, 0, 1], np.float32),
            )
        )
        targets.append(
            TeacherTarget(
                np.array([0.4, 0, 0], np.float32),
                0.0,
                np.array([[1, 0, 1]], np.float32),
                clearance,
                i == 5,
            )
        )
    return TrainingSequence(provenance, frames, targets)


def toy_model():
    n = len(FEATURE_NAMES) + 4
    connectome = Connectome(
        "toy",
        sparse.eye(n, format="csc", dtype=np.float32),
        np.array(["input"] * len(FEATURE_NAMES) + ["DN"] * 4),
        np.array([""] * n),
    )
    identity = build_structure_identity(connectome, "c" * 64)
    params = initial_parameter_set(
        identity, FEATURE_NAMES, ("vx", "vy", "vz", "yaw_rate"), 4
    )
    return ConnectomeConstrainedCore(
        connectome,
        params,
        np.arange(len(FEATURE_NAMES)),
        np.arange(n - 4, n),
    )


def test_teacher_labels_do_not_change_deployment_features():
    first = toy_sequence(0.8)
    second = TrainingSequence(
        first.provenance,
        first.frames,
        [replace(target, minimum_clearance_m=0.1) for target in first.targets],
    )
    x1, _, _ = sequence_tensors(first)
    x2, _, _ = sequence_tensors(second)
    assert torch.equal(x1, x2)


def test_loss_reports_safety_imitation_smoothness_and_saturation():
    prediction = torch.tensor([[[2.0, 0, 0, 0], [0.0, 0, 0, 0]]])
    target = torch.zeros_like(prediction)
    clearance = torch.tensor([[0.2, 1.0]])
    total, terms = sequence_loss(prediction, target, clearance, LossWeights())
    assert total > 0
    assert set(terms) == {
        "imitation",
        "clearance_weighted",
        "smoothness",
        "saturation",
    }


def test_offline_training_reduces_loss_and_resets_between_sequences():
    torch.manual_seed(4)
    model = toy_model()
    second = toy_sequence()
    second = replace(
        second,
        provenance=replace(second.provenance, seed=12, world_sha256="d" * 64),
    )
    sequences = [toy_sequence(), second]
    optimizer = torch.optim.Adam(model.parameters(), lr=0.03)
    before = evaluate_sequences(model, sequences, truncate_steps=3)["total"]
    for _ in range(40):
        train_epoch(model, sequences, optimizer, truncate_steps=3)
    after = evaluate_sequences(model, sequences, truncate_steps=3)["total"]
    assert after < before * 0.7
