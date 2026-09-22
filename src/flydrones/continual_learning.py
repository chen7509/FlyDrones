"""Fail-closed gates for bounded continual adaptation."""

from __future__ import annotations

import hashlib
import hmac
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from flydrones.multitask_contract import SafetySnapshot, Skill


def _digest_ok(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True)
class SignedCheckpoint:
    schema_version: int
    version: str
    payload: bytes
    payload_digest: str
    frozen_hash: str
    signature: str

    @staticmethod
    def _message(
        schema_version: int,
        version: str,
        payload_digest: str,
        frozen_hash: str,
    ) -> bytes:
        return f"{schema_version}|{version}|{payload_digest}|{frozen_hash}".encode()

    @classmethod
    def create(
        cls,
        version: str,
        payload: bytes,
        *,
        key: bytes,
        frozen_hash: str,
    ) -> SignedCheckpoint:
        if not isinstance(version, str) or not version:
            raise ValueError("checkpoint version cannot be empty")
        if not isinstance(payload, bytes):
            raise TypeError("checkpoint payload must be bytes")
        if not isinstance(key, bytes) or not key:
            raise ValueError("checkpoint signing key cannot be empty")
        if not _digest_ok(frozen_hash):
            raise ValueError("frozen_hash must be a lowercase SHA-256 digest")
        digest = hashlib.sha256(payload).hexdigest()
        message = cls._message(1, version, digest, frozen_hash)
        signature = hmac.new(key, message, hashlib.sha256).hexdigest()
        return cls(1, version, payload, digest, frozen_hash, signature)

    def verify(self, key: bytes) -> bool:
        if not isinstance(key, bytes) or not key:
            return False
        if self.schema_version != 1 or not _digest_ok(self.frozen_hash):
            return False
        actual_digest = hashlib.sha256(self.payload).hexdigest()
        if not hmac.compare_digest(actual_digest, self.payload_digest):
            return False
        expected = hmac.new(
            key,
            self._message(
                self.schema_version,
                self.version,
                self.payload_digest,
                self.frozen_hash,
            ),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, self.signature)

    def tampered(self) -> SignedCheckpoint:
        replacement = "0" if self.signature[-1] != "0" else "1"
        return SignedCheckpoint(
            self.schema_version,
            self.version,
            self.payload,
            self.payload_digest,
            self.frozen_hash,
            self.signature[:-1] + replacement,
        )


@dataclass(frozen=True)
class ResidualAdapter:
    frozen_hash: str
    skill_bias: Mapping[str, float]
    duration_scale: float
    energy_scale: float
    skill_parameters: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not _digest_ok(self.frozen_hash):
            raise ValueError("frozen_hash must be a lowercase SHA-256 digest")
        expected = {skill.value for skill in Skill}
        if set(self.skill_bias) != expected:
            raise ValueError("skill_bias must contain every skill exactly once")
        clean_bias: dict[str, float] = {}
        for key, value in self.skill_bias.items():
            number = float(value)
            if not math.isfinite(number) or abs(number) > 0.25:
                raise ValueError("skill biases must be finite and bounded")
            clean_bias[key] = number
        object.__setattr__(self, "skill_bias", MappingProxyType(clean_bias))
        if not all(
            math.isfinite(float(value)) and 0.5 <= float(value) <= 1.5
            for value in (self.duration_scale, self.energy_scale)
        ):
            raise ValueError("bid estimate scales must stay between 0.5 and 1.5")
        if len(self.skill_parameters) != 4 or not all(
            math.isfinite(float(value)) and abs(float(value)) <= 0.25
            for value in self.skill_parameters
        ):
            raise ValueError("skill parameters must contain four bounded values")

    @classmethod
    def zeros(cls, *, frozen_hash: str) -> ResidualAdapter:
        return cls(
            frozen_hash,
            {skill.value: 0.0 for skill in Skill},
            1.0,
            1.0,
            (0.0, 0.0, 0.0, 0.0),
        )

    def update(
        self,
        *,
        skill_advantages: Mapping[str, float],
        bid_errors: tuple[float, float],
        health: SafetySnapshot,
        learning_rate: float,
    ) -> ResidualAdapter:
        if not health.can_learn:
            raise ValueError("online update requires a healthy safety snapshot")
        rate = float(learning_rate)
        if not math.isfinite(rate) or not 0.0 < rate <= 1.0:
            raise ValueError("learning_rate must be in (0, 1]")
        unknown = set(skill_advantages) - set(self.skill_bias)
        if unknown:
            raise ValueError(f"unknown skills: {sorted(unknown)}")
        updated = dict(self.skill_bias)
        for skill, advantage in skill_advantages.items():
            value = float(advantage)
            if not math.isfinite(value):
                raise ValueError("skill advantages must be finite")
            delta = max(-0.05, min(0.05, rate * value))
            updated[skill] = max(-0.25, min(0.25, updated[skill] + delta))
        if len(bid_errors) != 2 or not all(math.isfinite(float(value)) for value in bid_errors):
            raise ValueError("bid_errors must contain two finite values")
        duration_delta = max(-0.05, min(0.05, rate * float(bid_errors[0])))
        energy_delta = max(-0.05, min(0.05, rate * float(bid_errors[1])))
        return ResidualAdapter(
            self.frozen_hash,
            updated,
            max(0.5, min(1.5, self.duration_scale + duration_delta)),
            max(0.5, min(1.5, self.energy_scale + energy_delta)),
            self.skill_parameters,
        )


