"""Local depth-memory and short-horizon safety planning primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import perf_counter

from .motor.command import FlightCommand


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
    _SAMPLES_PER_SECTOR_AND_KIND = 6

    def __init__(self, config: LocalPlannerConfig | None = None) -> None:
        self.config = config or LocalPlannerConfig()
        self._rays: dict[tuple[int, bool], list[WorldRay]] = {}

    def _purge(self, now: float) -> None:
        cutoff = float(now) - self.config.obstacle_memory_s
        retained: dict[tuple[int, bool], list[WorldRay]] = {}
        for key, rays in self._rays.items():
            live = [ray for ray in rays if ray.observed_at >= cutoff]
            if live:
                retained[key] = live
        self._rays = retained

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
            # Image columns run from visual left to right. In the mathematical
            # world frame visual left is the positive (counter-clockwise) side.
            offset = self.config.horizontal_fov_rad / 2.0 - (index + 0.5) * ray_width
            bearing = _wrap_angle(world_heading + offset)
            sector = int(((bearing + math.pi) % (2.0 * math.pi)) / sector_width) % self.config.sector_count
            obstacle = None
            if raw_distance < self.config.sensor_range_m - 1e-6:
                obstacle = (
                    origin[0] + math.cos(bearing) * distance,
                    origin[1] + math.sin(bearing) * distance,
                )
            key = (sector, obstacle is not None)
            ray = WorldRay(
                origin,
                bearing,
                distance,
                obstacle,
                captured_at,
                sector,
            )
            self._rays.setdefault(key, []).append(ray)
            self._rays[key] = self._rays[key][-self._SAMPLES_PER_SECTOR_AND_KIND :]

    def snapshot(self, *, now) -> ObstacleSnapshot:
        timestamp = float(now)
        if not math.isfinite(timestamp):
            raise ValueError("snapshot time must be finite")
        self._purge(timestamp)
        rays = tuple(
            ray
            for key in sorted(self._rays)
            for ray in self._rays[key]
        )
        obstacles = tuple(ray.obstacle_xy for ray in rays if ray.obstacle_xy is not None)
        return ObstacleSnapshot(rays, obstacles, 2.0 * math.pi / self.config.sector_count)


@dataclass(frozen=True)
class PlannerPeer:
    """A neighbour state expressed in the same world frame as the vehicle."""

    sender_id: int
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    age_s: float


@dataclass(frozen=True)
class TrajectoryCandidate:
    """A deterministic short-horizon body command and its world-frame samples."""

    candidate_id: str
    forward_mps: float
    lateral_mps: float
    yaw_rate_rad_s: float
    samples: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class PlannerDecision:
    command: FlightCommand
    mode: str
    candidate_id: str
    minimum_static_clearance_m: float | None
    minimum_peer_separation_m: float | None
    generated_candidates: int
    rejection_counts: dict[str, int]
    planning_time_ms: float


class HybridLocalPlanner:
    """Select a safe command from a fixed, reproducible trajectory lattice.

    The learned policy supplies only a preference.  Unknown space, remembered
    obstacles, predicted peer motion, and the forest corridor are hard gates.
    """

    _FORWARD_SPEEDS = (-0.18, 0.12, 0.25, 0.45, 0.65)
    _LATERAL_SPEEDS = (-0.35, 0.0, 0.35)
    _YAW_RATES = (-0.65, 0.0, 0.65)

    def __init__(self, config: LocalPlannerConfig | None = None) -> None:
        self.config = config or LocalPlannerConfig()
        self.memory = RollingObstacleMemory(self.config)
        self._escape_yaw_sign: int | None = None
        self._pose_history: list[tuple[float, tuple[float, float, float], float]] = []
        self._last_depth_timestamp = -math.inf

    def observe(self, *, now, position, yaw_rad, depth_observation) -> None:
        timestamp = float(now)
        numeric_position = tuple(float(value) for value in position)
        yaw = float(yaw_rad)
        if (
            not math.isfinite(timestamp)
            or not _finite_vector(numeric_position, 3)
            or not math.isfinite(yaw)
        ):
            raise ValueError("pose and time must be finite")
        self._pose_history.append((timestamp, numeric_position, yaw))
        cutoff = timestamp - self.config.obstacle_memory_s - 0.5
        self._pose_history = [sample for sample in self._pose_history if sample[0] >= cutoff]

        captured_at = float(depth_observation.captured_at)
        if not math.isfinite(captured_at) or captured_at > timestamp + 1e-6:
            raise ValueError("depth timestamp is invalid")
        if captured_at <= self._last_depth_timestamp + 1e-9:
            return
        self._last_depth_timestamp = captured_at

        capture_position, capture_yaw = numeric_position, yaw
        for index in range(1, len(self._pose_history)):
            before = self._pose_history[index - 1]
            after = self._pose_history[index]
            if before[0] <= captured_at <= after[0] and after[0] > before[0]:
                fraction = (captured_at - before[0]) / (after[0] - before[0])
                capture_position = tuple(
                    before[1][axis] + fraction * (after[1][axis] - before[1][axis])
                    for axis in range(3)
                )
                capture_yaw = _wrap_angle(
                    before[2] + fraction * _angle_difference(after[2], before[2])
                )
                break
        self.memory.update(
            now=timestamp,
            position=capture_position,
            yaw_rad=capture_yaw,
            depth_observation=depth_observation,
        )

    @staticmethod
    def _valid_peer(peer: PlannerPeer) -> bool:
        try:
            return (
                isinstance(peer.sender_id, int)
                and _finite_vector(peer.position, 3)
                and _finite_vector(peer.velocity, 3)
                and math.isfinite(float(peer.age_s))
                and float(peer.age_s) >= 0.0
            )
        except (TypeError, ValueError):
            return False

    def _make_candidate(
        self,
        *,
        candidate_id: str,
        forward_mps: float,
        lateral_mps: float,
        yaw_rate_rad_s: float,
        position: tuple[float, float, float],
        velocity: tuple[float, float, float],
        yaw_rad: float,
    ) -> TrajectoryCandidate:
        dt = self.config.integration_step_s
        steps = max(1, int(round(self.config.horizon_s / dt)))
        x, y, z = position
        vx, vy = velocity[0], velocity[1]
        world_heading = _wrap_angle(math.pi / 2.0 - yaw_rad)
        actual_yaw_rate = max(
            -self.config.max_yaw_rate_rad_s,
            min(self.config.max_yaw_rate_rad_s, yaw_rate_rad_s),
        )
        samples: list[tuple[float, float, float]] = []
        max_delta = self.config.max_acceleration_mps2 * dt

        for _ in range(steps):
            desired_vx = forward_mps * math.cos(world_heading) + lateral_mps * math.sin(world_heading)
            desired_vy = forward_mps * math.sin(world_heading) - lateral_mps * math.cos(world_heading)
            delta_x = desired_vx - vx
            delta_y = desired_vy - vy
            delta_norm = math.hypot(delta_x, delta_y)
            if delta_norm > max_delta:
                scale = max_delta / delta_norm
                delta_x *= scale
                delta_y *= scale
            vx += delta_x
            vy += delta_y
            x += vx * dt
            y += vy * dt
            samples.append((x, y, z))
            # PX4 positive yaw is clockwise; mathematical world heading is CCW.
            world_heading = _wrap_angle(world_heading - actual_yaw_rate * dt)

        return TrajectoryCandidate(
            candidate_id,
            forward_mps,
            lateral_mps,
            actual_yaw_rate,
            tuple(samples),
        )

    def _candidates(self, *, position, velocity, yaw_rad) -> tuple[TrajectoryCandidate, ...]:
        candidates: list[TrajectoryCandidate] = []
        for forward in self._FORWARD_SPEEDS:
            for lateral in self._LATERAL_SPEEDS:
                for yaw_rate in self._YAW_RATES:
                    candidate_id = f"f{forward:+.2f}-l{lateral:+.2f}-y{yaw_rate:+.2f}"
                    candidates.append(
                        self._make_candidate(
                            candidate_id=candidate_id,
                            forward_mps=forward,
                            lateral_mps=lateral,
                            yaw_rate_rad_s=yaw_rate,
                            position=position,
                            velocity=velocity,
                            yaw_rad=yaw_rad,
                        )
                    )
        # Rotation-only options let a vehicle acquire new depth evidence without
        # translating into unknown space.
        for yaw_rate in (-0.65, 0.65):
            candidates.append(
                self._make_candidate(
                    candidate_id=f"rotate-y{yaw_rate:+.2f}",
                    forward_mps=0.0,
                    lateral_mps=0.0,
                    yaw_rate_rad_s=yaw_rate,
                    position=position,
                    velocity=velocity,
                    yaw_rad=yaw_rad,
                )
            )
        return tuple(candidates)

    def _hold_decision(
        self,
        *,
        started_at: float,
        mode: str,
        candidate_count: int,
        rejection_counts: dict[str, int],
        static_clearance: float | None = None,
        peer_clearance: float | None = None,
    ) -> PlannerDecision:
        return PlannerDecision(
            command=FlightCommand.hover(mode),
            mode=mode,
            candidate_id="hold",
            minimum_static_clearance_m=static_clearance,
            minimum_peer_separation_m=peer_clearance,
            generated_candidates=candidate_count,
            rejection_counts=rejection_counts,
            planning_time_ms=(perf_counter() - started_at) * 1000.0,
        )

    def plan(
        self,
        *,
        now,
        position,
        velocity,
        yaw_rad,
        target,
        depth_observation,
        peers,
        preferred_command,
        corridor_center_y,
        inside_forest,
        corridor_half_width_m=None,
    ) -> PlannerDecision:
        started_at = perf_counter()
        rejection_counts = {"unknown": 0, "static": 0, "peer": 0, "corridor": 0, "invalid": 0}

        if (
            not math.isfinite(float(now))
            or not _finite_vector(position, 3)
            or not _finite_vector(velocity, 3)
            or not _finite_vector(target, 2)
            or not math.isfinite(float(yaw_rad))
            or not math.isfinite(float(corridor_center_y))
            or (
                corridor_half_width_m is not None
                and (
                    not math.isfinite(float(corridor_half_width_m))
                    or float(corridor_half_width_m) <= 0.0
                )
            )
        ):
            rejection_counts["invalid"] += 1
            return self._hold_decision(
                started_at=started_at,
                mode="hold-invalid-input",
                candidate_count=0,
                rejection_counts=rejection_counts,
            )

        peer_tuple = tuple(peers)
        if any(not self._valid_peer(peer) for peer in peer_tuple):
            rejection_counts["invalid"] += 1
            return self._hold_decision(
                started_at=started_at,
                mode="hold-invalid-peer",
                candidate_count=0,
                rejection_counts=rejection_counts,
            )

        numeric_position = tuple(float(value) for value in position)
        numeric_velocity = tuple(float(value) for value in velocity)
        numeric_target = tuple(float(value) for value in target)
        timestamp = float(now)
        self.observe(
            now=timestamp,
            position=numeric_position,
            yaw_rad=float(yaw_rad),
            depth_observation=depth_observation,
        )
        obstacle_snapshot = self.memory.snapshot(now=timestamp)
        candidates = self._candidates(
            position=numeric_position,
            velocity=numeric_velocity,
            yaw_rad=float(yaw_rad),
        )
        static_requirement = self.config.vehicle_radius_m + self.config.static_margin_m
        start_target_distance = math.hypot(
            numeric_target[0] - numeric_position[0],
            numeric_target[1] - numeric_position[1],
        )
        start_corridor_error = abs(numeric_position[1] - float(corridor_center_y))
        preferred = preferred_command.clipped() if isinstance(preferred_command, FlightCommand) else FlightCommand()
        safe: list[tuple[tuple[float, ...], int, TrajectoryCandidate, float | None, float | None]] = []

        for lattice_index, candidate in enumerate(candidates):
            # A zero-translation command still moves while the vehicle bleeds
            # existing velocity. Gate the simulated path, not only the command.
            moving = any(
                math.hypot(
                    sample[0] - numeric_position[0],
                    sample[1] - numeric_position[1],
                )
                > 1e-9
                for sample in candidate.samples
            )
            minimum_static = None
            if obstacle_snapshot.obstacle_points:
                minimum_static_squared = min(
                    (sample[0] - obstacle[0]) ** 2 + (sample[1] - obstacle[1]) ** 2
                    for sample in candidate.samples
                    for obstacle in obstacle_snapshot.obstacle_points
                )
                minimum_static = math.sqrt(minimum_static_squared)
                if moving and minimum_static_squared + 1e-9 < static_requirement ** 2:
                    rejection_counts["static"] += 1
                    continue

            if moving and self.config.unknown_is_blocked:
                if any(
                    not obstacle_snapshot.is_observed_free(sample[:2], margin_m=static_requirement)
                    for sample in candidate.samples
                ):
                    rejection_counts["unknown"] += 1
                    continue

            minimum_peer = None
            minimum_peer_squared = math.inf
            peer_rejected = False
            for peer in peer_tuple:
                required_separation = self.config.peer_minimum_m + min(0.30, peer.age_s * 0.25)
                for sample_index, sample in enumerate(candidate.samples, start=1):
                    future_s = sample_index * self.config.integration_step_s
                    peer_x = peer.position[0] + peer.velocity[0] * (peer.age_s + future_s)
                    peer_y = peer.position[1] + peer.velocity[1] * (peer.age_s + future_s)
                    peer_z = peer.position[2] + peer.velocity[2] * (peer.age_s + future_s)
                    separation_squared = (
                        (sample[0] - peer_x) ** 2
                        + (sample[1] - peer_y) ** 2
                        + (sample[2] - peer_z) ** 2
                    )
                    minimum_peer_squared = min(minimum_peer_squared, separation_squared)
                    if separation_squared + 1e-9 < required_separation ** 2:
                        peer_rejected = True
                        break
                if peer_rejected:
                    break
            if peer_rejected:
                rejection_counts["peer"] += 1
                continue
            if math.isfinite(minimum_peer_squared):
                minimum_peer = math.sqrt(minimum_peer_squared)

            final = candidate.samples[-1]
            final_corridor_error = abs(final[1] - float(corridor_center_y))
            if (
                moving
                and bool(inside_forest)
                and (
                    (
                        corridor_half_width_m is not None
                        and final_corridor_error > float(corridor_half_width_m) + 1e-9
                    )
                    or (
                        start_corridor_error > 0.8
                        and final_corridor_error > start_corridor_error + 1e-9
                    )
                )
            ):
                rejection_counts["corridor"] += 1
                continue

            final_target_distance = math.hypot(numeric_target[0] - final[0], numeric_target[1] - final[1])
            progress = start_target_distance - final_target_distance
            static_score = minimum_static if minimum_static is not None else self.config.sensor_range_m
            peer_score = minimum_peer if minimum_peer is not None else self.config.sensor_range_m
            command_delta = (
                abs(candidate.forward_mps / self.config.max_speed_mps - preferred.forward)
                + abs(candidate.lateral_mps / self.config.max_speed_mps - preferred.lateral)
                + abs(candidate.yaw_rate_rad_s / self.config.max_yaw_rate_rad_s - preferred.yaw)
            )
            preference_agreement = -command_delta
            score = (
                progress,
                min(static_score, 3.0),
                min(peer_score, 3.0),
                -final_corridor_error,
                preference_agreement,
                -float(lattice_index),
            )
            safe.append((score, lattice_index, candidate, minimum_static, minimum_peer))

        safe_moving = [entry for entry in safe if abs(entry[2].forward_mps) > 1e-9 or abs(entry[2].lateral_mps) > 1e-9]
        safe_rotations = [entry for entry in safe if abs(entry[2].yaw_rate_rad_s) > 1e-9]
        world_heading = _wrap_angle(math.pi / 2.0 - float(yaw_rad))
        target_heading = math.atan2(
            numeric_target[1] - numeric_position[1],
            numeric_target[0] - numeric_position[0],
        )
        target_error = _angle_difference(target_heading, world_heading)
        imminent_peer = any(
            math.sqrt(
                (numeric_position[0] - (peer.position[0] + peer.velocity[0] * (peer.age_s + future_s))) ** 2
                + (numeric_position[1] - (peer.position[1] + peer.velocity[1] * (peer.age_s + future_s))) ** 2
                + (numeric_position[2] - (peer.position[2] + peer.velocity[2] * (peer.age_s + future_s))) ** 2
            )
            < 1.80
            for peer in peer_tuple
            for future_s in (0.0, self.config.horizon_s * 0.5, self.config.horizon_s)
        )
        if safe_moving:
            best_moving = max(safe_moving, key=lambda entry: entry[0])
            if best_moving[0][0] < -0.05 and safe_rotations and not imminent_peer:
                target_yaw_sign = 1 if target_error < 0.0 else -1
                target_rotations = [
                    entry
                    for entry in safe_rotations
                    if entry[2].yaw_rate_rad_s * target_yaw_sign > 0.0
                ]
                selected = max(target_rotations or safe_rotations, key=lambda entry: entry[0])
            else:
                selected = best_moving
            self._escape_yaw_sign = None
        else:
            # If every depth ray ends inside the static envelope, turning cannot
            # reveal a safe translational route and the conservative action is hold.
            all_depth_blocked = bool(obstacle_snapshot.rays) and all(
                ray.free_distance_m <= static_requirement + 1e-9 for ray in obstacle_snapshot.rays[-9:]
            )
            if all_depth_blocked or not safe_rotations:
                self._escape_yaw_sign = None
                hold_static = None
                if obstacle_snapshot.obstacle_points:
                    hold_static = min(
                        math.hypot(numeric_position[0] - point[0], numeric_position[1] - point[1])
                        for point in obstacle_snapshot.obstacle_points
                    )
                return self._hold_decision(
                    started_at=started_at,
                    mode="hold-no-safe-trajectory",
                    candidate_count=len(candidates),
                    rejection_counts=rejection_counts,
                    static_clearance=hold_static,
                )
            reorientation_threshold = (
                0.10
                if corridor_half_width_m is not None
                else self.config.horizontal_fov_rad / 3.0
            )
            reorient_to_target = not imminent_peer and abs(target_error) > reorientation_threshold
            if reorient_to_target:
                self._escape_yaw_sign = None
                target_yaw_sign = 1 if target_error < 0.0 else -1
                target_rotations = [
                    entry
                    for entry in safe_rotations
                    if entry[2].yaw_rate_rad_s * target_yaw_sign > 0.0
                ]
                selected = max(target_rotations or safe_rotations, key=lambda entry: entry[0])
            else:
                use_persistent_turn = not peer_tuple and (
                    self._escape_yaw_sign is not None or abs(preferred.yaw) > 0.20
                )
                if not use_persistent_turn:
                    self._escape_yaw_sign = None
                    selected = max(safe_rotations, key=lambda entry: entry[0])
                else:
                    if self._escape_yaw_sign is None:
                        selected = max(safe_rotations, key=lambda entry: entry[0])
                        self._escape_yaw_sign = 1 if selected[2].yaw_rate_rad_s > 0.0 else -1
                    persistent_rotations = [
                        entry
                        for entry in safe_rotations
                        if entry[2].yaw_rate_rad_s * self._escape_yaw_sign > 0.0
                    ]
                    selected = max(persistent_rotations or safe_rotations, key=lambda entry: entry[0])

        _, _, candidate, minimum_static, minimum_peer = selected
        command = FlightCommand(
            yaw=candidate.yaw_rate_rad_s / self.config.max_yaw_rate_rad_s,
            forward=candidate.forward_mps / self.config.max_speed_mps,
            lateral=candidate.lateral_mps / self.config.max_speed_mps,
            note="hybrid-local-planner",
        ).clipped()
        return PlannerDecision(
            command=command,
            mode="trajectory",
            candidate_id=candidate.candidate_id,
            minimum_static_clearance_m=minimum_static,
            minimum_peer_separation_m=minimum_peer,
            generated_candidates=len(candidates),
            rejection_counts=rejection_counts,
            planning_time_ms=(perf_counter() - started_at) * 1000.0,
        )
