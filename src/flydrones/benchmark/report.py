"""Aggregate benchmark outcomes without dropping failed episodes."""

from __future__ import annotations

from collections import Counter

import numpy as np


def path_length(path: list[dict]) -> float:
    if len(path) < 2:
        return 0.0
    points = np.asarray([sample['position'] for sample in path], dtype=float)
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _distribution(values) -> dict:
    array = np.asarray(list(values), dtype=float)
    if not len(array):
        return {'mean': None, 'median': None, 'p95': None}
    return {
        'mean': float(array.mean()),
        'median': float(np.median(array)),
        'p95': float(np.percentile(array, 95)),
    }


def summarize_controller(episodes: list[dict]) -> dict:
    if not episodes:
        raise ValueError('controller summary requires episodes')
    counts = dict(sorted(Counter(episode['status'] for episode in episodes).items()))
    decisions = [
        decision['decision_wall_s']
        for episode in episodes
        for decision in episode.get('decisions', [])
    ]
    return {
        'episodes': len(episodes),
        'status_counts': counts,
        'success_rate': counts.get('success', 0) / len(episodes),
        'collision_rate': counts.get('collision', 0) / len(episodes),
        'elapsed_sim_s': _distribution(
            episode['elapsed_sim_s'] for episode in episodes if episode.get('elapsed_sim_s') is not None
        ),
        'wall_s': _distribution(episode['wall_s'] for episode in episodes),
        'decision_wall_s': _distribution(decisions),
        'minimum_clearance_m': _distribution(
            episode['minimum_clearance_m'] for episode in episodes
            if episode.get('minimum_clearance_m') is not None
        ),
        'path_length_m': _distribution(path_length(episode.get('path', [])) for episode in episodes),
    }
