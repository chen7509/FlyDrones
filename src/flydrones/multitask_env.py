"""Fast local-observation environment for compound swarm missions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from flydrones.multitask_contract import (
    LocalObservation,
    PolicyIntent,
    ScenarioManifest,
    Skill,
)


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

    def __init__(self, manifest: ScenarioManifest, max_steps: int = 400) -> None:
        super().__init__()
        if not isinstance(manifest, ScenarioManifest):
            raise TypeError("manifest must be a ScenarioManifest")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.manifest = manifest
        self.max_steps = max_steps
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
        self._velocities = np.zeros_like(self._positions)
        self._headings = np.zeros(manifest.fleet_size, dtype=np.float64)
        self._battery = np.full(manifest.fleet_size, 100.0, dtype=np.float64)
        self._previous_actions = np.zeros((manifest.fleet_size, 4), dtype=np.float32)
        self._coverage = np.zeros((manifest.fleet_size, 16), dtype=np.float32)
        self._last_skill = np.zeros(manifest.fleet_size, dtype=np.int64)
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

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        del options
        effective_seed = self.manifest.seed if seed is None else seed
        super().reset(seed=effective_seed)
        columns = max(1, math.ceil(math.sqrt(self.manifest.fleet_size)))
        for vehicle_id in range(self.manifest.fleet_size):
            row, column = divmod(vehicle_id, columns)
            self._positions[vehicle_id] = (
                -3.0 - 2.5 * row,
                (column - (columns - 1) / 2.0) * 2.5,
                8.0 + 0.25 * (vehicle_id % 3),
            )
        self._velocities.fill(0.0)
        self._headings.fill(0.0)
        self._battery[:] = self.np_random.uniform(72.0, 100.0, self.manifest.fleet_size)
        self._previous_actions.fill(0.0)
        self._coverage.fill(0.0)
        self._last_skill.fill(0)
        self._active = set(range(self.manifest.fleet_size))
        self._failed.clear()
        self._clearance_overrides.clear()
        self._steps = 0
        self._completed_evidence.clear()
        wind_scale = 0.8 if "wind" in self.manifest.disturbances else 0.05
        self._wind[:] = self.np_random.uniform(-wind_scale, wind_scale, 2)
        self._obstacles = self._sample_obstacles()
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
        angles = np.linspace(-math.pi, math.pi, 16, endpoint=False)
        position = self._positions[vehicle_id]
        distances = np.full(16, 12.0, dtype=np.float64)
        for obstacle in self._obstacles:
            delta = np.asarray((obstacle.x - position[0], obstacle.y - position[1]))
            distance = max(0.0, float(np.linalg.norm(delta)) - obstacle.radius - 0.25)
            angle = (math.atan2(delta[1], delta[0]) - self._headings[vehicle_id]) % (2 * math.pi)
            index = int(round(angle / (2 * math.pi) * 16)) % 16
            distances[index] = min(distances[index], distance)
        proximity = 1.0 - np.clip(distances / 12.0, 0.0, 1.0)
        if "sensor_noise" in self.manifest.disturbances:
            proximity += self.np_random.normal(0.0, 0.01, 16)
        return np.clip(proximity, 0.0, 1.0).astype(np.float32)

    @staticmethod
    def _relative(origin: np.ndarray, target: np.ndarray, scale: float) -> np.ndarray:
        return np.clip((target - origin) / scale, -1.0, 1.0).astype(np.float32)

    def _peer_summary(self, vehicle_id: int) -> np.ndarray:
        output = np.zeros(16, dtype=np.float32)
        position = self._positions[vehicle_id]
        peers = sorted(
            (
                (float(np.linalg.norm(self._positions[peer] - position)), peer)
                for peer in self._active
                if peer != vehicle_id
            ),
            key=lambda item: (item[0], item[1]),
        )[:4]
        for index, (distance, peer) in enumerate(peers):
            if "packet_loss" in self.manifest.disturbances and self.np_random.random() < 0.1:
                continue
            relative = np.clip((self._positions[peer] - position) / 20.0, -1.0, 1.0)
            output[index * 4:index * 4 + 3] = relative
            output[index * 4 + 3] = np.clip(distance / 20.0, 0.0, 1.0)
        return output

    def actor_observation(self, vehicle_id: int) -> np.ndarray:
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        position = self._positions[vehicle_id]
        visual = np.concatenate(
            (
                self._depth_features(vehicle_id),
                self._relative(position, self._target, 100.0),
                self._relative(position, self._exit, 100.0),
                self._relative(position, self._gate, 100.0),
                np.clip(self._wind / 4.0, -1.0, 1.0),
                np.asarray((math.sin(self._headings[vehicle_id]), math.cos(self._headings[vehicle_id]))),
                np.asarray((self._battery[vehicle_id] / 100.0, 1.0, 1.0)),
            )
        ).astype(np.float32)
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
        formation_error = min(1.0, abs(position[1]) / 20.0)
        task = np.concatenate((active_flags, np.asarray((self._steps / self.max_steps, formation_error))))
        validity = np.ones(6, dtype=np.float32)
        observation = LocalObservation.from_arrays(
            visual,
            flight,
            task,
            self._coverage[vehicle_id],
            self._peer_summary(vehicle_id),
            self._previous_actions[vehicle_id],
            validity,
            maximum_age_s=0.5,
            age_s=0.0,
        )
        return observation.actor_vector()

    def critic_observation(self) -> np.ndarray:
        active_mask = np.asarray(
            [float(vehicle_id in self._active) for vehicle_id in range(self.manifest.fleet_size)]
        )
        obstacle_truth = np.asarray(
            [(item.x, item.y, item.radius) for item in self._obstacles], dtype=np.float32
        ).reshape(-1)
        return np.concatenate(
            (
                self.actor_observation(min(self._active)),
                self._positions.astype(np.float32).reshape(-1),
                self._velocities.astype(np.float32).reshape(-1),
                self._battery.astype(np.float32) / 100.0,
                active_mask,
                self._target.astype(np.float32),
                self._gate.astype(np.float32),
                obstacle_truth,
                np.max(self._coverage, axis=0),
            )
        ).astype(np.float32)

    def _clearance(self, vehicle_id: int) -> float:
        if vehicle_id in self._clearance_overrides:
            return self._clearance_overrides[vehicle_id]
        position = self._positions[vehicle_id]
        boundary = min(
            position[axis] - self.bounds[axis, 0]
            for axis in range(3)
        )
        boundary = min(
            boundary,
            *(self.bounds[axis, 1] - position[axis] for axis in range(3)),
        ) - 0.25
        obstacle = min(
            (
                math.hypot(position[0] - item.x, position[1] - item.y) - item.radius - 0.25
                for item in self._obstacles
            ),
            default=math.inf,
        )
        peer = min(
            (
                float(np.linalg.norm(position - self._positions[other])) - 0.5
                for other in self._active
                if other != vehicle_id
            ),
            default=math.inf,
        )
        return float(min(boundary, obstacle, peer))

    def _update_coverage(self, vehicle_id: int) -> bool:
        position = self._positions[vehicle_id]
        x_index = int(np.clip((position[0] + 10.0) / 110.0 * 4, 0, 3))
        y_index = int(np.clip((position[1] + 60.0) / 120.0 * 4, 0, 3))
        index = y_index * 4 + x_index
        was_new = self._coverage[vehicle_id, index] == 0.0
        self._coverage[vehicle_id, index] = 1.0
        return bool(was_new)

    def step(self, actions: dict[int, PolicyIntent]):
        if not isinstance(actions, dict):
            raise TypeError("actions must map vehicle IDs to PolicyIntent")
        expected = self._active - self._failed
        if set(actions) != expected:
            raise ValueError("action vehicle IDs must exactly match active vehicles")
        for vehicle_id, intent in actions.items():
            if not isinstance(intent, PolicyIntent):
                raise TypeError("each action must be a PolicyIntent")
            checked = intent.checked()
            command = np.asarray(checked.motion, dtype=np.float64)
            self._velocities[vehicle_id] = command[:3] * self.maximum_speed_mps
            self._headings[vehicle_id] = (
                self._headings[vehicle_id] + command[3] * 1.5 * self.dt
            ) % (2 * math.pi)
            drift = np.asarray((self._wind[0], self._wind[1], 0.0))
            self._positions[vehicle_id] += (self._velocities[vehicle_id] + drift) * self.dt
            drain = 0.002 + 0.004 * float(np.linalg.norm(command[:3]))
            if "battery_variation" in self.manifest.disturbances:
                drain *= 1.0 + 0.2 * (vehicle_id % 3)
            self._battery[vehicle_id] -= drain
            self._previous_actions[vehicle_id] = command.astype(np.float32)
            self._last_skill[vehicle_id] = list(Skill).index(checked.skill)

        self._steps += 1
        target_angle = self._steps * self.dt * 0.25
        self._target[:] = (55.0 + 8.0 * math.cos(target_angle), 8.0 * math.sin(target_angle), 8.0)
        safety_failure: str | None = None
        rewards: dict[int, float] = {}
        reward_terms: dict[int, dict[str, float]] = {}
        for vehicle_id, intent in actions.items():
            clearance = self._clearance(vehicle_id)
            new_coverage = self._update_coverage(vehicle_id)
            exit_distance = float(np.linalg.norm(self._exit - self._positions[vehicle_id]))
            target_distance = float(np.linalg.norm(self._target - self._positions[vehicle_id]))
            terms = {
                "time": -0.01,
                "exit_progress": -0.002 * exit_distance,
                "target_tracking": -0.001 * abs(target_distance - 5.0),
                "new_coverage": 0.1 if new_coverage else 0.0,
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
            if exit_distance <= 1.0:
                self._completed_evidence.add(f"exit:{vehicle_id}")
            if target_distance <= 6.0:
                self._completed_evidence.add(f"track:{vehicle_id}")
            if float(np.mean(self._coverage[vehicle_id])) >= 0.95:
                self._completed_evidence.add(f"search:{vehicle_id}")
            rewards[vehicle_id] = float(sum(terms.values()))
            reward_terms[vehicle_id] = terms

        if self._steps == 50:
            for vehicle_id in self.manifest.failure_vehicle_ids:
                self._failed.add(vehicle_id)
                self._active.discard(vehicle_id)
        terminated = safety_failure is not None
        truncated = self._steps >= self.max_steps and not terminated
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
            "central_control_commands": 0,
        }
        return observations, rewards, terminated, truncated, info

    def _debug_set_clearance_m(self, vehicle_id: int, clearance_m: float) -> None:
        """Inject measured clearance for a deterministic safety test only."""
        if vehicle_id not in self._active:
            raise ValueError("vehicle is not active")
        if not math.isfinite(float(clearance_m)):
            raise ValueError("clearance_m must be finite")
        self._clearance_overrides[vehicle_id] = float(clearance_m)
