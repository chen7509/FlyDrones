"""Independent episode scoring that never enters the controller boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np


@dataclass(frozen=True)
class ScoreSample:
    sim_ns: int
    position: tuple[float, float, float]
    clearance_m: float
    contact: bool
    in_bounds: bool


_PRIORITY = {
    'timeout': 0,
    'success': 1,
    'out_of_bounds': 2,
    'collision': 3,
    'controller_error': 4,
    'infrastructure_error': 5,
}


class EpisodeScorer:
    def __init__(self, goal: tuple, radius: float, hold_s: float, timeout_s: float):
        parameters = np.asarray((*goal, radius, hold_s, timeout_s), dtype=float)
        if not np.all(np.isfinite(parameters)) or radius <= 0 or hold_s <= 0 or timeout_s <= 0:
            raise ValueError('scoring parameters must be finite and positive')
        self.goal = np.asarray(goal, dtype=float)
        self.radius = float(radius)
        self.hold_ns = round(float(hold_s) * 1_000_000_000)
        self.timeout_ns = round(float(timeout_s) * 1_000_000_000)
        self.samples: list[ScoreSample] = []
        self.events: list[str] = []
        self.status: str | None = None
        self.reason: str | None = None
        self._start_ns: int | None = None
        self._goal_entered_ns: int | None = None

    def _event(self, name: str) -> None:
        if name not in self.events:
            self.events.append(name)

    def _set_status(self, status: str, reason: str | None = None) -> str:
        if status not in _PRIORITY:
            raise ValueError(f'unknown terminal status: {status}')
        if self.status is None or _PRIORITY[status] > _PRIORITY[self.status]:
            self.status = status
            self.reason = reason
        self._event(status)
        return self.status

    def update(self, sample: ScoreSample) -> str | None:
        if type(sample.sim_ns) is not int:
            raise ValueError('simulation time must be integer nanoseconds')
        if self.samples and sample.sim_ns < self.samples[-1].sim_ns:
            raise ValueError('simulation clock moved backwards')
        if not np.all(np.isfinite(sample.position)) or not math.isfinite(sample.clearance_m):
            raise ValueError('score sample must be finite')
        self.samples.append(sample)
        if self._start_ns is None:
            self._start_ns = sample.sim_ns

        in_goal = float(np.linalg.norm(np.asarray(sample.position) - self.goal)) <= self.radius
        if in_goal:
            self._event('goal_region')
            if self._goal_entered_ns is None:
                self._goal_entered_ns = sample.sim_ns
        else:
            self._goal_entered_ns = None

        envelope_collision = sample.clearance_m <= 0
        if sample.contact:
            self._event('contact_truth')
        if envelope_collision:
            self._event('envelope_collision')
        if sample.contact or envelope_collision:
            return self._set_status('collision')
        if not sample.in_bounds:
            return self._set_status('out_of_bounds')
        if self._goal_entered_ns is not None and sample.sim_ns - self._goal_entered_ns >= self.hold_ns:
            return self._set_status('success')
        if sample.sim_ns - self._start_ns >= self.timeout_ns:
            return self._set_status('timeout')
        return self.status

    def fail(self, status: str, reason: str) -> str:
        if status not in {'controller_error', 'infrastructure_error'}:
            raise ValueError('fail status must be controller_error or infrastructure_error')
        return self._set_status(status, reason)

    def summary(self) -> dict:
        minimum = min((sample.clearance_m for sample in self.samples), default=None)
        elapsed = None
        if self.samples and self._start_ns is not None:
            elapsed = (self.samples[-1].sim_ns - self._start_ns) / 1_000_000_000
        return {
            'status': self.status,
            'reason': self.reason,
            'events': list(self.events),
            'elapsed_sim_s': elapsed,
            'minimum_clearance_m': minimum,
            'contact_truth': any(sample.contact for sample in self.samples),
            'envelope_collision': any(sample.clearance_m <= 0 for sample in self.samples),
            'path': [asdict(sample) for sample in self.samples],
        }
