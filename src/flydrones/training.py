"""Training contract for fly-like, decentralized navigation policies.

The connectome remains the fixed sensorimotor scaffold. Training changes the
visual adapter, descending-neuron readout and (optionally) a small declared set
of plastic synapses. This module defines the reward and curriculum independently
of any particular RL library so the same acceptance rules work in the fast
simulator, Gazebo and recorded replays.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlyTrainingState:
    distance_to_goal_m: float
    min_obstacle_distance_m: float
    min_neighbor_distance_m: float
    collisions: int = 0
    reached_goal: bool = False
    action: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    central_messages: int = 0


@dataclass(frozen=True)
class FlyRewardWeights:
    progress: float = 3.0
    time: float = -0.01
    obstacle: float = 5.0
    neighbor: float = 6.0
    collision: float = 30.0
    smoothness: float = 0.08
    energy: float = 0.015
    central_message: float = 0.25
    goal: float = 20.0
    obstacle_clearance_m: float = 0.65
    neighbor_clearance_m: float = 0.80

    @classmethod
    def from_dict(cls, values: dict | None) -> FlyRewardWeights:
        known = {k: v for k, v in (values or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def fly_reward(
    previous: FlyTrainingState,
    current: FlyTrainingState,
    weights: FlyRewardWeights | None = None,
) -> tuple[float, dict[str, float]]:
    """Return a scalar reward and auditable component breakdown."""
    w = weights or FlyRewardWeights()
    action_delta = sum((a - b) ** 2 for a, b in zip(current.action, previous.action))
    action_energy = sum(a * a for a in current.action)
    obstacle_intrusion = max(0.0, w.obstacle_clearance_m - current.min_obstacle_distance_m)
    neighbor_intrusion = max(0.0, w.neighbor_clearance_m - current.min_neighbor_distance_m)
    new_collisions = max(0, current.collisions - previous.collisions)
    first_arrival = current.reached_goal and not previous.reached_goal

    terms = {
        "progress": w.progress * (previous.distance_to_goal_m - current.distance_to_goal_m),
        "time": w.time,
        "obstacle_clearance": -w.obstacle * obstacle_intrusion**2,
        "neighbor_clearance": -w.neighbor * neighbor_intrusion**2,
        "collision": -w.collision * new_collisions,
        "smoothness": -w.smoothness * action_delta,
        "energy": -w.energy * action_energy,
        "central_dependency": -w.central_message * max(0, current.central_messages - previous.central_messages),
        "goal": w.goal if first_arrival else 0.0,
    }
    return sum(terms.values()), terms


@dataclass(frozen=True)
class CurriculumStage:
    name: str
    minimum_success_rate: float
    maximum_collision_rate: float
    minimum_clearance_m: float
    episodes: int
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, values: dict) -> CurriculumStage:
        return cls(
            name=str(values["name"]),
            minimum_success_rate=float(values["minimum_success_rate"]),
            maximum_collision_rate=float(values["maximum_collision_rate"]),
            minimum_clearance_m=float(values["minimum_clearance_m"]),
            episodes=int(values["episodes"]),
            capabilities=tuple(values.get("capabilities", ())),
        )

    def passed(self, metrics: dict[str, float]) -> bool:
        return (
            metrics.get("episodes", 0) >= self.episodes
            and metrics.get("success_rate", 0.0) >= self.minimum_success_rate
            and metrics.get("collision_rate", float("inf")) <= self.maximum_collision_rate
            and metrics.get("minimum_clearance_m", 0.0) >= self.minimum_clearance_m
        )


def next_curriculum_stage(
    stages: list[CurriculumStage],
    completed_name: str | None,
    metrics: dict[str, float],
) -> CurriculumStage:
    """Promote only after the current stage satisfies every acceptance gate."""
    if not stages:
        raise ValueError("curriculum needs at least one stage")
    if completed_name is None:
        return stages[0]
    index = next((i for i, stage in enumerate(stages) if stage.name == completed_name), None)
    if index is None:
        raise ValueError(f"unknown curriculum stage: {completed_name}")
    current = stages[index]
    if not current.passed(metrics) or index == len(stages) - 1:
        return current
    return stages[index + 1]
