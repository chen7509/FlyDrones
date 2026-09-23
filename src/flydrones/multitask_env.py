"""Fast local-observation environment for compound swarm missions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from flydrones.multitask_contract import (
    SUPPORTED_DISTURBANCES,
    LocalObservation,
    PolicyIntent,
    SafetySnapshot,
    ScenarioManifest,
    Skill,
)
from flydrones.multitask_metrics import EpisodeTelemetry


@dataclass(frozen=True)
class _Obstacle:
    x: float
    y: float
    radius: float


class MultiTaskEnv(gym.Env):
    """Multi-agent kinematic environment with deployment-safe observations.

    The actor API exposes one 90-value vector per vehicle. Simulator truth is
    available only through :meth:`critic_observation` for offline CTDE.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        manifest: ScenarioManifest,
        max_steps: int = 400,
        *,
        maximum_observation_age_s: float = 0.5,
    ) -> None:
        super().__init__()
        if not isinstance(manifest, ScenarioManifest):
            raise TypeError("manifest must be a ScenarioManifest")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ValueError("max_steps must be positive")
        unsupported = set(manifest.disturbances) - set(SUPPORTED_DISTURBANCES)
        if unsupported:
            raise ValueError(f"unsupported disturbance: {sorted(unsupported)[0]}")
        if (
            not math.isfinite(float(maximum_observation_age_s))
            or maximum_observation_age_s <= 0.0
        ):
            raise ValueError("maximum_observation_age_s must be positive")
        self.manifest = manifest
        self.max_steps = max_steps
        self.maximum_observation_age_s = float(maximum_observation_age_s)
        self.dt = 0.1
        self.maximum_speed_mps = 4.0
        self.bounds = np.asarray(((-10.0, 100.0), (-60.0, 60.0), (0.0, 30.0)))
        self.single_observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(LocalObservation.dimension,), dtype=np.float32
        )
        self.observation_space = spaces.Dict(
            {
                str(vehicle_id): self.single_observation_space
                for vehicle_id in range(manifest.fleet_size)
            }
        )
        self.action_space = spaces.Dict(
            {
                str(vehicle_id): spaces.Box(-1.0, 1.0, shape=(4,), dtype=np.float32)
                for vehicle_id in range(manifest.fleet_size)
            }
        )
        self._positions = np.zeros((manifest.fleet_size, 3), dtype=np.float64)
        self._estimated_positions = np.zeros_like(self._positions)
        self._localization_drift = np.zeros_like(self._positions)
        self._velocities = np.zeros_like(self._positions)
        self._headings = np.zeros(manifest.fleet_size, dtype=np.float64)
        self._battery = np.full(manifest.fleet_size, 100.0, dtype=np.float64)
        self._previous_actions = np.zeros((manifest.fleet_size, 4), dtype=np.float32)
        self._coverage = np.zeros((manifest.fleet_size, 16), dtype=np.float32)
        self._global_coverage_visits = np.zeros(16, dtype=np.int64)
        self._last_skill = np.zeros(manifest.fleet_size, dtype=np.int64)
        self._last_visual_features = np.zeros((manifest.fleet_size, 32), dtype=np.float32)
        self._peer_summaries = np.zeros((manifest.fleet_size, 16), dtype=np.float32)
        self._validity = np.ones((manifest.fleet_size, 6), dtype=np.float32)
        self._observation_ages = np.zeros(manifest.fleet_size, dtype=np.float64)
        self._forced_frame_drops = np.zeros(manifest.fleet_size, dtype=np.int64)
        self._frame_drop_phases = np.zeros(manifest.fleet_size, dtype=np.int64)
        self._packet_loss_phases = np.zeros(manifest.fleet_size, dtype=np.int64)
        self._battery_drain_multipliers = np.ones(manifest.fleet_size, dtype=np.float64)
        self._active: set[int] = set(range(manifest.fleet_size))
        self._failed: set[int] = set()
        self._obstacles: tuple[_Obstacle, ...] = ()
        self._clearance_overrides: dict[int, float] = {}
        self._wind = np.zeros(2, dtype=np.float64)
        self._target = np.asarray((55.0, 0.0, 8.0), dtype=np.float64)
        self._exit = np.asarray((92.0, 0.0, 10.0), dtype=np.float64)
        self._gate = np.asarray((48.0, 0.0, 9.0), dtype=np.float64)
        self._steps = 0
        self._completed_evidence: set[str] = set()
        self._tracking_squared_error_sum = 0.0
        self._tracking_samples = 0
        self._tracking_lost_steps = 0
        self._tracking_acquired: set[int] = set()
        self._duplicate_coverage_visits = 0
        self._coverage_visits = 0
        self._formation_squared_error_sum = 0.0
        self._formation_samples = 0
        self._formation_acquired: set[int] = set()
        self._gate_crossings = 0
        self._gate_contacts = 0
        self._safety_failures: list[str] = []
        self._safety_overrides = 0
        self._central_control_commands = 0
        self._disturbance_injections = {
            name: 0 for name in manifest.disturbances
        }
        self._disturbance_minimums = {
            name: math.inf for name in manifest.disturbances
        }
        self._disturbance_maximums = {
            name: -math.inf for name in manifest.disturbances
        }

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        del options
        effective_seed = self.manifest.seed if seed is None else seed
        super().reset(seed=effective_seed)
        columns = max(1, math.ceil(self.manifest.fleet_size / 4))
        for vehicle_id in range(self.manifest.fleet_size):
            row, column = divmod(vehicle_id, columns)
            self._positions[vehicle_id] = (
                -2.0 - 2.5 * row,
                (column - (columns - 1) / 2.0) * 2.5,
                8.0 + 0.25 * (vehicle_id % 3),
            )
        self._velocities.fill(0.0)
        self._estimated_positions[:] = self._positions
        self._localization_drift.fill(0.0)
        self._headings.fill(0.0)
        self._battery[:] = self.np_random.uniform(72.0, 100.0, self.manifest.fleet_size)
        self._previous_actions.fill(0.0)
        self._coverage.fill(0.0)
        self._global_coverage_visits.fill(0)
        self._last_skill.fill(0)
        self._last_visual_features.fill(0.0)
        self._peer_summaries.fill(0.0)
        self._validity.fill(1.0)
        self._observation_ages.fill(0.0)
        self._forced_frame_drops.fill(0)
        self._frame_drop_phases[:] = self.np_random.integers(
            0, 5, self.manifest.fleet_size
        )
        self._packet_loss_phases[:] = self.np_random.integers(
            0, 4, self.manifest.fleet_size
        )
        if "battery_variation" in self.manifest.disturbances:
            self._battery_drain_multipliers[:] = self.np_random.uniform(
                0.8, 1.25, self.manifest.fleet_size
            )
        else:
            self._battery_drain_multipliers.fill(1.0)
        self._active = set(range(self.manifest.fleet_size))
        self._failed.clear()
        self._clearance_overrides.clear()
        self._steps = 0
        self._completed_evidence.clear()
        self._tracking_squared_error_sum = 0.0
        self._tracking_samples = 0
        self._tracking_lost_steps = 0
        self._tracking_acquired.clear()
        self._duplicate_coverage_visits = 0
        self._coverage_visits = 0
        self._formation_squared_error_sum = 0.0
        self._formation_samples = 0
        self._formation_acquired.clear()
        self._gate_crossings = 0
        self._gate_contacts = 0
        self._safety_failures.clear()
        self._safety_overrides = 0
        self._central_control_commands = 0
        for name in self.manifest.disturbances:
            self._disturbance_injections[name] = 0
            self._disturbance_minimums[name] = math.inf
            self._disturbance_maximums[name] = -math.inf
        if "wind" in self.manifest.disturbances:
            self._wind[:] = self.np_random.uniform(-0.8, 0.8, 2)
        else:
            self._wind.fill(0.0)
        self._obstacles = self._sample_obstacles()
        self._refresh_local_measurements(initial=True)
        observations = {
            vehicle_id: self.actor_observation(vehicle_id)
            for vehicle_id in sorted(self._active)
        }
        info = {
            "manifest_digest": self.manifest.digest,
            "seed": int(effective_seed),
            "active_vehicle_ids": tuple(sorted(self._active)),
            "completed_evidence": (),
        }
        return observations, info

    def _sample_obstacles(self) -> tuple[_Obstacle, ...]:
        count = {"forest": 24, "building": 12, "mixed": 20}[self.manifest.world.value]
        obstacles: list[_Obstacle] = []
        for _ in range(count):
            for _attempt in range(100):
                obstacle = _Obstacle(
                    float(self.np_random.uniform(8.0, 85.0)),
                    float(self.np_random.uniform(-35.0, 35.0)),
                    float(self.np_random.uniform(0.5, 1.8)),
                )
                if math.hypot(obstacle.x - self._exit[0], obstacle.y - self._exit[1]) < 4.0:
                    continue
                if any(
                    math.hypot(obstacle.x - other.x, obstacle.y - other.y)
                    < obstacle.radius + other.radius + 0.5
                    for other in obstacles
                ):
                    continue
                obstacles.append(obstacle)
                break
        return tuple(obstacles)

    def _depth_features(self, vehicle_id: int) -> np.ndarray:
        position = self._positions[vehicle_id]
        distances = np.full(16, 12.0, dtype=np.float64)
        for obstacle in self._obstacles:
            delta = np.asarray((obstacle.x - position[0], obstacle.y - position[1]))
            distance = max(0.0, float(np.linalg.norm(delta)) - obstacle.radius - 0.25)
            angle = (math.atan2(delta[1], delta[0]) - self._headings[vehicle_id]) % (2 * math.pi)
            index = int(round(angle / (2 * math.pi) * 16)) % 16
            distances[index] = min(distances[index], distance)
        proximity = 1.0 - np.clip(distances / 12.0, 0.0, 1.0)
        return np.clip(proximity, 0.0, 1.0).astype(np.float32)

    @staticmethod
    def _relative(origin: np.ndarray, target: np.ndarray, scale: float) -> np.ndarray:
        return np.clip((target - origin) / scale, -1.0, 1.0).astype(np.float32)

    def _peer_summary(self, vehicle_id: int) -> np.ndarray:
        output = np.zeros(16, dtype=np.float32)
        position = self._estimated_positions[vehicle_id]
        peers = sorted(
            (
                (float(np.linalg.norm(self._estimated_positions[peer] - position)), peer)
                for peer in self._active
                if peer != vehicle_id
            ),
            key=lambda item: (item[0], item[1]),
        )[:4]
        for index, (distance, peer) in enumerate(peers):
            relative = np.clip(
                (self._estimated_positions[peer] - position) / 20.0, -1.0, 1.0
            )
            output[index * 4:index * 4 + 3] = relative
            output[index * 4 + 3] = np.clip(distance / 20.0, 0.0, 1.0)
        return output

    def _record_disturbance(self, name: str, magnitude: float) -> None:
        value = abs(float(magnitude))
        self._disturbance_injections[name] += 1
        self._disturbance_minimums[name] = min(
            self._disturbance_minimums[name], value
        )
        self._disturbance_maximums[name] = max(
            self._disturbance_maximums[name], value
        )

    def _visual_features(self, vehicle_id: int) -> np.ndarray:
        position = self._estimated_positions[vehicle_id]
        target_angle = self._steps * self.dt * 0.25
        target_velocity = np.asarray(
            (-2.0 * math.sin(target_angle), 2.0 * math.cos(target_angle))
        )
        return np.concatenate(
            (
                self._depth_features(vehicle_id),
                self._relative(position, self._target, 20.0),
                self._relative(position, self._exit, 20.0),
                self._relative(position, self._gate, 20.0),
                np.clip(self._wind / 4.0, -1.0, 1.0),
                np.asarray(
                    (
                        math.sin(self._headings[vehicle_id]),
                        math.cos(self._headings[vehicle_id]),
                    )
                ),
                np.asarray((self._battery[vehicle_id] / 100.0,)),
                np.clip(
                    target_velocity / self.maximum_speed_mps,
                    -1.0,
                    1.0,
                ),
            )
        ).astype(np.float32)

    def _refresh_local_measurements(self, *, initial: bool = False) -> None:
        for vehicle_id in sorted(self._active):
            self._validity[vehicle_id].fill(1.0)
            if "localization_drift" in self.manifest.disturbances:
                delta = self.np_random.normal(0.0, 0.015, 3)
                self._localization_drift[vehicle_id] = np.clip(
                    self._localization_drift[vehicle_id] + delta, -1.0, 1.0
                )
                self._record_disturbance(
                    "localization_drift",
                    float(np.linalg.norm(self._localization_drift[vehicle_id])),
                )
            else:
                self._localization_drift[vehicle_id].fill(0.0)
            self._estimated_positions[vehicle_id] = (
                self._positions[vehicle_id] + self._localization_drift[vehicle_id]
            )

            dropped = False
            if not initial and "frame_drop" in self.manifest.disturbances:
                dropped = (
                    self._forced_frame_drops[vehicle_id] > 0
                    or (self._steps + self._frame_drop_phases[vehicle_id]) % 5 == 0
                )
                if self._forced_frame_drops[vehicle_id] > 0:
                    self._forced_frame_drops[vehicle_id] -= 1
            if dropped:
                self._observation_ages[vehicle_id] += self.dt
                self._record_disturbance(
                    "frame_drop", self._observation_ages[vehicle_id]
                )
            else:
                visual = self._visual_features(vehicle_id)
                if "sensor_noise" in self.manifest.disturbances:
                    noise = self.np_random.normal(0.0, 0.01, 16).astype(np.float32)
                    visual[:16] = np.clip(visual[:16] + noise, 0.0, 1.0)
                    self._record_disturbance(
                        "sensor_noise", float(np.max(np.abs(noise)))
                    )
                self._last_visual_features[vehicle_id] = visual
                self._observation_ages[vehicle_id] = 0.0

            self._peer_summaries[vehicle_id] = self._peer_summary(vehicle_id)
            if (
                not initial
                and "packet_loss" in self.manifest.disturbances
                and (self._steps + self._packet_loss_phases[vehicle_id]) % 4 == 0
            ):
                self._peer_summaries[vehicle_id].fill(0.0)
                self._validity[vehicle_id, 4] = 0.0
                self._record_disturbance("packet_loss", 1.0)

    def local_observation(self, vehicle_id: int) -> LocalObservation:
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        position = self._estimated_positions[vehicle_id]
        flight = np.concatenate(
            (
                np.clip(position / np.asarray((100.0, 60.0, 30.0)), -1.0, 1.0),
                np.clip(self._velocities[vehicle_id] / self.maximum_speed_mps, -1.0, 1.0),
                np.asarray((self._battery[vehicle_id] / 100.0, self._headings[vehicle_id] / math.pi)),
            )
        ).astype(np.float32)
        active_flags = np.asarray(
            [float(skill in self.manifest.active_skills) for skill in Skill], dtype=np.float32
        )
        role = (
            0.0
            if self.manifest.fleet_size == 1
            else -1.0 + 2.0 * vehicle_id / (self.manifest.fleet_size - 1)
        )
        task = np.concatenate(
            (active_flags, np.asarray((self._steps / self.max_steps, role)))
        )
        return LocalObservation.from_arrays(
            self._last_visual_features[vehicle_id],
            flight,
            task,
            self._coverage[vehicle_id],
            self._peer_summaries[vehicle_id],
            self._previous_actions[vehicle_id],
            self._validity[vehicle_id],
            maximum_age_s=self.maximum_observation_age_s,
            age_s=float(self._observation_ages[vehicle_id]),
        )

    def actor_observation(self, vehicle_id: int) -> np.ndarray:
        return self.local_observation(vehicle_id).actor_vector()

    def critic_observation(self) -> np.ndarray:
        active_mask = np.asarray(
            [float(vehicle_id in self._active) for vehicle_id in range(self.manifest.fleet_size)]
        )
        obstacle_truth = np.asarray(
            [(item.x, item.y, item.radius) for item in self._obstacles], dtype=np.float32
        ).reshape(-1)
        padded_obstacles = np.zeros(24 * 3, dtype=np.float32)
        padded_obstacles[: obstacle_truth.size] = obstacle_truth
        return np.concatenate(
            (
                self._positions.astype(np.float32).reshape(-1),
                self._velocities.astype(np.float32).reshape(-1),
                self._battery.astype(np.float32) / 100.0,
                active_mask,
                self._target.astype(np.float32),
                self._gate.astype(np.float32),
                self._exit.astype(np.float32),
                padded_obstacles,
                np.max(self._coverage, axis=0),
                self._wind.astype(np.float32),
                np.asarray((self._steps / self.max_steps,), dtype=np.float32),
            )
        ).astype(np.float32)

    def _clearance_and_recovery(
        self, vehicle_id: int
    ) -> tuple[float, tuple[float, float, float, float]]:
        if vehicle_id in self._clearance_overrides:
            return self._clearance_overrides[vehicle_id], (0.0, 0.0, 0.0, 0.0)
        position = self._positions[vehicle_id]
        candidates: list[tuple[float, np.ndarray]] = []
        for axis in range(3):
            lower_recovery = np.zeros(3, dtype=np.float64)
            lower_recovery[axis] = 1.0
            candidates.append(
                (float(position[axis] - self.bounds[axis, 0] - 0.25), lower_recovery)
            )
            upper_recovery = np.zeros(3, dtype=np.float64)
            upper_recovery[axis] = -1.0
            candidates.append(
                (float(self.bounds[axis, 1] - position[axis] - 0.25), upper_recovery)
            )
        for item in self._obstacles:
            delta = np.asarray((position[0] - item.x, position[1] - item.y, 0.0))
            distance = float(np.linalg.norm(delta[:2]))
            if distance <= 1e-9:
                delta[:] = (-1.0, 0.0, 0.0)
            else:
                delta /= distance
            candidates.append((distance - item.radius - 0.25, delta))
        for other in self._active:
            if other == vehicle_id:
                continue
            delta = position - self._positions[other]
            distance = float(np.linalg.norm(delta))
            if distance <= 1e-9:
                delta = np.asarray((-0.25, 0.0, 0.0))
            else:
                delta *= 0.25 / distance
            candidates.append((distance - 0.5, delta))
        clearance, recovery = min(candidates, key=lambda item: item[0])
        motion = tuple(float(value) for value in recovery) + (0.0,)
        return float(clearance), motion  # type: ignore[return-value]

    def _clearance(self, vehicle_id: int) -> float:
        return self._clearance_and_recovery(vehicle_id)[0]

    def _update_coverage(self, vehicle_id: int) -> tuple[bool, int]:
        position = self._positions[vehicle_id]
        x_index = int(np.clip((position[0] + 10.0) / 110.0 * 4, 0, 3))
        y_index = int(np.clip((position[1] + 60.0) / 120.0 * 4, 0, 3))
        index = y_index * 4 + x_index
        was_new = self._coverage[vehicle_id, index] == 0.0
        self._coverage[vehicle_id, index] = 1.0
        return bool(was_new), index

    def step(self, actions: dict[int, PolicyIntent]):
        if not isinstance(actions, dict):
            raise TypeError("actions must map vehicle IDs to PolicyIntent")
        expected = self._active - self._failed
        if set(actions) != expected:
            raise ValueError("action vehicle IDs must exactly match active vehicles")
        previous_positions = self._positions.copy()
        checked_actions: dict[int, PolicyIntent] = {}
        for vehicle_id, intent in actions.items():
            if not isinstance(intent, PolicyIntent):
                raise TypeError("each action must be a PolicyIntent")
            checked = intent.checked()
            checked_actions[vehicle_id] = checked
            command = np.asarray(checked.motion, dtype=np.float64)
            self._velocities[vehicle_id] = command[:3] * self.maximum_speed_mps
            self._headings[vehicle_id] = (
                self._headings[vehicle_id] + command[3] * 1.5 * self.dt
            ) % (2 * math.pi)
            drift = np.asarray((self._wind[0], self._wind[1], 0.0))
            self._positions[vehicle_id] += (self._velocities[vehicle_id] + drift) * self.dt
            if "wind" in self.manifest.disturbances:
                self._record_disturbance("wind", float(np.linalg.norm(drift)))
            drain = 0.002 + 0.004 * float(np.linalg.norm(command[:3]))
            if "battery_variation" in self.manifest.disturbances:
                multiplier = self._battery_drain_multipliers[vehicle_id]
                drain *= multiplier
                self._record_disturbance("battery_variation", abs(multiplier - 1.0))
            self._battery[vehicle_id] -= drain
            self._previous_actions[vehicle_id] = command.astype(np.float32)
            self._last_skill[vehicle_id] = list(Skill).index(checked.skill)
        actions = checked_actions

        self._steps += 1
        target_angle = self._steps * self.dt * 0.25
        self._target[:] = (55.0 + 8.0 * math.cos(target_angle), 8.0 * math.sin(target_angle), 8.0)
        safety_failure: str | None = None
        rewards: dict[int, float] = {}
        reward_terms: dict[int, dict[str, float]] = {}
        for vehicle_id, intent in actions.items():
            clearance = self._clearance(vehicle_id)
            new_coverage, coverage_index = self._update_coverage(vehicle_id)
            exit_distance = float(np.linalg.norm(self._exit - self._positions[vehicle_id]))
            previous_exit_distance = float(
                np.linalg.norm(self._exit - previous_positions[vehicle_id])
            )
            target_distance = float(np.linalg.norm(self._target - self._positions[vehicle_id]))
            gate_distance = float(np.linalg.norm(self._gate - self._positions[vehicle_id]))
            previous_gate_distance = float(
                np.linalg.norm(self._gate - previous_positions[vehicle_id])
            )
            home = np.asarray((-3.0, 0.0, 8.0), dtype=np.float64)
            home_distance = float(np.linalg.norm(home - self._positions[vehicle_id]))
            previous_home_distance = float(
                np.linalg.norm(home - previous_positions[vehicle_id])
            )
            active_skill = intent.skill if intent.skill in self.manifest.active_skills else None
            if active_skill is Skill.TRACK_TARGET:
                if target_distance <= 6.0:
                    self._tracking_acquired.add(vehicle_id)
                if vehicle_id in self._tracking_acquired:
                    tracking_error = target_distance - 5.0
                    self._tracking_squared_error_sum += tracking_error * tracking_error
                    self._tracking_samples += 1
                    self._tracking_lost_steps += int(target_distance > 12.0)
            if new_coverage:
                already_covered = self._global_coverage_visits[coverage_index] > 0
                self._global_coverage_visits[coverage_index] += 1
                if active_skill is Skill.SEARCH_COVER:
                    self._coverage_visits += 1
                    if self._steps > 1 and already_covered:
                        self._duplicate_coverage_visits += 1
            if active_skill is Skill.FORMATION_RALLY:
                if abs(self._positions[vehicle_id, 1]) <= 0.4:
                    self._formation_acquired.add(vehicle_id)
                if vehicle_id in self._formation_acquired:
                    formation_error_value = float(self._positions[vehicle_id, 1])
                    self._formation_squared_error_sum += (
                        formation_error_value * formation_error_value
                    )
                    self._formation_samples += 1
            terms = {
                "time": -0.01,
                "exit_progress": (
                    previous_exit_distance - exit_distance
                    if active_skill is Skill.NAVIGATE_EXIT
                    else 0.0
                ),
                "target_tracking": (
                    -0.01 * abs(target_distance - 5.0)
                    if active_skill is Skill.TRACK_TARGET
                    else 0.0
                ),
                "new_coverage": (
                    0.1 if active_skill is Skill.SEARCH_COVER and new_coverage else 0.0
                ),
                "formation_error": (
                    -0.01 * abs(self._positions[vehicle_id, 1])
                    if active_skill is Skill.FORMATION_RALLY
                    else 0.0
                ),
                "gate_progress": (
                    previous_gate_distance - gate_distance
                    if active_skill is Skill.GATE_COURSE
                    else 0.0
                ),
                "return_progress": (
                    previous_home_distance - home_distance
                    if active_skill is Skill.YIELD_RETURN_LAND
                    else 0.0
                ),
                "energy": -0.005 * float(np.linalg.norm(intent.motion[:3])),
                "safety": 0.0,
            }
            if clearance <= 0.0:
                terms["safety"] = -100.0
                safety_failure = "collision"
            elif not all(
                self.bounds[axis, 0] <= self._positions[vehicle_id, axis] <= self.bounds[axis, 1]
                for axis in range(3)
            ):
                terms["safety"] = -100.0
                safety_failure = "geofence"
            elif self._battery[vehicle_id] < 30.0 and intent.skill is not Skill.YIELD_RETURN_LAND:
                terms["safety"] = -100.0
                safety_failure = "return-reserve"
            if active_skill is Skill.NAVIGATE_EXIT and exit_distance <= 1.0:
                self._completed_evidence.add(f"exit:{vehicle_id}")
            if active_skill is Skill.TRACK_TARGET and target_distance <= 6.0:
                self._completed_evidence.add(f"track:{vehicle_id}")
            if (
                active_skill is Skill.SEARCH_COVER
                and float(np.mean(self._coverage[vehicle_id])) >= 0.95
            ):
                self._completed_evidence.add(f"search:{vehicle_id}")
            if (
                active_skill is Skill.SEARCH_COVER
                and float(np.mean(self._global_coverage_visits > 0)) >= 0.95
            ):
                self._completed_evidence.add("search:fleet")
            crossed_gate = (
                previous_positions[vehicle_id, 0] < self._gate[0]
                <= self._positions[vehicle_id, 0]
            )
            aligned_gate = (
                abs(self._positions[vehicle_id, 1] - self._gate[1]) <= 2.0
                and abs(self._positions[vehicle_id, 2] - self._gate[2]) <= 2.0
            )
            within_gate_frame = (
                abs(self._positions[vehicle_id, 1] - self._gate[1]) <= 3.0
                and abs(self._positions[vehicle_id, 2] - self._gate[2]) <= 3.0
            )
            if (
                active_skill is Skill.GATE_COURSE
                and crossed_gate
                and aligned_gate
            ):
                self._completed_evidence.add(f"gate:{vehicle_id}")
                self._gate_crossings += 1
            elif (
                active_skill is Skill.GATE_COURSE
                and crossed_gate
                and within_gate_frame
            ):
                self._gate_contacts += 1
            if (
                active_skill is Skill.FORMATION_RALLY
                and abs(self._positions[vehicle_id, 1]) <= 0.4
            ):
                self._completed_evidence.add(f"formation:{vehicle_id}")
            if (
                active_skill is Skill.YIELD_RETURN_LAND
                and home_distance <= 1.0
            ):
                self._completed_evidence.add(f"return:{vehicle_id}")
            rewards[vehicle_id] = float(sum(terms.values()))
            reward_terms[vehicle_id] = terms

        if self._steps == 50:
            for vehicle_id in self.manifest.failure_vehicle_ids:
                self._failed.add(vehicle_id)
                self._active.discard(vehicle_id)
        if safety_failure is not None:
            self._safety_failures.append(safety_failure)
        terminated = safety_failure is not None
        truncated = self._steps >= self.max_steps and not terminated
        self._refresh_local_measurements()
        observations = {
            vehicle_id: self.actor_observation(vehicle_id)
            for vehicle_id in sorted(self._active)
        }
        info: dict[str, Any] = {
            "manifest_digest": self.manifest.digest,
            "reward_terms": reward_terms,
            "safety_failure": safety_failure,
            "completed_evidence": tuple(sorted(self._completed_evidence)),
            "active_vehicle_ids": tuple(sorted(self._active)),
            "failed_vehicle_ids": tuple(sorted(self._failed)),
            "central_control_commands": self._central_control_commands,
        }
        return observations, rewards, terminated, truncated, info

    def true_positions(self) -> np.ndarray:
        values = self._positions.copy()
        values.flags.writeable = False
        return values

    def safety_snapshot(self, vehicle_id: int) -> SafetySnapshot:
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        clearance, recovery_motion = self._clearance_and_recovery(vehicle_id)
        return SafetySnapshot(
            battery_pct=float(self._battery[vehicle_id]),
            localization_healthy=bool(self._validity[vehicle_id, 1]),
            sensors_healthy=bool(
                bool(self._validity[vehicle_id, 0])
                and self._observation_ages[vehicle_id]
                <= self.maximum_observation_age_s
            ),
            minimum_clearance_m=clearance,
            emergency_active=False,
            recovery_motion=recovery_motion,
        )

    def record_safety_override(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason:
            raise ValueError("safety override reason must be a non-empty string")
        self._safety_overrides += 1

    def telemetry(self) -> EpisodeTelemetry:
        minimums = {
            name: (
                0.0 if not math.isfinite(value) else value
            )
            for name, value in self._disturbance_minimums.items()
        }
        maximums = {
            name: (
                0.0 if not math.isfinite(value) else value
            )
            for name, value in self._disturbance_maximums.items()
        }
        return EpisodeTelemetry(
            tracking_squared_error_sum=self._tracking_squared_error_sum,
            tracking_samples=self._tracking_samples,
            tracking_lost_steps=self._tracking_lost_steps,
            union_coverage_cells=int(np.count_nonzero(self._global_coverage_visits)),
            duplicate_coverage_visits=self._duplicate_coverage_visits,
            coverage_visits=self._coverage_visits,
            formation_squared_error_sum=self._formation_squared_error_sum,
            formation_samples=self._formation_samples,
            gate_crossings=self._gate_crossings,
            gate_contacts=self._gate_contacts,
            safety_failures=tuple(self._safety_failures),
            safety_overrides=self._safety_overrides,
            completed_evidence=tuple(sorted(self._completed_evidence)),
            central_control_commands=self._central_control_commands,
            disturbance_injections=self._disturbance_injections,
            disturbance_minimums=minimums,
            disturbance_maximums=maximums,
        )

    def _debug_set_clearance_m(self, vehicle_id: int, clearance_m: float) -> None:
        """Inject measured clearance for a deterministic safety test only."""
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        if not math.isfinite(float(clearance_m)):
            raise ValueError("clearance_m must be finite")
        self._clearance_overrides[vehicle_id] = float(clearance_m)

    def _debug_force_frame_drops(self, vehicle_id: int, *, count: int) -> None:
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("count must be a positive integer")
        if "frame_drop" not in self.manifest.disturbances:
            raise ValueError("frame_drop disturbance is not active")
        self._observation_ages[vehicle_id] += count * self.dt
        for _ in range(count):
            self._record_disturbance(
                "frame_drop", self._observation_ages[vehicle_id]
            )
