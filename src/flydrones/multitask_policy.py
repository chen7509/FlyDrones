"""Shared recurrent skill policy behind a deterministic safety boundary."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import torch
from torch import nn

from flydrones.multitask_contract import (
    LocalObservation,
    PolicyIntent,
    SafetySnapshot,
    Skill,
)


def _immutable_hidden(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float32)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ValueError("policy hidden state must be a finite vector")
    result = result.copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class PolicyState:
    hidden: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "hidden", _immutable_hidden(self.hidden))

    @classmethod
    def zeros(cls, size: int) -> PolicyState:
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("policy state size must be positive")
        return cls(np.zeros(size, dtype=np.float32))


class Actor(Protocol):
    def act(
        self,
        observation: LocalObservation,
        state: PolicyState,
    ) -> tuple[Skill, tuple[float, float, float, float], float, PolicyState]: ...


class SharedRecurrentPolicy(nn.Module):
    """One shared deployment actor for every vehicle."""

    schema_version = 1
    input_dimension = LocalObservation.dimension
    hidden_dimension = 64
    skill_dimension = len(Skill)

    def __init__(self) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(self.input_dimension, 96),
            nn.Tanh(),
        )
        self.memory = nn.GRU(96, self.hidden_dimension, batch_first=True)
        self.skill_head = nn.Linear(self.hidden_dimension, self.skill_dimension)
        self.motion_head = nn.Linear(self.hidden_dimension, 4)
        self.confidence_head = nn.Linear(self.hidden_dimension, 1)

    def forward(
        self,
        observation: torch.Tensor,
        hidden: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if observation.ndim == 2:
            observation = observation.unsqueeze(1)
        if observation.ndim != 3 or observation.shape[-1] != self.input_dimension:
            raise ValueError(f"actor observation must end with {self.input_dimension} values")
        if hidden.ndim == 2:
            hidden = hidden.unsqueeze(0)
        if hidden.ndim != 3 or hidden.shape[-1] != self.hidden_dimension:
            raise ValueError(f"actor hidden state must end with {self.hidden_dimension} values")
        encoded = self.encoder(observation)
        recurrent, next_hidden = self.memory(encoded, hidden)
        features = recurrent[:, -1]
        return (
            self.skill_head(features),
            torch.tanh(self.motion_head(features)),
            torch.sigmoid(self.confidence_head(features)).squeeze(-1),
            next_hidden,
        )

    def act(
        self,
        observation: LocalObservation,
        state: PolicyState,
    ) -> tuple[Skill, tuple[float, float, float, float], float, PolicyState]:
        if state.hidden.shape != (self.hidden_dimension,):
            raise ValueError(f"policy state must contain {self.hidden_dimension} values")
        actor_vector = observation.actor_vector()
        with torch.no_grad():
            values = torch.tensor(actor_vector, dtype=torch.float32).reshape(1, 1, -1)
            hidden = torch.tensor(state.hidden, dtype=torch.float32).reshape(1, 1, -1)
            logits, motion, confidence, next_hidden = self(values, hidden)
        skill = tuple(Skill)[int(torch.argmax(logits[0]).item())]
        motion_values = tuple(float(value) for value in motion[0].cpu().numpy())
        return (
            skill,
            motion_values,  # type: ignore[arg-type]
            float(confidence[0].item()),
            PolicyState(next_hidden[0, 0].cpu().numpy()),
        )

    def export(self, path: str | Path) -> None:
        payload = {
            "schema_version": self.schema_version,
            "input_dimension": self.input_dimension,
            "hidden_dimension": self.hidden_dimension,
            "skill_dimension": self.skill_dimension,
            "actor_state_dict": self.state_dict(),
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        torch.save(payload, temporary)
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> SharedRecurrentPolicy:
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
        expected = {
            "schema_version": cls.schema_version,
            "input_dimension": cls.input_dimension,
            "hidden_dimension": cls.hidden_dimension,
            "skill_dimension": cls.skill_dimension,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise ValueError(f"checkpoint {key} is incompatible")
        model = cls()
        model.load_state_dict(payload["actor_state_dict"])
        return model


class CentralizedCritic(nn.Module):
    """Training-only value model; never included in actor exports."""

    def __init__(self, input_dimension: int, hidden_dimension: int = 128) -> None:
        super().__init__()
        if input_dimension <= 0 or hidden_dimension <= 0:
            raise ValueError("critic dimensions must be positive")
        self.network = nn.Sequential(
            nn.Linear(input_dimension, hidden_dimension),
            nn.Tanh(),
            nn.Linear(hidden_dimension, hidden_dimension),
            nn.Tanh(),
            nn.Linear(hidden_dimension, 1),
        )

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        return self.network(observation).squeeze(-1)


@dataclass(frozen=True)
class ProjectionResult:
    intent: PolicyIntent
    overrode: bool
    reason: str


class SafetyProjector:
    """Frozen action shield applied after the learned actor."""

    @staticmethod
    def _hold() -> PolicyIntent:
        return PolicyIntent(Skill.YIELD_RETURN_LAND, (0.0, 0.0, 0.0, 0.0), 1.0, 0.2)

    def project(
        self,
        intent: PolicyIntent,
        health: SafetySnapshot,
        *,
        reflex_override: PolicyIntent | None = None,
    ) -> ProjectionResult:
        try:
            battery = float(health.battery_pct)
            clearance = float(health.minimum_clearance_m)
            valid_health = (
                math.isfinite(battery)
                and math.isfinite(clearance)
                and health.localization_healthy is True
                and health.sensors_healthy is True
                and health.emergency_active is False
            )
        except (TypeError, ValueError):
            valid_health = False
            battery = math.nan
            clearance = math.nan
        if not valid_health:
            return ProjectionResult(self._hold(), True, "unhealthy")
        if reflex_override is not None:
            return ProjectionResult(reflex_override.checked(), True, "malecns-reflex")
        if battery < 35.0:
            return ProjectionResult(
                PolicyIntent(Skill.YIELD_RETURN_LAND, (-0.5, 0.0, 0.0, 0.0), 1.0, 0.5),
                True,
                "low-battery",
            )
        checked = intent.checked()
        if clearance < 0.65:
            turn = -1.0 if checked.motion[1] > 0.0 else 1.0
            return ProjectionResult(
                PolicyIntent(Skill.YIELD_RETURN_LAND, (0.0, turn, 0.0, turn), 1.0, 0.2),
                True,
                "low-clearance",
            )
        return ProjectionResult(checked, False, "accepted")


class SafetyArbiter:
    """Share safety preflight, projection, and skill hysteresis across callers."""

    def __init__(self, projector: SafetyProjector) -> None:
        self.projector = projector
        self._current_intent: PolicyIntent | None = None
        self._hold_until = -math.inf
        self._pending_skill: Skill | None = None
        self._pending_count = 0

    @staticmethod
    def _hold() -> PolicyIntent:
        return PolicyIntent(
            Skill.YIELD_RETURN_LAND,
            (0.0, 0.0, 0.0, 0.0),
            1.0,
            0.2,
        )

    def preflight(
        self,
        health: SafetySnapshot,
        *,
        reflex_override: PolicyIntent | None = None,
    ) -> ProjectionResult | None:
        result = self.projector.project(
            self._hold(), health, reflex_override=reflex_override
        )
        return result if result.overrode else None

    def _apply_hysteresis(
        self,
        intent: PolicyIntent,
        *,
        now: float,
        task_completed: bool,
    ) -> PolicyIntent:
        if not math.isfinite(now):
            raise ValueError("arbitration time must be finite")
        if self._current_intent is None or task_completed:
            self._current_intent = intent
            self._hold_until = now + intent.hold_time_s
            self._pending_skill = None
            self._pending_count = 0
            return intent
        if intent.skill is self._current_intent.skill:
            self._current_intent = intent
            self._hold_until = max(self._hold_until, now + intent.hold_time_s)
            self._pending_skill = None
            self._pending_count = 0
            return intent
        if now < self._hold_until:
            return self._current_intent
        if self._pending_skill is intent.skill:
            self._pending_count += 1
        else:
            self._pending_skill = intent.skill
            self._pending_count = 1
        if self._pending_count < 2:
            return self._current_intent
        self._current_intent = intent
        self._hold_until = now + intent.hold_time_s
        self._pending_skill = None
        self._pending_count = 0
        return intent

    def resolve(
        self,
        proposed: PolicyIntent,
        health: SafetySnapshot,
        *,
        now: float,
        reflex_override: PolicyIntent | None = None,
        task_completed: bool = False,
    ) -> ProjectionResult:
        projected = self.projector.project(
            proposed, health, reflex_override=reflex_override
        )
        if projected.overrode:
            return projected
        resolved = self._apply_hysteresis(
            projected.intent,
            now=now,
            task_completed=task_completed,
        )
        return ProjectionResult(resolved, False, "accepted")


@dataclass(frozen=True)
class SafePolicyResult:
    intent: PolicyIntent
    state: PolicyState
    safety_overrode: bool
    reason: str
    latency_ms: float


class SafePolicy:
    """Measure, validate, debounce, and project actor decisions."""

    def __init__(
        self,
        actor: Actor,
        projector: SafetyProjector,
        maximum_latency_ms: float = 35.0,
    ) -> None:
        if not math.isfinite(maximum_latency_ms) or maximum_latency_ms <= 0.0:
            raise ValueError("maximum_latency_ms must be positive")
        self.actor = actor
        self.projector = projector
        self.arbiter = SafetyArbiter(projector)
        self.maximum_latency_ms = maximum_latency_ms

    @staticmethod
    def _fallback() -> PolicyIntent:
        return PolicyIntent(Skill.YIELD_RETURN_LAND, (0.0, 0.0, 0.0, 0.0), 1.0, 0.2)

    def act(
        self,
        observation: LocalObservation,
        state: PolicyState,
        health: SafetySnapshot,
        *,
        reflex_override: PolicyIntent | None = None,
        task_completed: bool = False,
        now: float | None = None,
    ) -> SafePolicyResult:
        start = time.perf_counter()
        arbitration_time = start if now is None else float(now)
        next_state = state
        try:
            preflight = self.arbiter.preflight(
                health,
                reflex_override=reflex_override,
            )
        except (TypeError, ValueError, RuntimeError):
            latency = (time.perf_counter() - start) * 1000.0
            return SafePolicyResult(self._fallback(), state, True, "invalid-safety-input", latency)
        if preflight is not None:
            latency = (time.perf_counter() - start) * 1000.0
            return SafePolicyResult(preflight.intent, state, True, preflight.reason, latency)
        try:
            skill, motion, confidence, next_state = self.actor.act(observation, state)
            learned = PolicyIntent(skill, motion, confidence, 0.2).checked()
        except (TypeError, ValueError, RuntimeError):
            latency = (time.perf_counter() - start) * 1000.0
            return SafePolicyResult(self._fallback(), state, True, "invalid-output", latency)
        latency = (time.perf_counter() - start) * 1000.0
        if not math.isfinite(latency) or latency > self.maximum_latency_ms:
            return SafePolicyResult(self._fallback(), state, True, "deadline", latency)
        try:
            projected = self.arbiter.resolve(
                learned,
                health,
                now=arbitration_time,
                task_completed=task_completed,
            )
        except (TypeError, ValueError, RuntimeError):
            return SafePolicyResult(
                self._fallback(), state, True, "invalid-safety-input", latency
            )
        if projected.overrode:
            return SafePolicyResult(
                projected.intent,
                next_state,
                True,
                projected.reason,
                latency,
            )
        return SafePolicyResult(
            projected.intent, next_state, False, projected.reason, latency
        )
