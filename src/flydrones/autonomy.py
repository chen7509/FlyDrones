"""Fast local-observation environment for learning autonomous forest tasks."""

from __future__ import annotations

import math
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
from gymnasium import spaces


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class CircleObstacle:
    x: float
    y: float
    radius: float


class AutonomousForestEnv(gym.Env):
    """Learn point-to-point flight from depth rays and a relative goal only.

    Obstacle coordinates are retained by the environment for physics and reward
    calculation. They never appear in the policy observation.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        obstacle_count: tuple[int, int] = (2, 6),
        wind_mps: float = 0.04,
        depth_noise: float = 0.01,
        frame_drop_probability: float = 0.0,
        max_steps: int = 220,
        dt: float = 0.1,
        safety_reflex: bool = True,
    ) -> None:
        super().__init__()
        if obstacle_count[0] < 0 or obstacle_count[1] < obstacle_count[0]:
            raise ValueError("invalid obstacle count range")
        self.obstacle_count = obstacle_count
        self.wind_mps = float(wind_mps)
        self.depth_noise = float(depth_noise)
        self.frame_drop_probability = float(frame_drop_probability)
        self.max_steps = int(max_steps)
        self.dt = float(dt)
        self.safety_reflex = bool(safety_reflex)
        self.bounds = (-1.0, 8.0, -4.0, 4.0)
        self.vehicle_radius = 0.16
        self.sensor_range_m = 4.0
        self.ray_angles = np.linspace(-math.pi / 2.0, math.pi / 2.0, 9)
        self.max_speed_mps = 1.6
        self.max_yaw_rate = 1.8

        self.action_space = spaces.Box(-1.0, 1.0, shape=(2,), dtype=np.float32)
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(16,), dtype=np.float32)

        self.position = np.zeros(2, dtype=np.float64)
        self.goal = np.zeros(2, dtype=np.float64)
        self.heading = 0.0
        self.speed = 0.0
        self.yaw_rate = 0.0
        self.wind = np.zeros(2, dtype=np.float64)
        self.obstacles: list[CircleObstacle] = []
        self.previous_action = np.zeros(2, dtype=np.float32)
        self._last_depth = np.ones(9, dtype=np.float32)
        self.steps = 0
        self.episode_return = 0.0
        self.minimum_clearance = math.inf
        self.safety_interventions = 0

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        options = options or {}
        self.position[:] = (0.0, float(self.np_random.uniform(-1.0, 1.0)))
        self.goal[:] = (7.0, float(self.np_random.uniform(-2.2, 2.2)))
        self.heading = float(self.np_random.uniform(-0.18, 0.18))
        self.speed = 0.0
        self.yaw_rate = 0.0
        wind_angle = float(self.np_random.uniform(-math.pi, math.pi))
        wind_speed = float(self.np_random.uniform(0.0, self.wind_mps))
        self.wind[:] = (math.cos(wind_angle) * wind_speed, math.sin(wind_angle) * wind_speed)
        self.previous_action[:] = 0.0
        self.steps = 0
        self.episode_return = 0.0
        self.minimum_clearance = math.inf
        self.safety_interventions = 0
        self.obstacles = self._sample_obstacles()
        self._last_depth = self._depth_proximity(apply_sensor_effects=False)
        observation = self.local_observation()
        return observation, {"task": "navigate_to_goal", "obstacles": len(self.obstacles)}

    def _sample_obstacles(self) -> list[CircleObstacle]:
        count = int(self.np_random.integers(self.obstacle_count[0], self.obstacle_count[1] + 1))
        obstacles: list[CircleObstacle] = []
        for _ in range(count):
            for _attempt in range(100):
                candidate = CircleObstacle(
                    x=float(self.np_random.uniform(1.25, 5.9)),
                    y=float(self.np_random.uniform(-3.15, 3.15)),
                    radius=float(self.np_random.uniform(0.25, 0.48)),
                )
                center = np.asarray((candidate.x, candidate.y))
                if np.linalg.norm(center - self.position) <= candidate.radius + 1.0:
                    continue
                if np.linalg.norm(center - self.goal) <= candidate.radius + 1.0:
                    continue
                if any(math.hypot(candidate.x - item.x, candidate.y - item.y) < candidate.radius + item.radius + 0.25 for item in obstacles):
                    continue
                obstacles.append(candidate)
                break
        return obstacles

    def _ray_distances(self) -> np.ndarray:
        xmin, xmax, ymin, ymax = self.bounds
        distances = np.full(len(self.ray_angles), self.sensor_range_m, dtype=np.float64)
        for index, offset in enumerate(self.ray_angles):
            angle = self.heading + float(offset)
            direction = np.asarray((math.cos(angle), math.sin(angle)))
            candidates: list[float] = []
            if direction[0] > 1e-9:
                candidates.append((xmax - self.position[0]) / direction[0])
            elif direction[0] < -1e-9:
                candidates.append((xmin - self.position[0]) / direction[0])
            if direction[1] > 1e-9:
                candidates.append((ymax - self.position[1]) / direction[1])
            elif direction[1] < -1e-9:
                candidates.append((ymin - self.position[1]) / direction[1])
            for obstacle in self.obstacles:
                relative = np.asarray((obstacle.x, obstacle.y)) - self.position
                projection = float(np.dot(relative, direction))
                if projection <= 0.0:
                    continue
                inflated = obstacle.radius + self.vehicle_radius
                perpendicular_sq = float(np.dot(relative, relative) - projection * projection)
                if perpendicular_sq > inflated * inflated:
                    continue
                hit = projection - math.sqrt(max(0.0, inflated * inflated - perpendicular_sq))
                if hit > 0.0:
                    candidates.append(hit)
            positive = [value for value in candidates if value > 0.0]
            if positive:
                distances[index] = min(self.sensor_range_m, min(positive))
        return distances

    def _depth_proximity(self, *, apply_sensor_effects: bool = True) -> np.ndarray:
        proximity = 1.0 - self._ray_distances() / self.sensor_range_m
        if apply_sensor_effects and self.np_random.random() < self.frame_drop_probability:
            return self._last_depth.copy()
        if apply_sensor_effects and self.depth_noise > 0.0:
            proximity += self.np_random.normal(0.0, self.depth_noise, size=proximity.shape)
        proximity = np.clip(proximity, 0.0, 1.0).astype(np.float32)
        self._last_depth = proximity
        return proximity

    def local_observation(self) -> np.ndarray:
        relative_goal = self.goal - self.position
        distance = float(np.linalg.norm(relative_goal))
        bearing = _wrap(math.atan2(relative_goal[1], relative_goal[0]) - self.heading)
        values = np.concatenate((
            np.asarray([
                np.clip(distance / 10.0, 0.0, 1.0),
                math.sin(bearing),
                math.cos(bearing),
                np.clip(self.speed / self.max_speed_mps, 0.0, 1.0),
                np.clip(self.yaw_rate / self.max_yaw_rate, -1.0, 1.0),
            ], dtype=np.float32),
            self._depth_proximity(),
            self.previous_action.astype(np.float32),
        ))
        return np.clip(values, -1.0, 1.0).astype(np.float32)

    def _clearance(self, position: np.ndarray) -> float:
        xmin, xmax, ymin, ymax = self.bounds
        boundary = min(position[0] - xmin, xmax - position[0], position[1] - ymin, ymax - position[1]) - self.vehicle_radius
        obstacle = min(
            (math.hypot(position[0] - item.x, position[1] - item.y) - item.radius - self.vehicle_radius for item in self.obstacles),
            default=math.inf,
        )
        return float(min(boundary, obstacle))

    def step(self, action):
        command = np.clip(np.asarray(action, dtype=np.float32), -1.0, 1.0)
        previous_distance = float(np.linalg.norm(self.goal - self.position))
        target_speed = float((command[0] + 1.0) * 0.5 * self.max_speed_mps)
        target_yaw_rate = float(command[1] * self.max_yaw_rate)
        if self.safety_reflex:
            depth_distance = (1.0 - self._last_depth.astype(float)) * self.sensor_range_m
            nearest_index = int(np.argmin(depth_distance))
            nearest_distance = float(depth_distance[nearest_index])
            if nearest_distance < 1.05:
                safe_speed = float(np.clip((nearest_distance - 0.28) / 0.77, 0.0, 1.0) * 1.15)
                target_speed = min(target_speed, safe_speed)
                obstacle_angle = float(self.ray_angles[nearest_index])
                if abs(obstacle_angle) < 0.08:
                    left_space = float(np.mean(depth_distance[5:]))
                    right_space = float(np.mean(depth_distance[:4]))
                    turn_direction = 1.0 if left_space > right_space else -1.0
                else:
                    turn_direction = -1.0 if obstacle_angle > 0.0 else 1.0
                urgency = float(np.clip((1.05 - nearest_distance) / 0.75, 0.0, 1.0))
                reflex_yaw_rate = turn_direction * self.max_yaw_rate * (0.45 + 0.55 * urgency)
                if abs(reflex_yaw_rate) > abs(target_yaw_rate) or reflex_yaw_rate * target_yaw_rate < 0.0:
                    target_yaw_rate = reflex_yaw_rate
                self.safety_interventions += 1
        speed_blend = 1.0 - math.exp(-self.dt / 0.32)
        yaw_blend = 1.0 - math.exp(-self.dt / 0.24)
        self.speed += (target_speed - self.speed) * speed_blend
        self.yaw_rate += (target_yaw_rate - self.yaw_rate) * yaw_blend
        self.heading = _wrap(self.heading + self.yaw_rate * self.dt)
        forward = np.asarray((math.cos(self.heading), math.sin(self.heading)))
        noise = self.np_random.normal(0.0, self.wind_mps * 0.08, size=2)
        self.position += (forward * self.speed + self.wind + noise) * self.dt
        self.steps += 1

        distance = float(np.linalg.norm(self.goal - self.position))
        clearance = self._clearance(self.position)
        self.minimum_clearance = min(self.minimum_clearance, clearance)
        collision = clearance <= 0.0
        reached_goal = distance <= 0.35
        truncated = self.steps >= self.max_steps and not (collision or reached_goal)
        terminated = collision or reached_goal

        progress = previous_distance - distance
        bearing = _wrap(math.atan2(self.goal[1] - self.position[1], self.goal[0] - self.position[0]) - self.heading)
        action_delta = float(np.sum(np.square(command - self.previous_action)))
        clearance_intrusion = max(0.0, 0.90 - clearance)
        near_obstacle_speed = (self.speed / self.max_speed_mps) ** 2 if clearance < 0.80 else 0.0
        reward = (
            5.0 * progress
            + 0.025 * math.cos(bearing)
            - 0.01
            - (0.025 if progress < 0.002 else 0.0)
            - 4.5 * clearance_intrusion * clearance_intrusion
            - 0.06 * near_obstacle_speed
            - 0.025 * action_delta
        )
        if collision:
            reward -= 25.0
        if reached_goal:
            reward += 20.0
        self.previous_action = command.copy()
        self.episode_return += reward
        observation = self.local_observation()
        info = {
            "task": "navigate_to_goal",
            "reached_goal": reached_goal,
            "collision": collision,
            "distance_to_goal_m": distance,
            "minimum_clearance_m": self.minimum_clearance,
            "episode_return": self.episode_return,
            "steps": self.steps,
            "safety_interventions": self.safety_interventions,
        }
        return observation, float(reward), bool(terminated), bool(truncated), info
