from __future__ import annotations

from collections.abc import Iterable

import torch

from .dataset import TrainingSequence
from .features import sequence_tensors
from .losses import LossWeights, sequence_loss
from .model import ConnectomeConstrainedCore


def _accumulate(
    totals: dict[str, float],
    total: torch.Tensor,
    terms: dict[str, torch.Tensor],
    frames: int,
) -> None:
    totals["total"] += float(total.detach()) * frames
    for name, value in terms.items():
        totals[name] += float(value.detach()) * frames
    totals["frames"] += frames


def _mean_metrics(totals: dict[str, float]) -> dict[str, float]:
    frames = totals["frames"]
    if frames <= 0:
        raise ValueError("at least one training frame is required")
    return {
        name: value / frames
        for name, value in totals.items()
        if name != "frames"
    }


def _empty_totals() -> dict[str, float]:
    return {
        "total": 0.0,
        "imitation": 0.0,
        "clearance_weighted": 0.0,
        "smoothness": 0.0,
        "saturation": 0.0,
        "frames": 0.0,
    }


def _on_model_device(
    model: ConnectomeConstrainedCore, sequence: TrainingSequence
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    tensors = sequence_tensors(sequence)
    reference = next(model.parameters())
    return tuple(
        tensor.to(device=reference.device, dtype=reference.dtype)
        for tensor in tensors
    )


def train_epoch(
    model: ConnectomeConstrainedCore,
    sequences: Iterable[TrainingSequence],
    optimizer: torch.optim.Optimizer,
    truncate_steps: int,
    *,
    weights: LossWeights | None = None,
    gradient_clip_norm: float = 5.0,
) -> dict[str, float]:
    if gradient_clip_norm <= 0:
        raise ValueError("gradient_clip_norm must be positive")
    model.train()
    totals = _empty_totals()
    loss_weights = weights or LossWeights()
    for sequence in sequences:
        features, target, clearance = _on_model_device(model, sequence)
        optimizer.zero_grad(set_to_none=True)
        prediction, _ = model.forward_sequence(
            features, truncate_steps=truncate_steps
        )
        total, terms = sequence_loss(
            prediction, target, clearance, loss_weights
        )
        total.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip_norm)
        optimizer.step()
        _accumulate(totals, total, terms, features.shape[1])
    return _mean_metrics(totals)


def evaluate_sequences(
    model: ConnectomeConstrainedCore,
    sequences: Iterable[TrainingSequence],
    truncate_steps: int,
    *,
    weights: LossWeights | None = None,
) -> dict[str, float]:
    model.eval()
    totals = _empty_totals()
    loss_weights = weights or LossWeights()
    with torch.no_grad():
        for sequence in sequences:
            features, target, clearance = _on_model_device(model, sequence)
            prediction, _ = model.forward_sequence(
                features, truncate_steps=truncate_steps
            )
            total, terms = sequence_loss(
                prediction, target, clearance, loss_weights
            )
            _accumulate(totals, total, terms, features.shape[1])
    return _mean_metrics(totals)
