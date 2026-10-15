from __future__ import annotations

from collections.abc import Iterable

import torch

from .dataset import TrainingSequence
from .features import feature_profile_for_names, sequence_tensors
from .losses import LossWeights, sequence_loss
from .model import ConnectomeConstrainedCore


def _mean_metrics(totals: dict[str, float]) -> dict[str, float]:
    frames = totals["frames"]
    if frames <= 0:
        raise ValueError("at least one training frame is required")
    return {name: value / frames for name, value in totals.items() if name != "frames"}


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
    tensors = sequence_tensors(sequence, profile=feature_profile_for_names(model.input_features))
    reference = next(model.parameters())
    return tuple(tensor.to(device=reference.device, dtype=reference.dtype) for tensor in tensors)


def _prediction_windows(model, features, truncate_steps):
    state = None
    for start in range(0, features.shape[1], truncate_steps):
        prediction, state = model.forward_sequence(
            features[:, start : start + truncate_steps],
            truncate_steps=truncate_steps,
            state=state,
        )
        state = state.detached()
        yield start, prediction


def _sequence_pass(model, features, target, clearance, truncate_steps, weights, *, backward):
    """Two windows, one sequence objective, no retained prior-window graph."""
    if truncate_steps < 1:
        raise ValueError("truncate_steps must be positive")
    if features.ndim != 3 or features.shape[1] < 1:
        raise ValueError("feature sequence must be non-empty and three-dimensional")
    if target.ndim != 3 or target.shape[:2] != features.shape[:2]:
        raise ValueError("target shape does not match sequence")
    if clearance.shape != features.shape[:2]:
        raise ValueError("teacher_clearance_m shape does not match sequence")
    if not all(torch.isfinite(value).all() for value in (features, target, clearance)):
        raise ValueError("sequence inputs contain non-finite values")
    frames = features.shape[1]
    metrics = {name: 0.0 for name in _empty_totals() if name != "frames"}
    windows = iter(_prediction_windows(model, features, truncate_steps))
    current = next(windows)
    following = next(windows, None)
    previous_last = None
    while current is not None:
        start, prediction = current
        size = prediction.shape[1]
        local_total, local = sequence_loss(
            prediction, target[:, start : start + size], clearance[:, start : start + size], weights
        )
        del local_total
        terms = {name: value * size / frames for name, value in local.items() if name != "smoothness"}
        smoothness = local["smoothness"] * (size - 1) / max(1, frames - 1)
        if following is not None:
            smoothness = smoothness + (prediction[:, -1] - following[1][:, 0].detach()).square().mean() / (frames - 1)
        terms["smoothness"] = smoothness
        total = sum(getattr(weights, name) * value for name, value in terms.items())
        # Count this boundary value above only once. Its other partial derivative
        # belongs to the next window, whose recurrent input is already detached.
        if backward:
            objective = total
            if previous_last is not None:
                objective = objective + weights.smoothness * (prediction[:, 0] - previous_last).square().mean() / (frames - 1)
            objective.backward()
            del objective
        metrics["total"] += float(total.detach())
        for name, value in terms.items():
            metrics[name] += float(value.detach())
        previous_last = prediction[:, -1].detach()
        # Drop old graph references before constructing another prediction window.
        del prediction, local, terms, total, smoothness, value
        current = following
        following = next(windows, None) if current is not None else None
    return metrics


def _accumulate_metrics(totals, metrics, frames):
    for name, value in metrics.items():
        totals[name] += value * frames
    totals["frames"] += frames


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
        metrics = _sequence_pass(model, features, target, clearance, truncate_steps, loss_weights, backward=True)
        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip_norm)
        optimizer.step()
        _accumulate_metrics(totals, metrics, features.shape[1])
        del sequence, features, target, clearance
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
            metrics = _sequence_pass(model, features, target, clearance, truncate_steps, loss_weights, backward=False)
            _accumulate_metrics(totals, metrics, features.shape[1])
            del sequence, features, target, clearance
    return _mean_metrics(totals)
