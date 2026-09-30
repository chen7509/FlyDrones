"""Strict data contracts for decentralized multi-task learning."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np


class Skill(str, Enum):
    NAVIGATE_EXIT = "navigate_exit"
    TRACK_TARGET = "track_target"
    SEARCH_COVER = "search_cover"
    FORMATION_RALLY = "formation_rally"
    GATE_COURSE = "gate_course"
    YIELD_RETURN_LAND = "yield_return_land"


class WorldKind(str, Enum):
    FOREST = "forest"
    BUILDING = "building"
    MIXED = "mixed"


_MANIFEST_KEYS = {
    "schema_version",
    "seed",
    "world",
    "fleet_size",
    "active_skills",
    "disturbances",
    "failure_vehicle_ids",
    "minimum_active_factors",
}
_OBSERVATION_LENGTHS = (32, 8, 8, 16, 16, 4, 6)
SUPPORTED_DISTURBANCES = (
    "wind",
    "sensor_noise",
    "packet_loss",
    "frame_drop",
    "localization_drift",
    "battery_variation",
)


def _exact_keys(data: Mapping[str, object], expected: set[str], where: str) -> None:
    missing = expected - set(data)
    extra = set(data) - expected
    if missing or extra:
        raise ValueError(
            f"{where} keys differ: missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer")
    return value


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{where} must be finite")
    return result


def _unique_strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{where} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{where} must contain non-empty strings")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError(f"{where} contains duplicate members")
    return result


@dataclass(frozen=True)
class ScenarioManifest:
    schema_version: int
    seed: int
    world: WorldKind
    fleet_size: int
    active_skills: tuple[Skill, ...]
    disturbances: tuple[str, ...]
    failure_vehicle_ids: tuple[int, ...]
    minimum_active_factors: int

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ScenarioManifest:
        if not isinstance(data, Mapping):
            raise ValueError("scenario manifest must be an object")
        _exact_keys(data, _MANIFEST_KEYS, "scenario manifest")
        version = _integer(data["schema_version"], "schema_version")
        if version != 1:
            raise ValueError("only scenario schema version 1 is supported")
        seed = _integer(data["seed"], "seed")
        fleet_size = _integer(data["fleet_size"], "fleet_size")
        if not 1 <= fleet_size <= 100:
            raise ValueError("fleet_size must be between 1 and 100")
        minimum = _integer(data["minimum_active_factors"], "minimum_active_factors")
        if minimum < 1:
            raise ValueError("minimum_active_factors must be positive")
        try:
            world = WorldKind(data["world"])
        except (TypeError, ValueError) as exc:
            raise ValueError("world is unsupported") from exc
        raw_skills = _unique_strings(data["active_skills"], "active_skills")
        try:
            skills = tuple(Skill(value) for value in raw_skills)
        except ValueError as exc:
            raise ValueError("active_skills contains an unsupported skill") from exc
        if not skills:
            raise ValueError("active_skills cannot be empty")
        disturbances = _unique_strings(data["disturbances"], "disturbances")
        raw_failures = data["failure_vehicle_ids"]
        if not isinstance(raw_failures, (list, tuple)):
            raise ValueError("failure_vehicle_ids must be an array")
        failures = tuple(_integer(value, "failure_vehicle_ids") for value in raw_failures)
        if len(failures) != len(set(failures)):
            raise ValueError("failure_vehicle_ids contains duplicate members")
        if any(value < 0 or value >= fleet_size for value in failures):
            raise ValueError("failure_vehicle_ids must fall inside the fleet")
        factors = len(skills) + len(disturbances) + bool(failures)
        if factors < minimum:
            raise ValueError("scenario does not satisfy minimum_active_factors")
        return cls(
            version,
            seed,
            world,
            fleet_size,
            skills,
            disturbances,
            tuple(sorted(failures)),
            minimum,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "world": self.world.value,
            "fleet_size": self.fleet_size,
            "active_skills": [skill.value for skill in self.active_skills],
            "disturbances": list(self.disturbances),
            "failure_vehicle_ids": list(self.failure_vehicle_ids),
            "minimum_active_factors": self.minimum_active_factors,
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()


def _immutable_vector(values: Sequence[float] | np.ndarray, length: int, where: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (length,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{where} must contain {length} finite values")
    result = result.copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class LocalObservation:
    visual_features: np.ndarray
    flight_state: np.ndarray
    task_state: np.ndarray
    local_map: np.ndarray
    peer_summary: np.ndarray
    previous_action: np.ndarray
    validity: np.ndarray
    maximum_age_s: float
    age_s: float

    dimension = sum(_OBSERVATION_LENGTHS)

    @classmethod
    def from_arrays(
        cls,
        visual_features: Sequence[float] | np.ndarray,
        flight_state: Sequence[float] | np.ndarray,
        task_state: Sequence[float] | np.ndarray,
        local_map: Sequence[float] | np.ndarray,
        peer_summary: Sequence[float] | np.ndarray,
        previous_action: Sequence[float] | np.ndarray,
        validity: Sequence[float] | np.ndarray,
        *,
        maximum_age_s: float,
        age_s: float,
    ) -> LocalObservation:
        vectors = tuple(
            _immutable_vector(values, length, name)
            for values, length, name in zip(
                (
                    visual_features,
                    flight_state,
                    task_state,
                    local_map,
                    peer_summary,
                    previous_action,
                    validity,
                ),
                _OBSERVATION_LENGTHS,
                (
                    "visual_features",
                    "flight_state",
                    "task_state",
                    "local_map",
                    "peer_summary",
                    "previous_action",
                    "validity",
                ),
            )
        )
        if not np.all(np.isin(vectors[-1], (0.0, 1.0))):
            raise ValueError("validity must be a binary mask")
        maximum_age = _finite(maximum_age_s, "maximum_age_s")
        age = _finite(age_s, "age_s")
        if maximum_age <= 0.0:
            raise ValueError("maximum_age_s must be positive")
        if age < 0.0:
            raise ValueError("age_s cannot be negative")
        if age > maximum_age:
            raise ValueError("observation is stale")
        return cls(*vectors, maximum_age, age)

    def actor_vector(self) -> np.ndarray:
        result = np.concatenate(
            (
                self.visual_features,
                self.flight_state,
                self.task_state,
                self.local_map,
                self.peer_summary,
                self.previous_action,
                self.validity,
            )
        ).astype(np.float32, copy=False)
        result.flags.writeable = False
        return result


@dataclass(frozen=True)
class PolicyIntent:
    skill: Skill
    motion: tuple[float, float, float, float]
    confidence: float
    hold_time_s: float

    def checked(self) -> PolicyIntent:
        try:
            skill = self.skill if isinstance(self.skill, Skill) else Skill(self.skill)
        except (TypeError, ValueError) as exc:
            raise ValueError("skill is unsupported") from exc
        if not isinstance(self.motion, (list, tuple)) or len(self.motion) != 4:
            raise ValueError("motion must contain four finite values")
        motion = tuple(max(-1.0, min(1.0, _finite(value, "motion"))) for value in self.motion)
        confidence = _finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")
        hold_time = _finite(self.hold_time_s, "hold_time_s")
        if hold_time <= 0.0:
            raise ValueError("hold_time_s must be positive")
        return PolicyIntent(skill, motion, confidence, hold_time)


@dataclass(frozen=True)
class SafetySnapshot:
    battery_pct: float
    localization_healthy: bool
    sensors_healthy: bool
    minimum_clearance_m: float
    emergency_active: bool
    recovery_motion: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def can_learn(self) -> bool:
        try:
            battery = _finite(self.battery_pct, "battery_pct")
            clearance = _finite(self.minimum_clearance_m, "minimum_clearance_m")
        except ValueError:
            return False
        return (
            battery >= 35.0
            and self.localization_healthy is True
            and self.sensors_healthy is True
            and clearance >= 1.0
            and self.emergency_active is False
        )
