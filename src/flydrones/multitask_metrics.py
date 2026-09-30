"""Immutable evidence accumulated by the fast multi-task environment."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType


def _finite(value: object, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _immutable_mapping(
    values: Mapping[str, object], *, value_type: type[int] | type[float], name: str
) -> Mapping[str, int] | Mapping[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be a mapping")
    if any(not isinstance(key, str) or not key for key in values):
        raise ValueError(f"{name} keys must be non-empty strings")
    if value_type is int:
        result = {key: _count(value, f"{name}.{key}") for key, value in values.items()}
    else:
        result = {key: _finite(value, f"{name}.{key}") for key, value in values.items()}
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True)
class EpisodeTelemetry:
    tracking_squared_error_sum: float
    tracking_samples: int
    tracking_lost_steps: int
    union_coverage_cells: int
    duplicate_coverage_visits: int
    coverage_visits: int
    formation_squared_error_sum: float
    formation_samples: int
    gate_crossings: int
    gate_contacts: int
    safety_failures: tuple[str, ...]
    safety_overrides: int
    completed_evidence: tuple[str, ...]
    central_control_commands: int
    disturbance_injections: Mapping[str, int]
    disturbance_minimums: Mapping[str, float]
    disturbance_maximums: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in ("tracking_squared_error_sum", "formation_squared_error_sum"):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} cannot be negative")
            object.__setattr__(self, name, value)
        for name in (
            "tracking_samples",
            "tracking_lost_steps",
            "union_coverage_cells",
            "duplicate_coverage_visits",
            "coverage_visits",
            "formation_samples",
            "gate_crossings",
            "gate_contacts",
            "safety_overrides",
            "central_control_commands",
        ):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        if self.tracking_lost_steps > self.tracking_samples:
            raise ValueError("tracking_lost_steps cannot exceed tracking_samples")
        if self.duplicate_coverage_visits > self.coverage_visits:
            raise ValueError("duplicate coverage visits cannot exceed coverage visits")
        failures = tuple(self.safety_failures)
        evidence = tuple(self.completed_evidence)
        if any(not isinstance(item, str) or not item for item in (*failures, *evidence)):
            raise ValueError("telemetry evidence must contain non-empty strings")
        object.__setattr__(self, "safety_failures", failures)
        object.__setattr__(self, "completed_evidence", tuple(sorted(set(evidence))))
        object.__setattr__(
            self,
            "disturbance_injections",
            _immutable_mapping(
                self.disturbance_injections,
                value_type=int,
                name="disturbance_injections",
            ),
        )
        object.__setattr__(
            self,
            "disturbance_minimums",
            _immutable_mapping(
                self.disturbance_minimums,
                value_type=float,
                name="disturbance_minimums",
            ),
        )
        object.__setattr__(
            self,
            "disturbance_maximums",
            _immutable_mapping(
                self.disturbance_maximums,
                value_type=float,
                name="disturbance_maximums",
            ),
        )
        keys = set(self.disturbance_injections)
        if keys != set(self.disturbance_minimums) or keys != set(self.disturbance_maximums):
            raise ValueError("disturbance evidence keys must match")
        for key in keys:
            if self.disturbance_minimums[key] > self.disturbance_maximums[key]:
                raise ValueError(f"disturbance range is inverted: {key}")

    @classmethod
    def empty(cls, disturbances: Sequence[str] = ()) -> EpisodeTelemetry:
        names = tuple(sorted(set(disturbances)))
        zero_counts = {name: 0 for name in names}
        zero_values = {name: 0.0 for name in names}
        return cls(
            0.0,
            0,
            0,
            0,
            0,
            0,
            0.0,
            0,
            0,
            0,
            (),
            0,
            (),
            0,
            zero_counts,
            zero_values,
            zero_values,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "tracking_squared_error_sum": self.tracking_squared_error_sum,
            "tracking_samples": self.tracking_samples,
            "tracking_lost_steps": self.tracking_lost_steps,
            "union_coverage_cells": self.union_coverage_cells,
            "duplicate_coverage_visits": self.duplicate_coverage_visits,
            "coverage_visits": self.coverage_visits,
            "formation_squared_error_sum": self.formation_squared_error_sum,
            "formation_samples": self.formation_samples,
            "gate_crossings": self.gate_crossings,
            "gate_contacts": self.gate_contacts,
            "safety_failures": list(self.safety_failures),
            "safety_overrides": self.safety_overrides,
            "completed_evidence": list(self.completed_evidence),
            "central_control_commands": self.central_control_commands,
            "disturbance_injections": dict(self.disturbance_injections),
            "disturbance_minimums": dict(self.disturbance_minimums),
            "disturbance_maximums": dict(self.disturbance_maximums),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> EpisodeTelemetry:
        return cls(**dict(values))  # type: ignore[arg-type]

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()