@dataclass(frozen=True)
class ShadowOutcome:
    skill: str
    success: bool
    collision: bool
    probabilities: tuple[float, ...]


@dataclass(frozen=True)
class CandidateMetrics:
    shadow_only: bool
    collisions: int
    policy_kl: float
    candidate_success_by_skill: Mapping[str, float]
    baseline_success_by_skill: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_success_by_skill",
            MappingProxyType(dict(self.candidate_success_by_skill)),
        )
        object.__setattr__(
            self,
            "baseline_success_by_skill",
            MappingProxyType(dict(self.baseline_success_by_skill)),
        )


class ShadowPolicyRunner:
    """Compare policies off-control on the same immutable records."""

    def __init__(
        self,
        stable: Callable[[object], ShadowOutcome],
        candidate: Callable[[object], ShadowOutcome],
    ) -> None:
        self._stable = stable
        self._candidate = candidate

    def compare(self, records: Iterable[object]) -> CandidateMetrics:
        stable_success: dict[str, list[float]] = defaultdict(list)
        candidate_success: dict[str, list[float]] = defaultdict(list)
        collisions = 0
        divergences: list[float] = []
        count = 0
        for record in records:
            baseline = self._stable(record)
            candidate = self._candidate(record)
            if baseline.skill != candidate.skill:
                raise ValueError("shadow outcomes must report the same evaluated skill")
            if len(baseline.probabilities) != len(candidate.probabilities):
                raise ValueError("shadow probability dimensions differ")
            base_probabilities = tuple(float(value) for value in baseline.probabilities)
            candidate_probabilities = tuple(float(value) for value in candidate.probabilities)
            if not base_probabilities or any(value <= 0.0 for value in (*base_probabilities, *candidate_probabilities)):
                raise ValueError("shadow probabilities must be positive")
            divergences.append(sum(
                left * math.log(left / right)
                for left, right in zip(base_probabilities, candidate_probabilities)
            ))
            stable_success[baseline.skill].append(float(baseline.success))
            candidate_success[candidate.skill].append(float(candidate.success))
            collisions += int(candidate.collision)
            count += 1
        if count == 0:
            raise ValueError("shadow evaluation needs at least one record")
        return CandidateMetrics(
            True,
            collisions,
            sum(divergences) / count,
            {key: sum(values) / len(values) for key, values in candidate_success.items()},
            {key: sum(values) / len(values) for key, values in stable_success.items()},
        )


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]


