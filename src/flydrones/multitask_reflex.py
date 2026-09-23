"""Adapt the live MaleCNS policy into auditable multitask reflex overrides."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .multitask_contract import LocalObservation, PolicyIntent, Skill


@dataclass(frozen=True)
class ReflexEvidence:
    source: str
    neurons: int
    connections: int
    neural_updates: int
    fallback_calls: int
    p95_ms: float


@dataclass(frozen=True)
class ReflexDecision:
    intent: PolicyIntent | None
    evidence: ReflexEvidence


class ReflexBridge(Protocol):
    def evaluate(self, observation: LocalObservation) -> ReflexDecision: ...


class GeometricReflexBridge:
    """Deterministic local depth reflex for training without a connectome."""

    source = "geometric-v1"

    def __init__(
        self,
        *,
        trigger_proximity: float = 0.75,
        direction_margin: float = 0.05,
        turn_strength: float = 0.8,
    ) -> None:
        values = (trigger_proximity, direction_margin, turn_strength)
        if not all(np.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            raise ValueError("geometric reflex values must be finite and between zero and one")
        self.trigger_proximity = float(trigger_proximity)
        self.direction_margin = float(direction_margin)
        self.turn_strength = float(turn_strength)
        self.calls = 0
        self.overrides = 0

    def evaluate(self, observation: LocalObservation) -> ReflexDecision:
        if not isinstance(observation, LocalObservation):
            raise TypeError("observation must be a LocalObservation")
        self.calls += 1
        depth = np.asarray(observation.visual_features[:16], dtype=np.float32)
        front = float(np.max(depth[7:10]))
        intent = None
        if front >= self.trigger_proximity:
            self.overrides += 1
            left = float(np.max(depth[9:13]))
            right = float(np.max(depth[4:8]))
            difference = left - right
            if abs(difference) <= self.direction_margin:
                motion = (0.0, 0.0, 0.0, 0.0)
            else:
                turn = -self.turn_strength if difference > 0.0 else self.turn_strength
                heading = float(observation.flight_state[-1]) * math.pi
                motion = (
                    self._clean(-turn * math.sin(heading)),
                    self._clean(turn * math.cos(heading)),
                    0.0,
                    turn,
                )
            intent = PolicyIntent(Skill.YIELD_RETURN_LAND, motion, 1.0, 0.2)
        elif float(np.max(depth)) >= self.trigger_proximity:
            self.overrides += 1
            obstacle_index = int(np.argmax(depth))
            obstacle_angle = -math.pi + obstacle_index * (2.0 * math.pi / 16.0)
            heading = float(observation.flight_state[-1]) * math.pi
            escape_angle = heading + obstacle_angle + math.pi
            lateral = math.sin(obstacle_angle)
            yaw = 0.0
            if abs(lateral) > self.direction_margin:
                yaw = -math.copysign(self.turn_strength, lateral)
            motion = (
                self._clean(self.turn_strength * math.cos(escape_angle)),
                self._clean(self.turn_strength * math.sin(escape_angle)),
                0.0,
                yaw,
            )
            intent = PolicyIntent(Skill.YIELD_RETURN_LAND, motion, 1.0, 0.2)
        return ReflexDecision(
            intent,
            ReflexEvidence(self.source, 0, 0, 0, 0, 0.0),
        )

    @staticmethod
    def _clean(value: float) -> float:
        rounded = round(float(value), 6)
        return 0.0 if abs(rounded) < 1e-6 else rounded


class MaleCNSReflexBridge:
    """Own one MaleCNS policy instance and convert decoded commands to overrides."""

    expected_source = "malecns-v1.0-live"
    expected_neurons = 166_700
    expected_connections = 25_582_837

    def __init__(self, policy, *, require_live: bool = True) -> None:
        self.policy = policy
        self.require_live = bool(require_live)
        self._bridge_fallbacks = 0

    @staticmethod
    def _hold() -> PolicyIntent:
        return PolicyIntent(
            Skill.YIELD_RETURN_LAND,
            (0.0, 0.0, 0.0, 0.0),
            1.0,
            0.2,
        )

    @staticmethod
    def _policy_input(observation: LocalObservation) -> np.ndarray:
        depth = np.asarray(observation.visual_features[:16], dtype=np.float32)
        sectors = np.interp(
            np.linspace(0.0, 15.0, 9),
            np.arange(16, dtype=np.float32),
            depth,
        ).astype(np.float32)
        result = np.zeros(16, dtype=np.float32)
        result[5:14] = np.clip(sectors, 0.0, 1.0)
        return result

    def _evidence(self) -> ReflexEvidence:
        metrics = dict(getattr(self.policy, "metrics", {}) or {})
        return ReflexEvidence(
            source=str(metrics.get("source", getattr(self.policy, "source", "unknown"))),
            neurons=int(metrics.get("neurons", 0)),
            connections=int(metrics.get("connections", 0)),
            neural_updates=int(metrics.get("neural_updates", 0)),
            fallback_calls=int(metrics.get("fallback_calls", 0)) + self._bridge_fallbacks,
            p95_ms=float(metrics.get("neural_update_p95_ms", 0.0)),
        )

    def _validate_live(self, evidence: ReflexEvidence) -> None:
        if not self.require_live:
            return
        valid = (
            evidence.source == self.expected_source
            and evidence.neurons == self.expected_neurons
            and evidence.connections == self.expected_connections
            and evidence.fallback_calls == 0
        )
        if not valid:
            raise RuntimeError(
                "MaleCNS live backend evidence is invalid: "
                f"source={evidence.source}, neurons={evidence.neurons}, "
                f"connections={evidence.connections}, fallbacks={evidence.fallback_calls}"
            )

    def evaluate(self, observation: LocalObservation) -> ReflexDecision:
        try:
            action = np.asarray(
                self.policy.predict(self._policy_input(observation)), dtype=np.float32
            ).reshape(-1)
            if action.shape != (2,) or not np.all(np.isfinite(action)):
                raise ValueError("MaleCNS action must contain two finite values")
        except Exception as exc:
            self._bridge_fallbacks += 1
            evidence = self._evidence()
            if self.require_live:
                raise RuntimeError("MaleCNS live backend failed") from exc
            return ReflexDecision(self._hold(), evidence)

        evidence = self._evidence()
        self._validate_live(evidence)
        note = getattr(self.policy, "last_command_note", None)
        if note == "malecns:go":
            return ReflexDecision(None, evidence)
        if note == "malecns:brake":
            return ReflexDecision(self._hold(), evidence)
        if note == "malecns:turn-away":
            yaw = round(float(np.clip(action[1], -1.0, 1.0)), 6)
            intent = PolicyIntent(
                Skill.YIELD_RETURN_LAND,
                (0.0, yaw, 0.0, yaw),
                1.0,
                0.2,
            )
            return ReflexDecision(intent, evidence)

        self._bridge_fallbacks += 1
        evidence = self._evidence()
        if self.require_live:
            raise RuntimeError(f"MaleCNS returned unsupported command note: {note!r}")
        return ReflexDecision(self._hold(), evidence)
