"""Mission-phase adapter that gates learned preferences through local planning."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .local_planner import (
    HybridLocalPlanner,
    LocalPlannerConfig,
    PlannerDecision,
    PlannerPeer,
)
from .motor.command import FlightCommand


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


class HybridPlannerAgent:
    """Combine a learned navigation preference with deterministic safety gates."""

    def __init__(
        self,
        vehicle_id: int,
        rally_target: tuple[float, float],
        policy,
        *,
        config: LocalPlannerConfig,
        target_altitude_m: float = 1.8,
        corridor_center_y: float | None = None,
        deadlock_land_after_s: float = 3.0,
        enable_local_bypass: bool = True,
    ) -> None:
        if len(rally_target) != 2 or not all(math.isfinite(float(value)) for value in rally_target):
            raise ValueError("rally target must contain two finite coordinates")
        if not math.isfinite(float(target_altitude_m)):
            raise ValueError("target altitude must be finite")
        if not math.isfinite(float(deadlock_land_after_s)) or deadlock_land_after_s <= 0.0:
            raise ValueError("deadlock landing delay must be finite and positive")

        self.vehicle_id = int(vehicle_id)
        self.rally_target = (float(rally_target[0]), float(rally_target[1]))
        self.policy = policy
        self.config = config
        self.target_altitude_m = float(target_altitude_m)
        self.corridor_center_y = (
            self.rally_target[1] if corridor_center_y is None else float(corridor_center_y)
        )
        if not math.isfinite(self.corridor_center_y):
            raise ValueError("corridor centre must be finite")
        self.deadlock_land_after_s = float(deadlock_land_after_s)
        self.enable_local_bypass = bool(enable_local_bypass)
        self.planner = HybridLocalPlanner(config)
        self.phase = "escaping"
        self.previous_action = np.zeros(2, dtype=np.float32)
        self.policy_calls = 0
        self.should_land = False
        self.last_decision: PlannerDecision | None = None
        self._hold_started_at: float | None = None
        self._bypass_target: tuple[float, float] | None = None
        self._bypass_until_x = -math.inf
        self._bypass_y: float | None = None
        self._bypass_stage: str | None = None
        self._bypass_brake_started_at = -math.inf

    @property
    def active_target(self) -> tuple[float, float]:
        return self._bypass_target or self.rally_target

    @staticmethod
    def _empty_rejections() -> dict[str, int]:
        return {"unknown": 0, "static": 0, "peer": 0, "corridor": 0, "invalid": 0}

    def _record_decision(self, decision: PlannerDecision, *, now: float) -> FlightCommand:
        if decision.mode.startswith("hold"):
            if self._hold_started_at is None:
                self._hold_started_at = now
            elif now - self._hold_started_at >= self.deadlock_land_after_s:
                self.should_land = True
        else:
            self._hold_started_at = None

        self.last_decision = decision
        return decision.command

    def _hold(self, *, now: float, throttle: float, mode: str) -> FlightCommand:
        command = FlightCommand(throttle=throttle, note=mode)
        decision = PlannerDecision(
            command=command,
            mode=mode,
            candidate_id="hold",
            minimum_static_clearance_m=None,
            minimum_peer_separation_m=None,
            generated_candidates=0,
            rejection_counts=self._empty_rejections(),
            planning_time_ms=0.0,
        )
        return self._record_decision(decision, now=now)

    def _learned_observation(
        self,
        *,
        global_position: tuple[float, float, float],
        yaw_rad: float,
        depth_observation,
    ) -> np.ndarray:
        error_x = self.rally_target[0] - global_position[0]
        error_y = self.rally_target[1] - global_position[1]
        distance = math.hypot(error_x, error_y)
        world_heading = math.pi / 2.0 - yaw_rad
        bearing = _wrap_angle(math.atan2(error_y, error_x) - world_heading)
        rays = np.asarray(depth_observation.ray_distances_m, dtype=np.float32)
        proximity = 1.0 - np.clip(rays / self.config.sensor_range_m, 0.0, 1.0)
        observation = np.concatenate(
            (
                np.asarray(
                    (
                        np.clip(distance / 10.0, 0.0, 1.0),
                        math.sin(bearing),
                        math.cos(bearing),
                        np.clip((self.previous_action[0] + 1.0) * 0.5, 0.0, 1.0),
                        0.0,
                    ),
                    dtype=np.float32,
                ),
                proximity.astype(np.float32),
                self.previous_action,
            )
        )
        return np.clip(observation, -1.0, 1.0).astype(np.float32)

    def _policy_preference(self, observation: np.ndarray) -> FlightCommand:
        raw = self.policy.predict(observation)
        # Stable-Baselines returns (action, state); the exported NumPy policy
        # returns the action directly.
        if isinstance(raw, tuple) and len(raw) == 2:
            raw = raw[0]
        action = np.asarray(raw, dtype=np.float32).reshape(-1)
        if action.shape != (2,) or not np.all(np.isfinite(action)):
            raise ValueError("learned policy must return two finite actions")
        action = np.clip(action, -1.0, 1.0)
        self.previous_action = action.copy()
        self.policy_calls += 1
        return FlightCommand(
            forward=float((action[0] + 1.0) * 0.5),
            yaw=-float(action[1]),
            note="learned-preference",
        )

    def _update_local_bypass(
        self,
        now: float,
        position: tuple[float, float, float],
        velocity: tuple[float, float, float],
        depth_observation,
    ) -> None:
        if not self.enable_local_bypass:
            return
        if self.phase != "escaping":
            self._bypass_target = None
            self._bypass_y = None
            self._bypass_stage = None
            self._bypass_brake_started_at = -math.inf
            return
        if self._bypass_target is not None and position[0] >= self._bypass_until_x:
            self._bypass_target = None
            self._bypass_y = None
            self._bypass_stage = None
            self._bypass_brake_started_at = -math.inf
        if (
            self._bypass_target is not None
            and self._bypass_y is not None
            and self._bypass_stage == "lateral"
            and abs(position[1] - self._bypass_y) <= 0.20
        ):
            self._bypass_stage = "braking"
            self._bypass_brake_started_at = now
            self._bypass_target = (position[0], position[1])
        if (
            self._bypass_target is not None
            and self._bypass_y is not None
            and self._bypass_stage == "braking"
            and now - self._bypass_brake_started_at >= 1.0
            and math.hypot(velocity[0], velocity[1]) <= 0.12
        ):
            self._bypass_stage = "forward"
            self._bypass_target = (self._bypass_until_x, self._bypass_y)
        if self._bypass_target is not None:
            return

        rays = tuple(float(value) for value in depth_observation.ray_distances_m)
        nearest_ahead = min(rays)
        if nearest_ahead >= 2.40:
            return
        self._bypass_until_x = position[0] + max(1.40, nearest_ahead + 0.85)
        self._bypass_y = self.corridor_center_y + 1.00
        self._bypass_stage = "lateral"
        self._bypass_target = (position[0] + 0.25, self._bypass_y)

    def command(
        self,
        *,
        now: float,
        global_position: tuple[float, float, float],
        velocity: tuple[float, float, float],
        yaw_rad: float,
        peers: tuple[PlannerPeer, ...] | list[PlannerPeer],
        depth_observation,
    ) -> FlightCommand:
        timestamp = float(now)
        position = tuple(float(value) for value in global_position)
        altitude_throttle = _clamp((self.target_altitude_m - position[2]) / 0.5)
        distance = math.hypot(self.rally_target[0] - position[0], self.rally_target[1] - position[1])

        if self.phase == "escaping" and position[0] >= 4.0:
            self.phase = "rally"
        if distance <= 0.35:
            self.phase = "arrived"
        if self.phase == "arrived":
            command = FlightCommand(throttle=altitude_throttle, note="hybrid planner arrived")
            decision = PlannerDecision(
                command=command,
                mode="arrived",
                candidate_id="arrived-hold",
                minimum_static_clearance_m=None,
                minimum_peer_separation_m=None,
                generated_candidates=0,
                rejection_counts=self._empty_rejections(),
                planning_time_ms=0.0,
            )
            return self._record_decision(decision, now=timestamp)

        valid_depth = (
            depth_observation is not None
            and len(getattr(depth_observation, "ray_distances_m", ())) == 9
            and math.isfinite(float(getattr(depth_observation, "captured_at", math.nan)))
            and 0.0 <= timestamp - float(depth_observation.captured_at) <= 0.35
        )
        if not valid_depth:
            return self._hold(now=timestamp, throttle=altitude_throttle, mode="hold-stale-depth")

        self._update_local_bypass(
            timestamp,
            position,
            tuple(float(value) for value in velocity),
            depth_observation,
        )
        if self._bypass_stage == "braking":
            command = FlightCommand(throttle=altitude_throttle, note="bypass braking")
            decision = PlannerDecision(
                command=command,
                mode="bypass-braking",
                candidate_id="bypass-brake",
                minimum_static_clearance_m=None,
                minimum_peer_separation_m=None,
                generated_candidates=0,
                rejection_counts=self._empty_rejections(),
                planning_time_ms=0.0,
            )
            return self._record_decision(decision, now=timestamp)

        observation = self._learned_observation(
            global_position=position,
            yaw_rad=float(yaw_rad),
            depth_observation=depth_observation,
        )
        try:
            preference = self._policy_preference(observation)
        except (TypeError, ValueError):
            return self._hold(now=timestamp, throttle=altitude_throttle, mode="hold-invalid-policy")

        decision = self.planner.plan(
            now=timestamp,
            position=position,
            velocity=velocity,
            yaw_rad=yaw_rad,
            target=self.active_target,
            depth_observation=depth_observation,
            peers=tuple(peers),
            preferred_command=preference,
            corridor_center_y=(self.active_target[1] if self._bypass_target is not None else self.corridor_center_y),
            inside_forest=self.phase == "escaping",
        )
        command = replace(decision.command, throttle=altitude_throttle)
        decision = replace(decision, command=command)
        return self._record_decision(decision, now=timestamp)
