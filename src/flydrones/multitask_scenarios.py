"""Seeded curriculum scenarios for multi-task swarm learning."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from flydrones.multitask_contract import ScenarioManifest, Skill, WorldKind

LEVEL_SKILL_COUNTS = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}
LEVEL_MINIMUM_FACTORS = {0: 1, 1: 2, 2: 4, 3: 5, 4: 8}

_SKILLS = tuple(Skill)
_DISTURBANCES = (
    "wind",
    "packet_loss",
    "battery_variation",
    "sensor_noise",
    "frame_drop",
    "localization_drift",
)
_WORLDS = (WorldKind.FOREST, WorldKind.BUILDING, WorldKind.MIXED)


class ScenarioGenerator:
    """Generate replayable manifests without using process-global randomness."""

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        self.seed = seed

    def generate(
        self,
        *,
        level: int,
        fleet_size: int,
        active_skills: Iterable[Skill | str] | None = None,
    ) -> ScenarioManifest:
        if level not in LEVEL_SKILL_COUNTS:
            raise ValueError("level must be between 0 and 4")
        if isinstance(fleet_size, bool) or not isinstance(fleet_size, int) or not 1 <= fleet_size <= 100:
            raise ValueError("fleet_size must be between 1 and 100")
        if level == 4 and fleet_size < 5:
            raise ValueError("fleet_size must be at least five for level four")

        rng = np.random.default_rng(self.seed)
        overridden_skills: tuple[Skill, ...] | None = None
        if active_skills is not None:
            if isinstance(active_skills, (str, bytes)):
                raise ValueError("active_skills must be an iterable of skills")
            try:
                overridden_skills = tuple(
                    value if isinstance(value, Skill) else Skill(value)
                    for value in active_skills
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("active_skills contains an unsupported skill") from exc
            if (
                len(overridden_skills) != LEVEL_SKILL_COUNTS[level]
                or len(set(overridden_skills)) != len(overridden_skills)
            ):
                raise ValueError(
                    "active_skills must be unique and match the level skill count"
                )
        if level == 0:
            skills = (Skill.NAVIGATE_EXIT,)
            disturbances: tuple[str, ...] = ()
            failures: tuple[int, ...] = ()
        elif level == 4:
            skills = _SKILLS
            disturbances = ("wind", "packet_loss", "battery_variation", "sensor_noise")
            failure_count = max(1, round(fleet_size * 0.1))
            failures = tuple(sorted(int(value) for value in rng.choice(
                fleet_size, size=failure_count, replace=False
            )))
        else:
            skill_indices = sorted(
                int(value)
                for value in rng.choice(len(_SKILLS), size=LEVEL_SKILL_COUNTS[level], replace=False)
            )
            skills = tuple(_SKILLS[index] for index in skill_indices)
            disturbance_count = {1: 1, 2: 2, 3: 3}[level]
            disturbance_indices = sorted(
                int(value)
                for value in rng.choice(len(_DISTURBANCES), size=disturbance_count, replace=False)
            )
            disturbances = tuple(_DISTURBANCES[index] for index in disturbance_indices)
            failures = ()
            if level == 3 and fleet_size >= 5:
                failures = (int(rng.integers(0, fleet_size)),)
        if overridden_skills is not None:
            skills = overridden_skills

        world = WorldKind.MIXED if level == 4 else _WORLDS[int(rng.integers(0, len(_WORLDS)))]
        return ScenarioManifest.from_dict(
            {
                "schema_version": 1,
                "seed": self.seed,
                "world": world.value,
                "fleet_size": fleet_size,
                "active_skills": [skill.value for skill in skills],
                "disturbances": list(disturbances),
                "failure_vehicle_ids": list(failures),
                "minimum_active_factors": LEVEL_MINIMUM_FACTORS[level],
            }
        )

    @staticmethod
    def held_out(
        seeds: Iterable[int],
        *,
        level: int,
        fleet_size: int,
        active_skills: Iterable[Skill | str] | None = None,
    ) -> tuple[ScenarioManifest, ...]:
        values = tuple(seeds)
        if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in values):
            raise ValueError("held-out seeds must be integers")
        if len(values) != len(set(values)):
            raise ValueError("held-out seeds contain duplicates")
        return tuple(
            ScenarioGenerator(seed).generate(
                level=level,
                fleet_size=fleet_size,
                active_skills=active_skills,
            )
            for seed in sorted(values)
        )
