"""Local depth-memory and short-horizon safety planning primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass


def _finite_vector(values, length: int) -> bool:
    return len(values) == length and all(math.isfinite(float(value)) for value in values)


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _angle_difference(first: float, second: float) -> float:
    return _wrap_angle(first - second)


@dataclass(frozen=True)
class LocalPlannerConfig:
    horizontal_fov_rad: float = 1.274
    sector_count: int = 72
    sensor_range_m: float = 19.1
    obstacle_memory_s: float = 2.0
    horizon_s: float = 2.0
    integration_step_s: float = 0.10
    vehicle_radius_m: float = 0.25
    static_margin_m: float = 0.35
    peer_minimum_m: float = 0.90
    unknown_is_blocked: bool = True
    max_speed_mps: float = 0.8
    max_acceleration_mps2: float = 1.2
    max_yaw_rate_rad_s: float = math.radians(45.0)

    def __post_init__(self) -> None:
        positive = (
            self.horizontal_fov_rad,
            self.sensor_range_m,
            self.obstacle_memory_s,
            self.horizon_s,
            self.integration_step_s,
            self.vehicle_radius_m,
            self.static_margin_m,
            self.peer_minimum_m,
            self.max_speed_mps,
            self.max_acceleration_mps2,
            self.max_yaw_rate_rad_s,
        )
        if self.sector_count < 8 or not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("local planner limits must be finite and positive")
        if self.horizontal_fov_rad >= 2.0 * math.pi:
            raise ValueError("horizontal field of view must be below 2*pi")


@dataclass(frozen=True)
class WorldRay:
    origin_xy: tuple[float, float]
    bearing_rad: float
    free_distance_m: float
    obstacle_xy: tuple[float, float] | None
    observed_at: float
    sector: int


@dataclass(frozen=True)
class ObstacleSnapshot:
    rays: tuple[WorldRay, ...]
    obstacle_points: tuple[tuple[float, float], ...]
    sector_width_rad: float

    def is_observed_free(self, point_xy, *, margin_m: float) -> bool:
        if not _finite_vector(point_xy, 2) or not math.isfinite(float(margin_m)) or margin_m < 0.0:
            return False
        px, py = (float(value) for value in point_xy)
        for ray in self.rays:
            dx = px - ray.origin_xy[0]
            dy = py - ray.origin_xy[1]
            distance = math.hypot(dx, dy)
            if distance <= 1e-9:
                return True
            bearing = math.atan2(dy, dx)
            if abs(_angle_difference(bearing, ray.bearing_rad)) > self.sector_width_rad * 0.5 + 1e-9:
                continue
            along = dx * math.cos(ray.bearing_rad) + dy * math.sin(ray.bearing_rad)
            if along >= 0.0 and along + float(margin_m) <= ray.free_distance_m + 1e-9:
                return True
        return False


class RollingObstacleMemory:
    def __init__(self, config: LocalPlannerConfig | None = None) -> None:
        self.config = config or LocalPlannerConfig()
        self._rays: list[WorldRay] = []

    def _purge(self, now: float) -> None:
        cutoff = float(now) - self.config.obstacle_memory_s
        self._rays = [ray for ray in self._rays if ray.observed_at >= cutoff]

    def update(self, *, now, position, yaw_rad, depth_observation) -> None:
        timestamp = float(now)
        yaw = float(yaw_rad)
        if not math.isfinite(timestamp) or not math.isfinite(yaw) or not _finite_vector(position, 3):
            raise ValueError("pose and time must be finite")
        captured_at = float(depth_observation.captured_at)
        distances = tuple(float(value) for value in depth_observation.ray_distances_m)
        if not math.isfinite(captured_at) or captured_at > timestamp + 1e-6:
            raise ValueError("depth timestamp is invalid")
        if len(distances) != 9 or any(not math.isfinite(value) or value <= 0.0 for value in distances):
            raise ValueError("depth observation must contain nine positive finite rays")

        self._purge(timestamp)
        world_heading = _wrap_angle(math.pi / 2.0 - yaw)
        ray_width = self.config.horizontal_fov_rad / len(distances)
        sector_width = 2.0 * math.pi / self.config.sector_count
        origin = (float(position[0]), float(position[1]))
        for index, raw_distance in enumerate(distances):
            distance = min(raw_distance, self.config.sensor_range_m)
            offset = -self.config.horizontal_fov_rad / 2.0 + (index + 0.5) * ray_width
            bearing = _wrap_angle(world_heading + offset)
            sector = int(((bearing + math.pi) % (2.0 * math.pi)) / sector_width) % self.config.sector_count
            obstacle = None
            if raw_distance < self.config.sensor_range_m - 1e-6:
                obstacle = (
                    origin[0] + math.cos(bearing) * distance,
                    origin[1] + math.sin(bearing) * distance,
                )
            self._rays.append(WorldRay(origin, bearing, distance, obstacle, captured_at, sector))

    def snapshot(self, *, now) -> ObstacleSnapshot:
        timestamp = float(now)
        if not math.isfinite(timestamp):
            raise ValueError("snapshot time must be finite")
        self._purge(timestamp)
        rays = tuple(self._rays)
        obstacles = tuple(ray.obstacle_xy for ray in rays if ray.obstacle_xy is not None)
        return ObstacleSnapshot(rays, obstacles, 2.0 * math.pi / self.config.sector_count)
