"""Build continuous forest-training samples from recorded simulator flights."""

from __future__ import annotations

import math

import numpy as np

from .drones.sim import Box
from .senses.retina import FEATURES, VisualFrame


def summarize_retina(vision: VisualFrame) -> dict[str, float]:
    """Collapse each ommatidial grid to stable per-eye training features."""
    values = {
        f"{feature}_{eye}": float(vision.eyes[eye].grids[feature].mean())
        for eye in ("L", "R")
        for feature in FEATURES
    }
    values.update(
        expansion=float(vision.expansion),
        rotation=float(vision.rotation),
        vertical=float(vision.vertical),
    )
    return values


def nearest_box_guidance(
    position: np.ndarray,
    yaw: float,
    boxes: list[Box],
    clearance: float,
    *,
    cruise: float = 0.75,
    warning_m: float = 1.2,
    critical_m: float = 0.7,
) -> dict[str, float | bool]:
    """Return deterministic safety labels for sequence-level imitation.

    Positive yaw is clockwise in ``SimDrone``. When an obstacle lies left of
    the current heading, the label is therefore positive (turn right), and
    vice versa. The label persists throughout the warning zone so training
    does not reward oscillating left/right commands.
    """
    if not boxes:
        return {"target_yaw": 0.0, "target_forward": cruise, "danger": False}

    p = np.asarray(position, dtype=float)

    def surface_distance(box: Box) -> float:
        lo, hi = np.asarray(box.lo), np.asarray(box.hi)
        delta = np.maximum(np.maximum(lo - p, p - hi), 0.0)
        return float(np.linalg.norm(delta))

    nearest = min(boxes, key=surface_distance)
    center = (np.asarray(nearest.lo) + np.asarray(nearest.hi)) * 0.5
    bearing = math.atan2(center[1] - p[1], center[0] - p[0])
    relative = (bearing - yaw + math.pi) % (2 * math.pi) - math.pi
    danger = clearance < warning_m and abs(relative) < math.pi / 2
    if not danger:
        return {"target_yaw": 0.0, "target_forward": cruise, "danger": False}

    strength = float(np.clip((warning_m - clearance) / max(1e-6, warning_m - critical_m), 0.0, 1.0))
    # Straight-ahead ties use a stable side selected from the obstacle centre.
    side = 1.0 if relative >= 0.0 else -1.0
    target_yaw = side * (0.35 + 0.65 * strength)
    target_forward = cruise * (1.0 - strength)
    if clearance <= critical_m:
        target_forward = -0.2
    return {
        "target_yaw": float(target_yaw),
        "target_forward": float(target_forward),
        "danger": True,
    }

