from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.nn import functional as functional


@dataclass(frozen=True)
class LossWeights:
    imitation: float = 1.0
    clearance_weighted: float = 2.0
    smoothness: float = 0.05
    saturation: float = 0.1
    clearance_margin_m: float = 0.8


def sequence_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    teacher_clearance_m: torch.Tensor,
    weights: LossWeights,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    if prediction.ndim != 3 or prediction.shape != target.shape:
        raise ValueError("prediction and target must have identical 3D shapes")
    if teacher_clearance_m.shape != prediction.shape[:2]:
        raise ValueError("teacher_clearance_m shape does not match sequence")
    if prediction.shape[1] < 1:
        raise ValueError("loss requires at least one sequence frame")
    if not all(
        torch.isfinite(value).all()
        for value in (prediction, target, teacher_clearance_m)
    ):
        raise ValueError("loss inputs contain non-finite values")
    frame_mse = (prediction - target).square().mean(dim=-1)
    risk = functional.relu(weights.clearance_margin_m - teacher_clearance_m)
    imitation = frame_mse.mean()
    clearance_weighted = (frame_mse * (1.0 + risk)).mean()
    if prediction.shape[1] > 1:
        smoothness = (prediction[:, 1:] - prediction[:, :-1]).square().mean()
    else:
        smoothness = prediction.new_zeros(())
    saturation = functional.relu(prediction.abs() - 1.0).square().mean()
    terms = {
        "imitation": imitation,
        "clearance_weighted": clearance_weighted,
        "smoothness": smoothness,
        "saturation": saturation,
    }
    total = (
        weights.imitation * imitation
        + weights.clearance_weighted * clearance_weighted
        + weights.smoothness * smoothness
        + weights.saturation * saturation
    )
    return total, terms
