"""Continuous swept bounding-sphere geometry for independent scoring."""

import numpy as np
from scipy.optimize import minimize_scalar


def segment_box_clearance(a, b, lo, hi, radius: float) -> float:
    a, b, lo, hi = (np.asarray(v, dtype=float) for v in (a, b, lo, hi))
    d = b - a
    knots = [0., 1.]
    for j in range(3):
        if abs(d[j]) > 1e-15:
            knots.extend(t for edge in (lo[j], hi[j]) if 0 < (t := (edge - a[j]) / d[j]) < 1)
    knots = sorted(knots)

    def distance(t):
        p = a + t * d
        return float(np.linalg.norm(np.maximum(np.maximum(lo - p, p - hi), 0.)))

    best = min(distance(0), distance(1))
    for left, right in zip(knots[:-1], knots[1:]):
        p = a + (left + right) * .5 * d
        mask = (p < lo) | (p > hi)
        edge = np.where(p < lo, lo, hi)
        slope, offset = d[mask], (a - edge)[mask]
        norm = float(slope @ slope)
        t = float(np.clip(-(offset @ slope) / norm, left, right)) if norm > 0 else left
        best = min(best, distance(t), distance(left), distance(right))
    return best - radius


def segment_cylinder_clearance(a, b, center, tree_radius, zlo, zhi, radius: float) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    center = np.asarray(center, dtype=float)

    def distance(t):
        p = a + t * (b - a)
        radial = max(0., float(np.linalg.norm(p[:2] - center)) - tree_radius)
        vertical = max(zlo - p[2], p[2] - zhi, 0.)
        return float(np.hypot(radial, vertical))

    result = minimize_scalar(distance, bounds=(0., 1.), method='bounded', options={'xatol': 1e-12})
    # Sub-micrometre conservatism prevents numerical near-contact false negatives.
    return min(distance(0), distance(1), float(result.fun)) - radius - 1e-8


def point_clearances(points: np.ndarray, world: dict) -> np.ndarray:
    result = np.full(points.shape[:-1], np.inf)
    for box in world['boxes']:
        delta = np.maximum(np.maximum(np.array(box['lo']) - points, points - np.array(box['hi'])), 0.)
        result = np.minimum(result, np.linalg.norm(delta, axis=-1))
    for tree in world['cylinders']:
        radial = np.maximum(0., np.linalg.norm(points[..., :2] - np.array(tree['center']), axis=-1) - tree['radius'])
        vertical = np.maximum(np.maximum(tree['zlo'] - points[..., 2], points[..., 2] - tree['zhi']), 0.)
        result = np.minimum(result, np.hypot(radial, vertical))
    return result