class ContinualLearningGate:
    def __init__(self, *, key: bytes, maximum_skill_drop: float, maximum_kl: float) -> None:
        if not isinstance(key, bytes) or not key:
            raise ValueError("gate key cannot be empty")
        self.key = key
        self.maximum_skill_drop = float(maximum_skill_drop)
        self.maximum_kl = float(maximum_kl)
        if not 0.0 <= self.maximum_skill_drop <= 1.0:
            raise ValueError("maximum_skill_drop must be between zero and one")
        if not math.isfinite(self.maximum_kl) or self.maximum_kl < 0.0:
            raise ValueError("maximum_kl must be non-negative")

    def evaluate(
        self,
        base: SignedCheckpoint,
        candidate: SignedCheckpoint,
        metrics: CandidateMetrics,
        health: SafetySnapshot,
    ) -> PromotionDecision:
        reasons: list[str] = []
        if not base.verify(self.key):
            reasons.append("invalid-base-signature")
        if not candidate.verify(self.key):
            reasons.append("invalid-candidate-signature")
        if base.frozen_hash != candidate.frozen_hash:
            reasons.append("frozen-base-mismatch")
        if base.version == candidate.version:
            reasons.append("version-not-advanced")
        if not health.can_learn:
            reasons.append("unhealthy")
        if metrics.shadow_only is not True:
            reasons.append("shadow-evaluation-required")
        if isinstance(metrics.collisions, bool) or metrics.collisions != 0:
            reasons.append("collisions")
        try:
            policy_kl = float(metrics.policy_kl)
        except (TypeError, ValueError):
            policy_kl = math.inf
        if not math.isfinite(policy_kl) or policy_kl > self.maximum_kl:
            reasons.append("policy-kl")
        candidate_keys = set(metrics.candidate_success_by_skill)
        baseline_keys = set(metrics.baseline_success_by_skill)
        if candidate_keys != baseline_keys or not candidate_keys:
            reasons.append("skill-metric-keys")
        else:
            for skill in sorted(candidate_keys):
                try:
                    candidate_value = float(metrics.candidate_success_by_skill[skill])
                    baseline_value = float(metrics.baseline_success_by_skill[skill])
                except (TypeError, ValueError):
                    reasons.append(f"invalid-skill-metric:{skill}")
                    continue
                if not all(
                    math.isfinite(value) and 0.0 <= value <= 1.0
                    for value in (candidate_value, baseline_value)
                ):
                    reasons.append(f"invalid-skill-metric:{skill}")
                elif baseline_value - candidate_value > self.maximum_skill_drop + 1e-12:
                    reasons.append(f"skill-regression:{skill}")
        return PromotionDecision(not reasons, tuple(reasons))


@dataclass(frozen=True)
class CanaryEvent:
    vehicle_id: int
    version: str
    event: str
    detail: str | None


class CanaryController:
    maximum_latency_ms = 35.0

    def __init__(self, stable: SignedCheckpoint) -> None:
        self.stable = stable
        self.active = stable
        self.canary_vehicle_id: int | None = None
        self.rollback_reason: str | None = None
        self._events: list[CanaryEvent] = []

    @property
    def audit_events(self) -> tuple[CanaryEvent, ...]:
        return tuple(self._events)

    def activate(self, candidate: SignedCheckpoint, *, vehicle_id: int) -> None:
        if isinstance(vehicle_id, bool) or not isinstance(vehicle_id, int) or vehicle_id < 0:
            raise ValueError("canary vehicle_id must be non-negative")
        if candidate.frozen_hash != self.stable.frozen_hash:
            raise ValueError("candidate frozen base does not match stable base")
        self.active = candidate
        self.canary_vehicle_id = vehicle_id
        self.rollback_reason = None
        self._events.append(CanaryEvent(vehicle_id, candidate.version, "activate", None))

    def observe(
        self,
        *,
        vehicle_id: int,
        safety_failure: str | None,
        latency_ms: float,
    ) -> None:
        if self.canary_vehicle_id is None or vehicle_id != self.canary_vehicle_id:
            raise ValueError("observation is not from the active canary vehicle")
        latency = float(latency_ms)
        reason: str | None = None
        if safety_failure:
            reason = safety_failure
        elif not math.isfinite(latency):
            reason = "nonfinite-latency"
        elif latency > self.maximum_latency_ms:
            reason = "deadline"
        if reason is not None:
            failed_version = self.active.version
            self.active = self.stable
            self.rollback_reason = reason
            self._events.append(CanaryEvent(vehicle_id, failed_version, "rollback", reason))

    def peer_announcement(self) -> dict[str, object]:
        return {
            "schema_version": self.active.schema_version,
            "version": self.active.version,
            "payload_digest": self.active.payload_digest,
            "frozen_hash": self.active.frozen_hash,
        }
