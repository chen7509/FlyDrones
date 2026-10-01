"""Decentralized 3-D stress simulator for high-speed swarm encounters.

The controller deliberately receives only delayed/noisy local tracks, its own
goal and short-range obstacle detections.  Global state is retained by the
simulator solely to integrate physics and score the run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else np.zeros(3, dtype=float)


def _limit(vector: np.ndarray, magnitude: float) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector * (magnitude / norm) if norm > magnitude else vector


class EncounterType(str, Enum):
    CLEAR = "clear"
    HEAD_ON = "head_on"
    CROSSING = "crossing"
    OVERTAKING = "overtaking"
    VERTICAL = "vertical"


def time_to_closest_approach(
    relative_position: np.ndarray,
    own_velocity: np.ndarray,
    other_velocity: np.ndarray,
    horizon_s: float,
) -> tuple[float, float]:
    """Return bounded time and distance at closest approach from local tracks."""
    closing_velocity = np.asarray(own_velocity, dtype=float) - np.asarray(other_velocity, dtype=float)
    speed_squared = float(np.dot(closing_velocity, closing_velocity))
    if speed_squared < 1e-9:
        return 0.0, float(np.linalg.norm(relative_position))
    time_s = float(np.dot(relative_position, closing_velocity) / speed_squared)
    time_s = max(0.0, min(float(horizon_s), time_s))
    miss = np.asarray(relative_position, dtype=float) - closing_velocity * time_s
    return time_s, float(np.linalg.norm(miss))


def classify_encounter(
    relative_position: np.ndarray,
    own_velocity: np.ndarray,
    other_velocity: np.ndarray,
) -> EncounterType:
    """Classify an encounter using only relative position and velocity."""
    relative_position = np.asarray(relative_position, dtype=float)
    own_velocity = np.asarray(own_velocity, dtype=float)
    other_velocity = np.asarray(other_velocity, dtype=float)
    horizontal = float(np.linalg.norm(relative_position[:2]))
    if abs(float(relative_position[2])) > max(3.0, 0.55 * horizontal) and abs(own_velocity[2] - other_velocity[2]) > 1.0:
        return EncounterType.VERTICAL

    own_speed = float(np.linalg.norm(own_velocity))
    other_speed = float(np.linalg.norm(other_velocity))
    if own_speed < 1e-6 or other_speed < 1e-6:
        return EncounterType.CLEAR
    direction_cosine = float(np.dot(own_velocity, other_velocity) / (own_speed * other_speed))
    ahead = float(np.dot(_unit(own_velocity), _unit(relative_position)))
    if direction_cosine < -0.65 and ahead > 0.35:
        return EncounterType.HEAD_ON
    if direction_cosine > 0.75 and ahead > 0.35 and own_speed > other_speed + 0.5:
        return EncounterType.OVERTAKING
    time_s, miss = time_to_closest_approach(relative_position, own_velocity, other_velocity, 6.0)
    if 0.0 < time_s < 6.0 and miss < 8.0:
        return EncounterType.CROSSING
    return EncounterType.CLEAR


@dataclass
class DroneState:
    vehicle_id: int
    position: np.ndarray
    velocity: np.ndarray
    goal: np.ndarray
    radius_m: float = 0.45
    arrived: bool = False


@dataclass(frozen=True)
class BoxObstacle:
    name: str
    center: tuple[float, float, float]
    size: tuple[float, float, float]


@dataclass
class MovingObstacle:
    name: str
    position: np.ndarray
    velocity: np.ndarray
    radius_m: float


@dataclass
class CrossingScenario:
    drones: list[DroneState]
    static_obstacles: list[BoxObstacle]
    dynamic_obstacles: list[MovingObstacle]
    seed: int = 1
    duration_s: float = 24.0
    dt_s: float = 0.05
    target_speed_mps: float = 13.0
    max_speed_mps: float = 17.0
    max_acceleration_mps2: float = 8.0
    sensor_range_m: float = 48.0
    collision_horizon_s: float = 5.0
    protected_separation_m: float = 2.0
    planning_separation_m: float = 3.0
    goal_tolerance_m: float = 2.2
    perception_latency_s: float = 0.14
    frame_drop_probability: float = 0.10
    position_noise_m: float = 0.12
    velocity_noise_mps: float = 0.18
    steady_wind_mps: tuple[float, float, float] = (2.2, -1.1, 0.0)
    wind_gust_mps: float = 3.5
    central_avoidance_commands: int = 0


@dataclass
class HighSpeedTrialResult:
    trace: list[dict]
    summary: dict
    scenario: CrossingScenario = field(repr=False)


@dataclass(frozen=True)
class NavigationCommand:
    velocity: np.ndarray
    action: tuple[float, float]
    source: str


class GoalNavigationPolicy:
    """Non-learning reference policy used by the original stress test."""

    source = "goal-vector-rules"

    def __init__(self) -> None:
        self.predict_calls = 0

    def preferred_velocity(
        self,
        own: DroneState,
        observation: np.ndarray,
        scenario: CrossingScenario,
    ) -> NavigationCommand:
        del observation
        self.predict_calls += 1
        distance = float(np.linalg.norm(own.goal - own.position))
        speed = min(scenario.target_speed_mps, max(3.0, distance * 0.7))
        return NavigationCommand(_unit(own.goal - own.position) * speed, (1.0, 0.0), self.source)


class PpoForestNavigationPolicy:
    """Adapter that reuses the trained local-observation forest PPO policy."""

    source = "ppo-forest-v1"

    def __init__(self, model_path: str) -> None:
        from stable_baselines3 import PPO

        self.model = PPO.load(model_path)
        self.predict_calls = 0

    def preferred_velocity(
        self,
        own: DroneState,
        observation: np.ndarray,
        scenario: CrossingScenario,
    ) -> NavigationCommand:
        action, _state = self.model.predict(observation, deterministic=True)
        action = np.clip(np.asarray(action, dtype=float), -1.0, 1.0)
        self.predict_calls += 1
        horizontal_velocity = own.velocity[:2]
        if np.linalg.norm(horizontal_velocity) > 0.25:
            heading = math.atan2(float(horizontal_velocity[1]), float(horizontal_velocity[0]))
        else:
            goal_delta = own.goal - own.position
            heading = math.atan2(float(goal_delta[1]), float(goal_delta[0]))
        speed = float((action[0] + 1.0) * 0.5 * scenario.target_speed_mps)
        target_heading = heading + float(action[1]) * 0.65
        vertical_speed = float(np.clip((own.goal[2] - own.position[2]) * 0.7, -4.0, 4.0))
        horizontal_speed = math.sqrt(max(0.0, speed * speed - vertical_speed * vertical_speed))
        velocity = np.array([
            math.cos(target_heading) * horizontal_speed,
            math.sin(target_heading) * horizontal_speed,
            vertical_speed,
        ])
        return NavigationCommand(velocity, (float(action[0]), float(action[1])), self.source)


def _ray_aabb_distance_2d(origin: np.ndarray, direction: np.ndarray, obstacle: BoxObstacle, margin: float) -> float | None:
    center = np.asarray(obstacle.center[:2], dtype=float)
    half = np.asarray(obstacle.size[:2], dtype=float) / 2.0 + margin
    low, high = center - half, center + half
    near, far = -math.inf, math.inf
    for axis in range(2):
        if abs(float(direction[axis])) < 1e-9:
            if origin[axis] < low[axis] or origin[axis] > high[axis]:
                return None
            continue
        first = (low[axis] - origin[axis]) / direction[axis]
        second = (high[axis] - origin[axis]) / direction[axis]
        near = max(near, min(first, second))
        far = min(far, max(first, second))
    if far < max(near, 0.0):
        return None
    return max(0.0, float(near))


def _ray_circle_distance(origin: np.ndarray, direction: np.ndarray, center: np.ndarray, radius: float) -> float | None:
    relative = center[:2] - origin
    projection = float(np.dot(relative, direction))
    if projection <= 0.0:
        return None
    perpendicular_squared = float(np.dot(relative, relative) - projection * projection)
    if perpendicular_squared > radius * radius:
        return None
    return projection - math.sqrt(max(0.0, radius * radius - perpendicular_squared))


def build_local_navigation_observation(
    own: DroneState,
    *,
    neighbor_positions: list[np.ndarray],
    dynamic_obstacles: list[MovingObstacle],
    static_obstacles: list[BoxObstacle],
    scenario: CrossingScenario,
    previous_action: np.ndarray,
) -> np.ndarray:
    """Emulate the 16-value local observation used during forest PPO training."""
    horizontal_velocity = own.velocity[:2]
    if np.linalg.norm(horizontal_velocity) > 0.25:
        heading = math.atan2(float(horizontal_velocity[1]), float(horizontal_velocity[0]))
    else:
        goal_delta = own.goal - own.position
        heading = math.atan2(float(goal_delta[1]), float(goal_delta[0]))
    goal_delta = own.goal - own.position
    goal_distance = float(np.linalg.norm(goal_delta))
    goal_bearing = (math.atan2(float(goal_delta[1]), float(goal_delta[0])) - heading + math.pi) % (2 * math.pi) - math.pi
    ray_offsets = np.linspace(-math.pi / 2.0, math.pi / 2.0, 9)
    ray_distances = np.full(9, scenario.sensor_range_m, dtype=float)
    for index, offset in enumerate(ray_offsets):
        direction = np.array([math.cos(heading + float(offset)), math.sin(heading + float(offset))])
        candidates: list[float] = []
        for obstacle in static_obstacles:
            bottom = obstacle.center[2] - obstacle.size[2] / 2.0 - own.radius_m
            top = obstacle.center[2] + obstacle.size[2] / 2.0 + own.radius_m
            if not bottom <= own.position[2] <= top:
                continue
            hit = _ray_aabb_distance_2d(own.position[:2], direction, obstacle, own.radius_m)
            if hit is not None:
                candidates.append(hit)
        for position in neighbor_positions:
            if abs(float(position[2] - own.position[2])) > scenario.protected_separation_m:
                continue
            hit = _ray_circle_distance(
                own.position[:2], direction, np.asarray(position), scenario.protected_separation_m / 2.0
            )
            if hit is not None:
                candidates.append(hit)
        for obstacle in dynamic_obstacles:
            if abs(float(obstacle.position[2] - own.position[2])) > obstacle.radius_m + own.radius_m:
                continue
            hit = _ray_circle_distance(
                own.position[:2], direction, obstacle.position, obstacle.radius_m + own.radius_m
            )
            if hit is not None:
                candidates.append(hit)
        positive = [value for value in candidates if 0.0 <= value <= scenario.sensor_range_m]
        if positive:
            ray_distances[index] = min(positive)
    proximity = 1.0 - ray_distances / scenario.sensor_range_m
    values = np.concatenate((
        np.array([
            np.clip(goal_distance / 200.0, 0.0, 1.0),
            math.sin(goal_bearing),
            math.cos(goal_bearing),
            np.clip(np.linalg.norm(own.velocity) / scenario.target_speed_mps, 0.0, 1.0),
            0.0,
        ], dtype=np.float32),
        proximity.astype(np.float32),
        np.asarray(previous_action, dtype=np.float32),
    ))
    return np.clip(values, -1.0, 1.0).astype(np.float32)


def _clone_drone(drone: DroneState) -> DroneState:
    return DroneState(
        drone.vehicle_id,
        np.array(drone.position, dtype=float),
        np.array(drone.velocity, dtype=float),
        np.array(drone.goal, dtype=float),
        drone.radius_m,
        drone.arrived,
    )


def create_complex_crossing_scenario(seed: int = 19, drone_count: int = 12) -> CrossingScenario:
    """Create high-altitude crossing traffic inside a cluttered urban work zone."""
    if drone_count < 4:
        raise ValueError("high-speed crossing requires at least four drones")
    rng = np.random.default_rng(seed)
    drones: list[DroneState] = []
    for vehicle_id in range(drone_count):
        angle = 2.0 * math.pi * vehicle_id / drone_count
        radius = 70.0 + float(rng.uniform(-2.0, 2.0))
        altitude = 46.0 + 4.0 * (vehicle_id % 4)
        position = np.array([radius * math.cos(angle), radius * math.sin(angle), altitude])
        goal_altitude = 46.0 + 4.0 * ((vehicle_id + 2) % 4)
        goal = np.array([-position[0], -position[1], goal_altitude])
        initial_speed = 11.5 + 0.45 * (vehicle_id % 4)
        velocity = _unit(goal - position) * initial_speed
        drones.append(DroneState(vehicle_id, position, velocity, goal))

    buildings = [
        BoxObstacle("building_0", (-35.0, -31.0, 25.0), (18.0, 20.0, 50.0)),
        BoxObstacle("building_1", (-12.0, -39.0, 20.0), (14.0, 16.0, 40.0)),
        BoxObstacle("building_2", (18.0, -38.0, 28.0), (18.0, 18.0, 56.0)),
        BoxObstacle("building_3", (40.0, -24.0, 22.0), (16.0, 22.0, 44.0)),
        BoxObstacle("building_4", (38.0, 27.0, 22.0), (20.0, 18.0, 44.0)),
        BoxObstacle("building_5", (15.0, 39.0, 24.0), (16.0, 18.0, 48.0)),
        BoxObstacle("building_6", (-15.0, 40.0, 29.0), (18.0, 16.0, 58.0)),
        BoxObstacle("building_7", (-39.0, 25.0, 20.0), (18.0, 22.0, 40.0)),
        BoxObstacle("crane_tower", (24.0, -12.0, 34.0), (3.0, 3.0, 68.0)),
        BoxObstacle("crane_boom", (10.0, -12.0, 63.0), (31.0, 2.0, 2.0)),
        BoxObstacle("radio_tower", (-22.0, 12.0, 38.0), (3.0, 3.0, 76.0)),
        BoxObstacle("rooftop_unit", (15.0, 39.0, 51.0), (6.0, 5.0, 6.0)),
    ]
    dynamic = [
        MovingObstacle("helicopter_corridor", np.array([8.0, -82.0, 55.0]), np.array([0.0, 13.0, 0.0]), 3.5),
        MovingObstacle("crane_load", np.array([9.0, -12.0, 55.0]), np.array([0.7, 0.0, 0.0]), 2.2),
    ]
    return CrossingScenario(drones, buildings, dynamic, seed=seed)


def _box_clearance_and_normal(point: np.ndarray, obstacle: BoxObstacle, margin: float = 0.0) -> tuple[float, np.ndarray]:
    center = np.asarray(obstacle.center, dtype=float)
    half = np.asarray(obstacle.size, dtype=float) / 2.0 + margin
    delta = point - center
    q = np.abs(delta) - half
    outside = np.maximum(q, 0.0)
    outside_distance = float(np.linalg.norm(outside))
    if outside_distance > 1e-9:
        nearest = center + np.clip(delta, -half, half)
        return outside_distance, _unit(point - nearest)
    axis = int(np.argmax(q))
    normal = np.zeros(3)
    normal[axis] = 1.0 if delta[axis] >= 0.0 else -1.0
    return float(np.max(q)), normal


def _avoid_track(
    own: DroneState,
    other_id: int,
    relative_position: np.ndarray,
    other_velocity: np.ndarray,
    scenario: CrossingScenario,
    *,
    reciprocal: bool,
) -> tuple[np.ndarray, EncounterType, bool]:
    encounter = classify_encounter(relative_position, own.velocity, other_velocity)
    time_s, miss_distance = time_to_closest_approach(
        relative_position, own.velocity, other_velocity, scenario.collision_horizon_s
    )
    closing_velocity = own.velocity - other_velocity
    miss_vector = relative_position - closing_velocity * time_s
    closing_speed = max(0.0, float(np.dot(_unit(relative_position), own.velocity - other_velocity)))
    delay_margin = closing_speed * (scenario.perception_latency_s + scenario.dt_s)
    required = scenario.planning_separation_m + min(2.5, delay_margin)
    current_distance = float(np.linalg.norm(relative_position))
    threatening = (
        current_distance < required * 1.35
        or (0.05 < time_s < scenario.collision_horizon_s and miss_distance < required)
    )
    if not threatening:
        return np.zeros(3), encounter, False

    forward = _unit(own.velocity)
    horizontal = _unit(np.array([forward[0], forward[1], 0.0]))
    right = np.array([horizontal[1], -horizontal[0], 0.0])
    vertical_sign = 1.0 if own.vehicle_id < other_id else -1.0
    urgency = max(0.15, 1.0 - time_s / scenario.collision_horizon_s)
    penetration = max(0.0, (required - miss_distance) / max(required, 0.1))
    strength = scenario.max_acceleration_mps2 * min(1.0, 0.35 + 0.65 * urgency + 0.35 * penetration)

    if encounter is EncounterType.VERTICAL:
        direction = np.array([0.25 * right[0], 0.25 * right[1], vertical_sign])
    elif encounter in {EncounterType.CROSSING, EncounterType.OVERTAKING} and np.linalg.norm(miss_vector) > 0.2:
        # The closest-point normal is reciprocal: the other aircraft observes
        # the opposite vector and therefore separates in the opposite direction.
        direction = _unit(-miss_vector) + 0.35 * right + np.array([0.0, 0.0, 0.28 * vertical_sign])
    else:
        direction = right + np.array([0.0, 0.0, 0.42 * vertical_sign])
    brake = -horizontal * strength * (0.22 if time_s < 1.6 else 0.08)
    correction = _unit(direction) * strength + brake
    if current_distance < required * 1.15:
        correction += _unit(-relative_position) * strength * 0.85
        correction -= horizontal * strength * 0.35
    if reciprocal:
        correction *= 0.72
    return correction, encounter, True


def _static_avoidance(own: DroneState, scenario: CrossingScenario) -> tuple[np.ndarray, bool, float]:
    correction = np.zeros(3)
    active = False
    minimum = math.inf
    for obstacle in scenario.static_obstacles:
        present, _ = _box_clearance_and_normal(own.position, obstacle, own.radius_m)
        minimum = min(minimum, present)
        for time_s in (0.45, 0.9, 1.5, 2.3):
            predicted = own.position + own.velocity * time_s
            clearance, normal = _box_clearance_and_normal(predicted, obstacle, own.radius_m + 1.0)
            trigger = 8.0 + 0.8 * time_s
            if clearance >= trigger:
                continue
            weight = max(0.0, (trigger - clearance) / trigger) / (0.45 + time_s)
            correction += normal * scenario.max_acceleration_mps2 * 1.35 * weight
            correction -= _unit(own.velocity) * scenario.max_acceleration_mps2 * 0.18 * weight
            active = True
    return _limit(correction, scenario.max_acceleration_mps2 * 1.4), active, minimum


def run_high_speed_trial(
    scenario: CrossingScenario,
    *,
    navigation_policy=None,
    safety_shield: bool = True,
) -> HighSpeedTrialResult:
    """Run one deterministic trial and return an auditable trace and safety gates."""
    rng = np.random.default_rng(scenario.seed)
    policy = navigation_policy or GoalNavigationPolicy()
    drones = [_clone_drone(drone) for drone in scenario.drones]
    moving = [MovingObstacle(item.name, item.position.copy(), item.velocity.copy(), item.radius_m) for item in scenario.dynamic_obstacles]
    latency_steps = max(1, int(round(scenario.perception_latency_s / scenario.dt_s)))
    position_history: list[np.ndarray] = [np.stack([drone.position.copy() for drone in drones])]
    velocity_history: list[np.ndarray] = [np.stack([drone.velocity.copy() for drone in drones])]
    last_tracks: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    trace: list[dict] = []
    encounters = {kind.value: 0 for kind in EncounterType if kind is not EncounterType.CLEAR}
    interventions = obstacle_interventions = dropped_frames = 0
    collisions: set[tuple[int, int]] = set()
    obstacle_contacts: set[tuple[int, str]] = set()
    minimum_separation = math.inf
    minimum_obstacle_clearance = math.inf
    previous_actions = {drone.vehicle_id: np.zeros(2, dtype=np.float32) for drone in drones}
    total_steps = int(round(scenario.duration_s / scenario.dt_s))

    for step in range(total_steps + 1):
        now = step * scenario.dt_s
        delayed_index = max(0, len(position_history) - 1 - latency_steps)
        sensed_positions = position_history[delayed_index]
        sensed_velocities = velocity_history[delayed_index]
        commands: list[np.ndarray] = []
        navigation_commands: list[NavigationCommand] = []
        step_events: list[list[str]] = [[] for _ in drones]

        for own_index, own in enumerate(drones):
            distance_to_goal = float(np.linalg.norm(own.goal - own.position))
            if distance_to_goal <= scenario.goal_tolerance_m:
                own.arrived = True
            local_observation = build_local_navigation_observation(
                own,
                neighbor_positions=[
                    sensed_positions[index]
                    for index in range(len(drones))
                    if index != own_index
                ],
                dynamic_obstacles=moving,
                static_obstacles=scenario.static_obstacles,
                scenario=scenario,
                previous_action=previous_actions[own.vehicle_id],
            )
            navigation = policy.preferred_velocity(own, local_observation, scenario)
            previous_actions[own.vehicle_id] = np.asarray(navigation.action, dtype=np.float32)
            navigation_commands.append(navigation)
            desired_velocity = np.zeros(3) if own.arrived else navigation.velocity
            acceleration = _limit((desired_velocity - own.velocity) * 1.8, scenario.max_acceleration_mps2)

            for other_index, other in enumerate(drones) if safety_shield else ():
                if own_index == other_index:
                    continue
                key = (own.vehicle_id, other.vehicle_id)
                if rng.random() < scenario.frame_drop_probability:
                    dropped_frames += 1
                    if key not in last_tracks:
                        continue
                    relative_position, other_velocity = last_tracks[key]
                else:
                    noisy_other = sensed_positions[other_index] + rng.normal(0.0, scenario.position_noise_m, 3)
                    noisy_own = sensed_positions[own_index] + rng.normal(0.0, scenario.position_noise_m * 0.35, 3)
                    relative_position = noisy_other - noisy_own
                    other_velocity = sensed_velocities[other_index] + rng.normal(0.0, scenario.velocity_noise_mps, 3)
                    last_tracks[key] = (relative_position, other_velocity)
                if float(np.linalg.norm(relative_position)) > scenario.sensor_range_m:
                    continue
                correction, encounter, active = _avoid_track(
                    own, other.vehicle_id, relative_position, other_velocity, scenario, reciprocal=True
                )
                if encounter is not EncounterType.CLEAR:
                    encounters[encounter.value] += 1
                if active:
                    acceleration += correction
                    interventions += 1
                    step_events[own_index].append(encounter.value)

            for obstacle_index, obstacle in enumerate(moving) if safety_shield else ():
                relative_position = obstacle.position - own.position
                if float(np.linalg.norm(relative_position)) > scenario.sensor_range_m:
                    continue
                correction, encounter, active = _avoid_track(
                    own, len(drones) + obstacle_index, relative_position, obstacle.velocity, scenario, reciprocal=False
                )
                if active:
                    acceleration += correction
                    interventions += 1
                    step_events[own_index].append(f"dynamic:{encounter.value}")

            static_correction, static_active, clearance = _static_avoidance(own, scenario)
            minimum_obstacle_clearance = min(minimum_obstacle_clearance, clearance)
            if safety_shield and static_active:
                acceleration += static_correction
                obstacle_interventions += 1
                step_events[own_index].append("static")
            commands.append(_limit(acceleration, scenario.max_acceleration_mps2))

        gust = scenario.wind_gust_mps * np.array([
            math.sin(0.63 * now + 0.4),
            math.sin(0.91 * now + 2.1),
            0.18 * math.sin(1.37 * now),
        ])
        wind = np.asarray(scenario.steady_wind_mps) + gust
        for index, (drone, acceleration, navigation) in enumerate(zip(drones, commands, navigation_commands)):
            disturbance = (wind - drone.velocity * 0.04) * 0.08
            drone.velocity = _limit(drone.velocity + (acceleration + disturbance) * scenario.dt_s, scenario.max_speed_mps)
            drone.position = drone.position + drone.velocity * scenario.dt_s
            trace.append({
                "step": step,
                "t_s": round(now, 3),
                "vehicle_id": drone.vehicle_id,
                "x_m": round(float(drone.position[0]), 4),
                "y_m": round(float(drone.position[1]), 4),
                "z_m": round(float(drone.position[2]), 4),
                "speed_mps": round(float(np.linalg.norm(drone.velocity)), 4),
                "goal_distance_m": round(float(np.linalg.norm(drone.goal - drone.position)), 4),
                "arrived": drone.arrived,
                "events": ";".join(sorted(set(step_events[index]))),
                "navigation_source": navigation.source,
                "policy_action_speed": round(float(navigation.action[0]), 5),
                "policy_action_yaw": round(float(navigation.action[1]), 5),
                "safety_override": bool(step_events[index]),
            })

        for first_index, first in enumerate(drones):
            for second in drones[first_index + 1:]:
                distance = float(np.linalg.norm(first.position - second.position))
                minimum_separation = min(minimum_separation, distance)
                if distance <= first.radius_m + second.radius_m:
                    collisions.add((first.vehicle_id, second.vehicle_id))
            for obstacle in scenario.static_obstacles:
                clearance, _normal = _box_clearance_and_normal(first.position, obstacle, first.radius_m)
                minimum_obstacle_clearance = min(minimum_obstacle_clearance, clearance)
                if clearance <= 0.0:
                    obstacle_contacts.add((first.vehicle_id, obstacle.name))
        for obstacle in moving:
            obstacle.position = obstacle.position + obstacle.velocity * scenario.dt_s
        position_history.append(np.stack([drone.position.copy() for drone in drones]))
        velocity_history.append(np.stack([drone.velocity.copy() for drone in drones]))

    arrived = int(sum(
        bool(drone.arrived or np.linalg.norm(drone.goal - drone.position) <= scenario.goal_tolerance_m)
        for drone in drones
    ))
    checks = {
        "zero_collisions": not collisions,
        "zero_static_obstacle_contacts": not obstacle_contacts,
        "safe_intervehicle_separation": minimum_separation >= scenario.protected_separation_m,
        "at_least_80_percent_arrived": bool(arrived >= math.ceil(0.8 * len(drones))),
        "encounters_were_locally_classified": sum(encounters.values()) > 0,
        "avoidance_was_exercised": interventions > 0,
        "no_central_avoidance_commands": scenario.central_avoidance_commands == 0,
    }
    metrics = {
        "vehicles": len(drones),
        "duration_s": scenario.duration_s,
        "target_speed_mps": scenario.target_speed_mps,
        "goal_tolerance_m": scenario.goal_tolerance_m,
        "maximum_observed_speed_mps": round(max(row["speed_mps"] for row in trace), 4),
        "arrived": arrived,
        "collisions": len(collisions),
        "static_obstacle_contacts": len(obstacle_contacts),
        "minimum_intervehicle_distance_m": round(minimum_separation, 4),
        "minimum_static_obstacle_clearance_m": round(minimum_obstacle_clearance, 4),
        "encounters_classified": sum(encounters.values()),
        "encounters_by_type": encounters,
        "avoidance_interventions": interventions,
        "static_avoidance_interventions": obstacle_interventions,
        "dropped_local_frames": dropped_frames,
        "perception_latency_s": scenario.perception_latency_s,
        "frame_drop_probability": scenario.frame_drop_probability,
        "wind_gust_mps": scenario.wind_gust_mps,
        "central_avoidance_commands": scenario.central_avoidance_commands,
        "navigation_policy": policy.source,
        "learned_policy_calls": int(getattr(policy, "predict_calls", 0)) if policy.source != "goal-vector-rules" else 0,
        "navigation_policy_calls": int(getattr(policy, "predict_calls", 0)),
        "safety_shield_enabled": bool(safety_shield),
        "safety_overrides": interventions + obstacle_interventions,
    }
    summary = {
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "scope": "Kinematic 3-D stress simulation; not a hardware flight-safety certification.",
    }
    return HighSpeedTrialResult(trace, summary, scenario)


def _box_model(obstacle: BoxObstacle, color: str = "0.45 0.48 0.52 1") -> str:
    x, y, z = obstacle.center
    sx, sy, sz = obstacle.size
    return f"""
    <model name='{obstacle.name}'>
      <static>true</static><pose>{x} {y} {z} 0 0 0</pose>
      <link name='link'>
        <collision name='collision'><geometry><box><size>{sx} {sy} {sz}</size></box></geometry></collision>
        <visual name='visual'><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
          <material><ambient>{color}</ambient><diffuse>{color}</diffuse></material></visual>
      </link>
    </model>"""


def render_urban_crossing_world() -> str:
    """Render a self-contained Gazebo Harmonic urban crossing world."""
    scenario = create_complex_crossing_scenario()
    models = "\n".join(
        _box_model(obstacle, "0.72 0.55 0.32 1" if "crane" in obstacle.name else "0.38 0.42 0.48 1")
        for obstacle in scenario.static_obstacles
    )
    return f"""<?xml version='1.0'?>
