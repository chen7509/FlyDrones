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

    schema_version = 2
    input_dimension = LocalObservation.dimension
    hidden_dimension = 64
    skill_dimension = len(Skill)
    task_state_offset = 32 + 8
    navigation_goal_offset = 16 + 3

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
        nn.init.zeros_(self.motion_head.weight)
        nn.init.zeros_(self.motion_head.bias)

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
        residual_motion = torch.tanh(self.motion_head(features))
        task_prior, guided_task = self.task_motion_prior(
            observation[:, -1]
        )
        residual_scale = torch.where(
            guided_task,
            torch.full_like(guided_task, 0.01, dtype=residual_motion.dtype),
            torch.ones_like(guided_task, dtype=residual_motion.dtype),
        )
        return (
            self.skill_head(features),
            torch.clamp(
                task_prior + residual_scale * residual_motion,
                -1.0,
                1.0,
            ),
            torch.sigmoid(self.confidence_head(features)).squeeze(-1),
            next_hidden,
        )

    @classmethod
    def task_motion_prior(
        cls, actor_observations: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if actor_observations.shape[-1] != cls.input_dimension:
            raise ValueError(
                f"actor observation must end with {cls.input_dimension} values"
            )
        active = actor_observations[
            ..., cls.task_state_offset:cls.task_state_offset + cls.skill_dimension
        ] > 0.5
        role = actor_observations[..., cls.task_state_offset + 7]
        active, paired, compound = cls._assign_local_roles(active, role)
        single_task = active.sum(dim=-1, keepdim=True) == 1
        navigation_only = active[..., :1] & single_task
        tracking_only = active[..., 1:2] & single_task
        search_only = active[..., 2:3] & single_task
        formation_only = active[..., 3:4] & single_task
        gate_only = active[..., 4:5] & single_task
        navigation_goal = actor_observations[
            ..., cls.navigation_goal_offset:cls.navigation_goal_offset + 3
        ]
        navigation_magnitude = torch.linalg.vector_norm(
            navigation_goal, dim=-1, keepdim=True
        )
        navigation_direction = navigation_goal / torch.clamp(
            navigation_magnitude, min=1e-6
        )
        navigation_speed = torch.clamp(navigation_magnitude * 4.0, max=1.0)
        wind = actor_observations[..., 25:27]
        navigation_motion = navigation_direction * navigation_speed
        navigation_motion = navigation_motion.clone()
        navigation_motion[..., :2] -= wind
        navigation_motion = torch.clamp(navigation_motion, -1.0, 1.0)
        tracking_goal = actor_observations[..., 16:19]
        tracking_magnitude = torch.linalg.vector_norm(
            tracking_goal, dim=-1, keepdim=True
        )
        tracking_direction = tracking_goal / torch.clamp(
            tracking_magnitude, min=1e-6
        )
        tracking_speed = torch.clamp(
            (tracking_magnitude - 0.25) * 4.0, min=-1.0, max=1.0
        )
        tracking_motion = tracking_direction * tracking_speed
        tracking_motion = tracking_motion.clone()
        tracking_motion[..., :2] += actor_observations[..., 30:32] - wind
        tracking_motion = torch.clamp(tracking_motion, -1.0, 1.0)
        role = actor_observations[..., cls.task_state_offset + 7]
        row = torch.clamp(torch.floor((role + 1.0) * 2.0), 0, 3).long()
        paired_row = torch.where(
            role < -0.6,
            torch.zeros_like(row),
            torch.where(
                role < -0.2,
                torch.ones_like(row),
                torch.where(role <= 0.6, torch.full_like(row, 2), torch.full_like(row, 3)),
            ),
        )
        compound_row = torch.clamp(
            torch.floor((role + 0.6) * (4.0 / 1.5)), 0, 3
        ).long()
        row = torch.where(paired, paired_row, row)
        row = torch.where(compound, compound_row, row)
        coverage = actor_observations[..., 48:64]
        columns = torch.arange(4, device=coverage.device)
        row_indices = row.unsqueeze(-1) * 4 + columns
        row_coverage = torch.gather(coverage, -1, row_indices)
        allowed = torch.ones_like(row_coverage, dtype=torch.bool)
        coordinated_search = paired | compound
        support = (role > 0.75) & ~coordinated_search
        primary_top_row = (row == 3) & ~support & ~coordinated_search
        allowed = torch.where(
            support.unsqueeze(-1),
            columns == 3,
            allowed,
        )
        allowed = torch.where(
            primary_top_row.unsqueeze(-1),
            columns < 3,
            allowed,
        )
        available = allowed & (row_coverage < 0.5)
        search_column = torch.argmax(available.to(torch.int64), dim=-1)
        has_search_target = available.any(dim=-1, keepdim=True)
        search_y = -45.0 + 30.0 * row.to(actor_observations.dtype)
        paired_search_y = torch.where(
            row == 1,
            torch.full_like(search_y, -25.0),
            torch.where(row == 2, torch.full_like(search_y, 25.0), search_y),
        )
        search_y = torch.where(coordinated_search, paired_search_y, search_y)
        search_target = torch.stack(
            (
                3.75 + 27.5 * search_column.to(actor_observations.dtype),
                search_y,
                torch.full_like(role, 8.0),
            ),
            dim=-1,
        )
        position_scale = actor_observations.new_tensor((100.0, 60.0, 30.0))
        position = actor_observations[..., 32:35] * position_scale
        search_delta = search_target - position
        search_distance = torch.linalg.vector_norm(
            search_delta, dim=-1, keepdim=True
        )
        search_motion = search_delta / torch.clamp(search_distance, min=1e-6)
        search_motion *= torch.clamp(search_distance / 5.0, max=1.0)
        search_motion = torch.where(
            has_search_target,
            search_motion,
            torch.zeros_like(search_motion),
        )
        search_motion = search_motion.clone()
        search_motion[..., :2] -= wind
        search_motion = torch.clamp(search_motion, -1.0, 1.0)
        formation_target = torch.stack(
            (
                10.0 + 4.0 * role,
                torch.zeros_like(role),
                torch.full_like(role, 8.0),
            ),
            dim=-1,
        )
        formation_delta = formation_target - position
        formation_distance = torch.linalg.vector_norm(
            formation_delta, dim=-1, keepdim=True
        )
        formation_motion = formation_delta / torch.clamp(
            formation_distance, min=1e-6
        )
        formation_motion *= torch.clamp(formation_distance / 5.0, max=1.0)
        formation_motion = formation_motion.clone()
        formation_motion[..., :2] -= wind
        formation_motion = torch.clamp(formation_motion, -1.0, 1.0)
        gate_goal = actor_observations[..., 22:25].clone()
        gate_goal[..., 1] += role * 0.075
        needs_gate_alignment = (
            (torch.abs(gate_goal[..., 1]) > 0.05)
            | (torch.abs(gate_goal[..., 2]) > 0.05)
        )
        gate_goal[..., 0] = torch.where(
            needs_gate_alignment,
            gate_goal[..., 0] - 0.25,
            gate_goal[..., 0] + 0.25,
        )
        gate_distance = torch.linalg.vector_norm(gate_goal, dim=-1, keepdim=True)
        gate_motion = gate_goal / torch.clamp(gate_distance, min=1e-6)
        gate_motion *= torch.clamp(gate_distance * 4.0, max=1.0)
        gate_motion = gate_motion.clone()
        gate_motion[..., :2] -= wind
        gate_motion = torch.clamp(gate_motion, -1.0, 1.0)
        xyz = torch.zeros_like(navigation_goal)
        xyz = torch.where(
            navigation_only,
            navigation_motion,
            xyz,
        )
        xyz = torch.where(
            tracking_only,
            tracking_motion,
            xyz,
        )
        xyz = torch.where(search_only, search_motion, xyz)
        xyz = torch.where(formation_only, formation_motion, xyz)
        xyz = torch.where(gate_only, gate_motion, xyz)
        guided_task = (
            navigation_only
            | tracking_only
            | search_only
            | formation_only
            | gate_only
        )
        return torch.cat((xyz, torch.zeros_like(xyz[..., :1])), dim=-1), guided_task

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
            logits = self.mask_skill_logits(logits, values[:, -1, :])
        skill = tuple(Skill)[int(torch.argmax(logits[0]).item())]
        motion_values = tuple(float(value) for value in motion[0].cpu().numpy())
        return (
            skill,
            motion_values,  # type: ignore[arg-type]
            float(confidence[0].item()),
            PolicyState(next_hidden[0, 0].cpu().numpy()),
        )

    @classmethod
    def mask_skill_logits(
        cls,
        logits: torch.Tensor,
        actor_observations: torch.Tensor,
    ) -> torch.Tensor:
        """Restrict skill selection to tasks declared active in each observation."""
        if logits.shape[-1] != cls.skill_dimension:
            raise ValueError(f"skill logits must end with {cls.skill_dimension} values")
        if actor_observations.shape[-1] != cls.input_dimension:
            raise ValueError(
                f"actor observation must end with {cls.input_dimension} values"
            )
        active = actor_observations[
            ..., cls.task_state_offset:cls.task_state_offset + cls.skill_dimension
        ] > 0.5
        role = actor_observations[..., cls.task_state_offset + 7]
        active, _paired, _compound = cls._assign_local_roles(active, role)
        if active.shape != logits.shape:
            raise ValueError("skill mask shape does not match skill logits")
        masked = torch.where(
            active,
            logits,
            torch.full_like(logits, torch.finfo(logits.dtype).min),
        )
        return torch.where(active.any(dim=-1, keepdim=True), masked, logits)

    @staticmethod
    def _assign_local_roles(
        active: torch.Tensor,
        role: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        paired = active[..., 1] & active[..., 2] & (active.sum(dim=-1) == 2)
        tracker = torch.abs(role) <= 0.2
        active = active.clone()
        active[..., 1] = torch.where(paired, tracker, active[..., 1])
        active[..., 2] = torch.where(paired, ~tracker, active[..., 2])
        compound = active[..., :4].all(dim=-1) & (active.sum(dim=-1) == 4)
        assignments = (
            role < -0.75,
            (role >= -0.75) & (role < -0.6),
            (role >= -0.6) & (role < 0.9),
            role >= 0.9,
        )
        for index, assignment in enumerate(assignments):
            active[..., index] = torch.where(
                compound, assignment, active[..., index]
            )
        return active, paired, compound

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
        if clearance < 1.0:
            try:
                recovery = PolicyIntent(
                    Skill.YIELD_RETURN_LAND,
                    health.recovery_motion,
                    1.0,
                    0.2,
                ).checked()
            except (TypeError, ValueError):
                recovery = self._hold()
            return ProjectionResult(recovery, True, "low-clearance")
        if battery < 35.0:
            return ProjectionResult(
                PolicyIntent(Skill.YIELD_RETURN_LAND, (-0.5, 0.0, 0.0, 0.0), 1.0, 0.5),
                True,
                "low-battery",
            )
        if reflex_override is not None:
            return ProjectionResult(reflex_override.checked(), True, "malecns-reflex")
        checked = intent.checked()
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
