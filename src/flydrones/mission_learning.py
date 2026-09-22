"""Narrow learned-estimation adapter for the deterministic mission ledger."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from flydrones.mission_contract import MissionContract, WorkUnit


class AgentStateLike(Protocol):
    battery_pct: float


class MissionAgentLike(Protocol):
    contract: MissionContract

    @property
    def work_unit_ids(self) -> tuple[str, ...]: ...

    def work_unit(self, task_id: str) -> WorkUnit: ...


@dataclass(frozen=True)
class TaskEstimate:
    task_id: str
    duration_s: float
    energy_pct: float
    success_probability: float


Estimator = Callable[[WorkUnit, AgentStateLike], TaskEstimate]


class MissionLearningAdapter:
    """Rank known work without acquiring any ledger mutation capability."""

    def __init__(self, estimator: Estimator) -> None:
        if not callable(estimator):
            raise TypeError("estimator must be callable")
        self._estimator = estimator

    @staticmethod
    def _score(estimate: TaskEstimate, known_task_id: str) -> float:
        if not isinstance(estimate, TaskEstimate):
            raise ValueError("estimator must return TaskEstimate")
        if estimate.task_id != known_task_id:
            raise ValueError("estimator returned an unknown task ID")
        values = (estimate.duration_s, estimate.energy_pct, estimate.success_probability)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise ValueError("task estimate values must be finite numbers")
        duration, energy, probability = (float(value) for value in values)
        if not all(math.isfinite(value) for value in (duration, energy, probability)):
            raise ValueError("task estimate values must be finite")
        if duration < 0.0 or energy < 0.0:
            raise ValueError("duration and energy must be non-negative")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("success probability must be between zero and one")
        return 100.0 * probability - duration - 2.0 * energy

    def rank_work_units(
        self,
        units: Iterable[WorkUnit],
        state: AgentStateLike,
    ) -> tuple[str, ...]:
        ranked: list[tuple[float, str]] = []
        for unit in units:
            estimate = self._estimator(unit, state)
            ranked.append((self._score(estimate, unit.task_id), unit.task_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(task_id for _score, task_id in ranked)

    def preferred_task_ids(
        self,
        agent: MissionAgentLike,
        state: AgentStateLike,
    ) -> tuple[str, ...]:
        try:
            battery = float(state.battery_pct)
            if (
                not math.isfinite(battery)
                or battery <= agent.contract.safety.minimum_battery_return_pct
            ):
                return ()
            units = tuple(agent.work_unit(task_id) for task_id in agent.work_unit_ids)
            return self.rank_work_units(units, state)
        except (KeyError, TypeError, ValueError, OverflowError):
            return ()