<sdf version='1.9'>
  <world name='flydrones_urban_crossing'>
    <physics type='ode'><max_step_size>0.004</max_step_size><real_time_factor>1</real_time_factor></physics>
    <gravity>0 0 -9.81</gravity>
    <wind><linear_velocity>2.2 -1.1 0</linear_velocity></wind>
    <scene><ambient>0.45 0.47 0.5 1</ambient><background>0.55 0.68 0.82 1</background><shadows>true</shadows></scene>
    <light name='sun' type='directional'><pose>0 0 150 0 0 0</pose><direction>-0.35 0.25 -0.9</direction>
      <diffuse>0.9 0.88 0.82 1</diffuse><cast_shadows>true</cast_shadows></light>
    <model name='ground_plane'><static>true</static><link name='link'>
      <collision name='collision'><geometry><plane><normal>0 0 1</normal><size>240 240</size></plane></geometry></collision>
      <visual name='visual'><geometry><plane><normal>0 0 1</normal><size>240 240</size></plane></geometry>
        <material><ambient>0.12 0.14 0.15 1</ambient><diffuse>0.12 0.14 0.15 1</diffuse></material></visual>
      <enable_wind>true</enable_wind></link></model>
    {_box_model(BoxObstacle('road_ns', (0, 0, 0.03), (18, 180, 0.05)), '0.08 0.09 0.1 1')}
    {_box_model(BoxObstacle('road_ew', (0, 0, 0.04), (180, 18, 0.06)), '0.08 0.09 0.1 1')}
    {models}
    <spherical_coordinates><surface_model>EARTH_WGS84</surface_model><world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>31.2304</latitude_deg><longitude_deg>121.4737</longitude_deg><elevation>8</elevation></spherical_coordinates>
  </world>
</sdf>
"""
