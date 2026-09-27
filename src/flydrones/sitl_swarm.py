"""Five-vehicle PX4/Gazebo trial with one distilled local agent per vehicle."""

from __future__ import annotations

import csv
import heapq
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .gazebo_depth import DepthCameraBank, DepthObservation, px4_depth_camera_topics
from .motor.command import FlightCommand
from .numpy_policy import NumpyMlpPolicy


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SwarmVehicleSpec:
    vehicle_id: int
    system_id: int
    connection: str
    home_xy: tuple[float, float]

    def global_position(self, local_north: float, local_east: float, altitude: float) -> tuple[float, float, float]:
        """Convert MAVLink local NED telemetry to Gazebo's shared ENU world."""
        return self.home_xy[0] + local_east, self.home_xy[1] + local_north, altitude


@dataclass(frozen=True)
class PeerBroadcastConfig:
    """Limits applied to the simulated peer-to-peer position radio."""

    range_m: float = 8.0
    latency_s: float = 0.12
    jitter_s: float = 0.04
    packet_loss: float = 0.15
    track_ttl_s: float = 0.65
    blackout_windows_s: tuple[tuple[float, float], ...] = ()
    seed: int = 20260921


class PeerBroadcastNetwork:
    """A radio medium that gives each vehicle its own delayed peer cache."""

    def __init__(self, vehicle_count: int, config: PeerBroadcastConfig, *, epoch_s: float = 0.0):
        if vehicle_count < 1:
            raise ValueError("vehicle_count must be positive")
        if config.range_m <= 0.0 or config.track_ttl_s <= 0.0:
            raise ValueError("radio range and track TTL must be positive")
        if config.latency_s < 0.0 or config.jitter_s < 0.0 or not 0.0 <= config.packet_loss <= 1.0:
            raise ValueError("invalid peer radio timing or packet loss")
        self.vehicle_count = vehicle_count
        self.config = config
        self.epoch_s = float(epoch_s)
        self._random = random.Random(config.seed)
        self._sequence = 0
        self._pending: list[tuple[float, int, int, int, tuple[float, float, float], float]] = []
        self._tracks: list[dict[int, tuple[tuple[float, float, float], float, float]]] = [
            {} for _ in range(vehicle_count)
        ]
        self.received_by_vehicle = [0] * vehicle_count
        self.metrics = {
            "attempted_packets": 0,
            "delivered_packets": 0,
            "random_dropped_packets": 0,
            "blackout_dropped_packets": 0,
            "out_of_range_packets": 0,
            "stale_tracks_expired": 0,
        }

    def _in_blackout(self, now_s: float) -> bool:
        elapsed = now_s - self.epoch_s
        return any(start <= elapsed <= end for start, end in self.config.blackout_windows_s)

    def exchange(self, now_s: float, positions: list[tuple[float, float, float]]) -> None:
        """Broadcast one local position packet from every vehicle."""
        if len(positions) != self.vehicle_count:
            raise ValueError("one broadcast position is required per vehicle")
        self.advance(now_s)
        blackout = self._in_blackout(now_s)
        for sender_id, sender_position in enumerate(positions):
            for receiver_id, receiver_position in enumerate(positions):
                if sender_id == receiver_id:
                    continue
                self.metrics["attempted_packets"] += 1
                if blackout:
                    self.metrics["blackout_dropped_packets"] += 1
                    continue
                if math.dist(sender_position, receiver_position) > self.config.range_m:
                    self.metrics["out_of_range_packets"] += 1
                    continue
                if self._random.random() < self.config.packet_loss:
                    self.metrics["random_dropped_packets"] += 1
                    continue
                jitter = self._random.uniform(-self.config.jitter_s, self.config.jitter_s)
                deliver_at = now_s + max(0.0, self.config.latency_s + jitter)
                self._sequence += 1
                heapq.heappush(
                    self._pending,
                    (deliver_at, self._sequence, receiver_id, sender_id, tuple(sender_position), now_s),
                )
        self.advance(now_s)

    def advance(self, now_s: float) -> None:
        while self._pending and self._pending[0][0] <= now_s:
            deliver_at, _sequence, receiver_id, sender_id, position, sent_at = heapq.heappop(self._pending)
            self._tracks[receiver_id][sender_id] = (position, deliver_at, sent_at)
            self.received_by_vehicle[receiver_id] += 1
            self.metrics["delivered_packets"] += 1

    def neighbors(self, vehicle_id: int, now_s: float) -> list[tuple[float, float, float]]:
        if not 0 <= vehicle_id < self.vehicle_count:
            raise IndexError(vehicle_id)
        self.advance(now_s)
        tracks = self._tracks[vehicle_id]
        expired = [sender_id for sender_id, (_position, received_at, _sent_at) in tracks.items()
                   if now_s - received_at > self.config.track_ttl_s]
        for sender_id in expired:
            del tracks[sender_id]
            self.metrics["stale_tracks_expired"] += 1
        return [tracks[sender_id][0] for sender_id in sorted(tracks)]


def px4_swarm_specs(count: int = 5, *, lane_spacing_m: float = 1.5) -> list[SwarmVehicleSpec]:
    if count != 5:
        raise ValueError("the current PX4 staged trial requires exactly five vehicles")
    home_y = tuple((index - 2) * lane_spacing_m for index in range(count))
    return [
        SwarmVehicleSpec(
            vehicle_id=index,
            system_id=index + 1,
            connection=f"udpin:0.0.0.0:{14540 + index}",
            home_xy=(0.0, home_y[index]),
        )
        for index in range(count)
    ]


def px4_swarm_obstacles(*, lane_spacing_m: float = 1.5) -> list[tuple[float, float, float]]:
    return [(2.5, (index - 2) * lane_spacing_m + 0.05, 0.22) for index in range(5)]


def px4_swarm_rally_targets(*, lane_spacing_m: float = 1.5) -> list[tuple[float, float]]:
    scale = 2.6 / 3.0 if math.isclose(lane_spacing_m, 1.5) else 0.8
    return [(6.5, (index - 2) * lane_spacing_m * scale) for index in range(5)]


@dataclass
class NeuralSaccadeState:
    active_until: float = -math.inf
    cooldown_until: float = -math.inf
    side: int = 0
    bypass_until_x: float = -math.inf
    bypass_until_time: float = -math.inf
    corridor_y: float = 0.0
    escape_heading: tuple[float, float] = (1.0, 0.0)


@dataclass
class DistilledForestAgent:
    vehicle_id: int
    rally_target: tuple[float, float]
    obstacles: list[tuple[float, float, float]]
    ready_at: float = 2.0
    target_altitude_m: float = 1.8
    escape_x_m: float = 5.5
    warning_distance_m: float = 1.4
    saccade_seconds: float = 1.4
    cooldown_seconds: float = 5.0
    max_horizontal_speed_mps: float = 0.8
    vertical_speed_scale_mps: float = 0.5
    neural_state: NeuralSaccadeState = field(default_factory=NeuralSaccadeState)
    neural_triggers: int = 0
    phase: str = "escaping"

    def _start_saccade(
        self,
        now: float,
        position: tuple[float, float, float],
        heading: tuple[float, float],
        side: int,
        *,
        sensor_only: bool,
    ) -> None:
        self.neural_state.side = side
        self.neural_state.active_until = now + self.saccade_seconds
        self.neural_state.cooldown_until = self.neural_state.active_until + self.cooldown_seconds
        self.neural_state.corridor_y = position[1] + side * 0.72
        self.neural_state.escape_heading = heading
        if sensor_only:
            self.neural_state.bypass_until_time = self.neural_state.active_until + 1.7
        self.neural_triggers += 1

    def _trigger_depth_reflex(
        self,
        now: float,
        position: tuple[float, float, float],
        heading: tuple[float, float],
        observation: DepthObservation,
    ) -> None:
        if now < self.ready_at or now <= self.neural_state.cooldown_until or self.phase != "escaping":
            return
        if observation.nearest_distance_m > self.warning_distance_m:
            return
        difference = observation.left_clearance_m - observation.right_clearance_m
        if abs(difference) < 0.08:
            side = -1
        else:
            side = 1 if difference > 0 else -1
        self._start_saccade(now, position, heading, side, sensor_only=True)

    def _trigger_neural_reflex(self, now: float, position: tuple[float, float, float], heading: tuple[float, float]) -> None:
        if now < self.ready_at or now <= self.neural_state.cooldown_until or self.phase != "escaping":
            return
        nearest: tuple[float, float, float, float] | None = None
        for x, y, radius in self.obstacles:
            relative = (x - position[0], y - position[1])
            centre_distance = math.hypot(*relative)
            surface_distance = centre_distance - radius
            if centre_distance < 1e-9 or surface_distance > self.warning_distance_m:
                continue
            ahead = (relative[0] * heading[0] + relative[1] * heading[1]) / centre_distance
            if ahead < 0.35:
                continue
            if nearest is None or surface_distance < nearest[2]:
                nearest = relative[0], relative[1], surface_distance, x
        if nearest is None:
            return
        def side_clearance(side: int) -> float:
            candidate_y = position[1] + side * 1.0
            return min(
                math.hypot(nearest[3] - obstacle_x, candidate_y - obstacle_y) - obstacle_radius
                for obstacle_x, obstacle_y, obstacle_radius in self.obstacles
            )

        left_clearance = side_clearance(1)
        right_clearance = side_clearance(-1)
        if abs(left_clearance - right_clearance) < 1e-9:
            side = -1 if self.vehicle_id % 2 == 0 else 1
        else:
            side = 1 if left_clearance > right_clearance else -1
        self.neural_state.bypass_until_x = nearest[3] + 0.7
        self._start_saccade(now, position, heading, side, sensor_only=False)

    def command(
        self,
        now: float,
        global_position: tuple[float, float, float],
        yaw_rad: float,
        neighbors: list[tuple[float, float, float]],
        depth_observation: DepthObservation | None = None,
    ) -> FlightCommand:
        if global_position[0] >= self.escape_x_m and self.phase == "escaping":
            self.phase = "rally"
        error = (self.rally_target[0] - global_position[0], self.rally_target[1] - global_position[1])
        distance = math.hypot(*error)
        if distance < 0.35:
            self.phase = "arrived"
        heading = (1.0, 0.0) if distance < 1e-9 else (error[0] / distance, error[1] / distance)
        if depth_observation is None:
            self._trigger_neural_reflex(now, global_position, heading)
        else:
            self._trigger_depth_reflex(now, global_position, heading, depth_observation)

        if self.neural_state.active_until < now < self.neural_state.bypass_until_time:
            stored = self.neural_state.escape_heading
            lateral_error = self.neural_state.corridor_y - global_position[1]
            vx = stored[0] * self.max_horizontal_speed_mps
            vy = stored[1] * self.max_horizontal_speed_mps + _clamp(lateral_error * 0.6, -0.25, 0.25)
            distance = self.max_horizontal_speed_mps
            heading_norm = math.hypot(vx, vy)
            heading = (vx / heading_norm, vy / heading_norm)
        elif now > self.neural_state.active_until and global_position[0] < self.neural_state.bypass_until_x - 0.08:
            bypass_error = (
                self.neural_state.bypass_until_x - global_position[0],
                self.neural_state.corridor_y - global_position[1],
            )
            bypass_distance = math.hypot(*bypass_error)
            if bypass_distance > 1e-9:
                heading = (bypass_error[0] / bypass_distance, bypass_error[1] / bypass_distance)
                distance = bypass_distance

        speed = min(self.max_horizontal_speed_mps, distance * 0.8)
        vx, vy = heading[0] * speed, heading[1] * speed
        if now <= self.neural_state.active_until:
            corridor_error = self.neural_state.corridor_y - global_position[1]
            vx = heading[0] * 0.2
            vy = heading[1] * 0.2 + _clamp(corridor_error * 1.8, -0.72, 0.72)

        for neighbor in neighbors:
            dx = global_position[0] - neighbor[0]
            dy = global_position[1] - neighbor[1]
            horizontal = math.hypot(dx, dy)
            if horizontal < 1e-9 or horizontal >= 1.4:
                continue
            repulsion = min(0.8, (1.4 - horizontal) * 2.0)
            vx += dx / horizontal * repulsion
            vy += dy / horizontal * repulsion

        horizontal_speed = math.hypot(vx, vy)
        if horizontal_speed > self.max_horizontal_speed_mps:
            vx *= self.max_horizontal_speed_mps / horizontal_speed
            vy *= self.max_horizontal_speed_mps / horizontal_speed

        world_yaw = math.pi / 2.0 - yaw_rad
        cos_yaw, sin_yaw = math.cos(world_yaw), math.sin(world_yaw)
        forward = (cos_yaw * vx + sin_yaw * vy) / self.max_horizontal_speed_mps
        lateral = (sin_yaw * vx - cos_yaw * vy) / self.max_horizontal_speed_mps
        throttle = (self.target_altitude_m - global_position[2]) / self.vertical_speed_scale_mps
        return FlightCommand(
            throttle=_clamp(throttle, -1.0, 1.0),
            forward=_clamp(forward, -1.0, 1.0),
            lateral=_clamp(lateral, -1.0, 1.0),
            note=f"px4 swarm {self.phase}",
        )


@dataclass
class LearnedDepthForestAgent:
    """Run the exported forest PPO from nine real depth-image sectors."""

    vehicle_id: int
    rally_target: tuple[float, float]
    policy: NumpyMlpPolicy
    target_altitude_m: float = 1.8
    corridor_center_y: float | None = None
    corridor_half_width_m: float = 0.80
    max_horizontal_speed_mps: float = 0.8
    vertical_speed_scale_mps: float = 0.5
    sensor_range_m: float = 19.1
    warning_distance_m: float = 1.4
    phase: str = "escaping"
    previous_action: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    policy_calls: int = 0
    neural_triggers: int = 0
    sensor_holds: int = 0
    docking_overrides: int = 0
    recovery_overrides: int = 0
    corridor_overrides: int = 0
    emergency_latch_overrides: int = 0
    emergency_distance_m: float = 0.90
    emergency_stop_seconds: float = 1.10
    emergency_escape_seconds: float = 0.90
    emergency_stop_until_s: float = -math.inf
    emergency_escape_until_s: float = -math.inf
    emergency_yaw: float = 0.0
    last_safety_override: bool = False
    last_policy_action: tuple[float, float] = (0.0, 0.0)

    def command(
        self,
        now: float,
        global_position: tuple[float, float, float],
        yaw_rad: float,
        neighbors: list[tuple[float, float, float]],
        depth_observation: DepthObservation | None = None,
    ) -> FlightCommand:
        error_x = self.rally_target[0] - global_position[0]
        error_y = self.rally_target[1] - global_position[1]
        distance = math.hypot(error_x, error_y)
        if global_position[0] >= 4.0 and self.phase == "escaping":
            self.phase = "rally"
        if distance < 0.35:
            self.phase = "arrived"
        throttle = _clamp((self.target_altitude_m - global_position[2]) / self.vertical_speed_scale_mps, -1.0, 1.0)
        if self.phase == "arrived":
            self.last_policy_action = (0.0, 0.0)
            self.last_safety_override = False
            return FlightCommand(throttle=throttle, note="learned px4 swarm arrived")
        if depth_observation is None or len(depth_observation.ray_distances_m) != 9:
            self.sensor_holds += 1
            self.last_safety_override = True
            return FlightCommand(throttle=throttle, note="learned px4 depth hold")

        world_yaw = math.pi / 2.0 - yaw_rad
        bearing = (math.atan2(error_y, error_x) - world_yaw + math.pi) % (2.0 * math.pi) - math.pi
        rays = np.asarray(depth_observation.ray_distances_m, dtype=np.float32)
        proximity = 1.0 - np.clip(rays / self.sensor_range_m, 0.0, 1.0)
        observation = np.concatenate((
            np.asarray([
                np.clip(distance / 10.0, 0.0, 1.0),
                math.sin(bearing),
                math.cos(bearing),
                np.clip((self.previous_action[0] + 1.0) * 0.5, 0.0, 1.0),
                0.0,
            ], dtype=np.float32),
            proximity,
            self.previous_action,
        )).astype(np.float32)
        action = np.asarray(self.policy.predict(observation), dtype=np.float32)
        self.policy_calls += 1
        self.previous_action = action.copy()
        self.last_policy_action = (float(action[0]), float(action[1]))
        forward = float((action[0] + 1.0) * 0.5)
        # PPO heading grows counter-clockwise in ENU. MAVLink yaw rate grows
        # clockwise in NED, so the learned turn command must change sign.
        yaw = -float(action[1])
        self.last_safety_override = False

        nearest_index = int(np.argmin(rays))
        nearest = float(rays[nearest_index])
        docking = self.phase == "rally" and nearest > 1.8
        if docking:
            forward = min(0.38, max(0.08, distance * 0.25))
            yaw = _clamp(-bearing / 0.65, -0.75, 0.75)
            self.docking_overrides += 1
        recovering = self.phase == "escaping" and global_position[0] < -0.50 and nearest > 1.8
        if recovering:
            forward = 0.35
            yaw = _clamp(-bearing / 0.65, -0.75, 0.75)
            self.recovery_overrides += 1
        corridor_active = (
            self.phase == "escaping"
            and global_position[0] < 4.0
            and self.corridor_center_y is not None
            and abs(global_position[1] - self.corridor_center_y) > self.corridor_half_width_m
            and nearest > 0.75
        )
        if corridor_active:
            corridor_bearing = (
                math.atan2(self.corridor_center_y - global_position[1], 1.0) - world_yaw + math.pi
            ) % (2.0 * math.pi) - math.pi
            forward = 0.0 if abs(corridor_bearing) > 0.60 else 0.25
            yaw = _clamp(-corridor_bearing / 0.65, -0.85, 0.85)
            self.corridor_overrides += 1
        if nearest < self.warning_distance_m:
            safe_forward = _clamp((nearest - 0.45) / (self.warning_distance_m - 0.45), 0.0, 0.6)
            forward = min(forward, safe_forward)
            left_space = float(np.mean(rays[:4]))
            right_space = float(np.mean(rays[5:]))
            reflex_yaw = -1.0 if left_space > right_space else 1.0
            urgency = _clamp((self.warning_distance_m - nearest) / 0.9, 0.0, 1.0)
            reflex_yaw *= 0.55 + 0.45 * urgency
            if abs(reflex_yaw) > abs(yaw) or reflex_yaw * yaw < 0.0:
                yaw = reflex_yaw
            self.last_safety_override = True
            self.neural_triggers += 1

            if nearest < self.emergency_distance_m and now >= self.emergency_escape_until_s:
                self.emergency_stop_until_s = now + self.emergency_stop_seconds
                self.emergency_escape_until_s = self.emergency_stop_until_s + self.emergency_escape_seconds
                self.emergency_yaw = reflex_yaw

        emergency_stopping = now < self.emergency_stop_until_s
        emergency_escaping = self.emergency_stop_until_s <= now < self.emergency_escape_until_s
        emergency_active = emergency_stopping or emergency_escaping
        if emergency_stopping:
            forward = 0.0
            yaw = self.emergency_yaw
            self.last_safety_override = True
            self.emergency_latch_overrides += 1
        elif emergency_escaping:
            forward = 0.18 if nearest >= self.warning_distance_m else 0.0
            yaw = 0.0
            self.last_safety_override = True
            self.emergency_latch_overrides += 1

        peer_warning_distance = 1.60 if self.phase == "escaping" else 1.10
        for neighbor in (() if emergency_active else neighbors):
            dx = neighbor[0] - global_position[0]
            dy = neighbor[1] - global_position[1]
            horizontal = math.hypot(dx, dy)
            if horizontal >= peer_warning_distance or abs(neighbor[2] - global_position[2]) >= 1.0:
                continue
            relative_bearing = (math.atan2(dy, dx) - world_yaw + math.pi) % (2.0 * math.pi) - math.pi
            peer_stop_distance = 0.75 if self.phase == "escaping" else 0.65
            forward = min(forward, _clamp(
                (horizontal - peer_stop_distance) / (peer_warning_distance - peer_stop_distance),
                0.0,
                0.35,
            ))
            yaw = 1.0 if relative_bearing >= 0.0 else -1.0
            self.last_safety_override = True
            self.neural_triggers += 1
        if emergency_active:
            note = "learned px4 emergency latch"
        elif self.last_safety_override:
            note = "learned px4 depth shield"
        elif recovering:
            note = "learned px4 recovery"
        elif corridor_active:
            note = "learned px4 corridor"
        else:
            note = "learned px4 docking" if docking else "learned px4 ppo"
        return FlightCommand(
            throttle=throttle,
            yaw=_clamp(yaw, -1.0, 1.0),
            forward=_clamp(forward, -1.0, 1.0),
            note=note,
        )


def run_px4_swarm_trial(
    *,
    rate_hz: float = 20.0,
    target_alt_m: float = 1.8,
    takeoff_timeout_s: float = 25.0,
    mission_timeout_s: float = 35.0,
    land_timeout_s: float = 20.0,
    drone_factory=None,
    depth_camera_bank: DepthCameraBank | None = None,
    require_depth_cameras: bool = False,
    depth_camera_timeout_s: float = 25.0,
    lane_spacing_m: float = 1.5,
    learned_policy_path: str | Path | None = None,
    peer_broadcast_config: PeerBroadcastConfig | None = None,
    allow_mission_timeout: bool = False,
    time_fn=None,
    sleep_fn=None,
) -> tuple[list[dict], dict, list[int]]:
    """Run five identical local agents against five independent PX4 links."""
    if learned_policy_path is not None and not require_depth_cameras:
        raise ValueError("the learned PX4 policy requires per-vehicle depth cameras")
    if drone_factory is None:
        from .drones.mavlink import MavlinkDrone

        drone_factory = MavlinkDrone
    now = time_fn or time.monotonic
    sleep = sleep_fn or time.sleep
    period = 1.0 / max(5.0, float(rate_hz))
    specs = px4_swarm_specs(lane_spacing_m=lane_spacing_m)
    obstacles = px4_swarm_obstacles(lane_spacing_m=lane_spacing_m)
    rally_targets = px4_swarm_rally_targets(lane_spacing_m=lane_spacing_m)
    drones = [
        drone_factory(
            connection=spec.connection,
            autopilot="px4",
            takeoff_alt=target_alt_m,
            v_max=0.8,
            vz_max=0.5,
            offboard_rate_hz=rate_hz,
        )
        for spec in specs
    ]
    trace: list[dict] = []
    start = now()
    step = 0
    latest_depth: list[DepthObservation | None] = [None] * len(specs)
    local_peer_track_counts = [0] * len(specs)
    peer_track_uses_by_vehicle = [0] * len(specs)
    direct_global_neighbor_reads = 0
    peer_network: PeerBroadcastNetwork | None = None
    runtime_policy = NumpyMlpPolicy.load(learned_policy_path) if learned_policy_path is not None else None
    mission_timed_out = False
    mission_start: float | None = None

    def read_frame() -> list[tuple]:
        frame = []
        for spec, drone in zip(specs, drones):
            telemetry = drone.telemetry()
            local_x = float(telemetry.x_m or 0.0)
            local_y = float(telemetry.y_m or 0.0)
            altitude = float(telemetry.alt_m or 0.0)
            frame.append((spec, drone, telemetry, spec.global_position(local_x, local_y, altitude)))
        return frame

    def record(frame: list[tuple], phases: list[str]) -> None:
        nonlocal step
        for (spec, _drone, telemetry, position), phase in zip(frame, phases):
            observation = latest_depth[spec.vehicle_id]
            agent = agents[spec.vehicle_id] if len(agents) == len(specs) else None
            trace.append({
                "step": step,
                "t_s": round(now() - start, 4),
                "mission_elapsed_s": round(now() - mission_start, 4) if mission_start is not None else None,
                "vehicle_id": spec.vehicle_id,
                "system_id": spec.system_id,
                "phase": phase,
                "x_m": round(position[0], 4),
                "y_m": round(position[1], 4),
                "alt_m": round(position[2], 4),
                "yaw_deg": telemetry.yaw_deg,
                "battery_pct": telemetry.battery_pct,
                "depth_nearest_m": round(observation.nearest_distance_m, 4) if observation else None,
                "depth_bearing": round(observation.obstacle_bearing, 4) if observation else None,
                "depth_left_m": round(observation.left_clearance_m, 4) if observation else None,
                "depth_right_m": round(observation.right_clearance_m, 4) if observation else None,
                "depth_rays_m": ";".join(f"{value:.3f}" for value in observation.ray_distances_m) if observation else None,
                "navigation_policy": "ppo-forest-v1-numpy" if isinstance(agent, LearnedDepthForestAgent) else None,
                "policy_action_speed": round(agent.last_policy_action[0], 5) if isinstance(agent, LearnedDepthForestAgent) else None,
                "policy_action_yaw": round(agent.last_policy_action[1], 5) if isinstance(agent, LearnedDepthForestAgent) else None,
                "safety_override": agent.last_safety_override if isinstance(agent, LearnedDepthForestAgent) else None,
                "local_peer_tracks": local_peer_track_counts[spec.vehicle_id] if peer_network is not None else None,
            })
        step += 1

    connected = False
    agents: list[DistilledForestAgent | LearnedDepthForestAgent] = []
    camera_observations_used = [0] * len(specs)
    try:
        if require_depth_cameras:
            if depth_camera_bank is None:
                depth_camera_bank = DepthCameraBank(px4_depth_camera_topics(), clock=now)
            depth_camera_bank.start()
            if not depth_camera_bank.wait_until_ready(timeout_s=depth_camera_timeout_s):
                raise TimeoutError("not all five namespaced Gazebo depth cameras produced frames")
        for drone in drones:
            drone.connect()
        connected = True

        for _ in range(max(20, math.ceil(rate_hz * 1.2))):
            for drone in drones:
                drone.send(FlightCommand.hover("prime five-vehicle offboard"))
            sleep(period)

        for drone in drones:
            drone.m.set_mode("OFFBOARD")
            drone.m.arducopter_arm()
            drone.flying = True

        arm_deadline = now() + 12.0
        while True:
            armed = []
            for drone in drones:
                drone.send(FlightCommand.hover("waiting for five-vehicle arm"))
                drone.m.recv_match(type="HEARTBEAT", blocking=False)
                armed.append(not hasattr(drone.m, "motors_armed") or bool(drone.m.motors_armed()))
            if all(armed):
                break
            if now() >= arm_deadline:
                raise TimeoutError("not all five PX4 vehicles armed within 12 seconds")
            sleep(period)

        takeoff_deadline = now() + takeoff_timeout_s
        while True:
            frame = read_frame()
            record(frame, ["takeoff"] * len(frame))
            if all(position[2] >= target_alt_m - 0.15 for *_prefix, position in frame):
                break
            if now() >= takeoff_deadline:
                raise TimeoutError("not all five PX4 vehicles reached takeoff altitude")
            for _spec, drone, _telemetry, position in frame:
                throttle = _clamp((target_alt_m - position[2]) / 0.5, 0.0, 1.0)
                drone.send(FlightCommand(throttle=throttle, note="coordinated five-vehicle takeoff"))
            sleep(period)

        mission_start = now()
        if peer_broadcast_config is not None:
            peer_network = PeerBroadcastNetwork(len(specs), peer_broadcast_config, epoch_s=mission_start)
        if runtime_policy is not None:
            agents = [
                LearnedDepthForestAgent(
                    vehicle_id=spec.vehicle_id,
                    rally_target=rally_targets[spec.vehicle_id],
                    policy=runtime_policy,
                    target_altitude_m=target_alt_m,
                    corridor_center_y=spec.home_xy[1],
                )
                for spec in specs
            ]
        else:
            agents = [
                DistilledForestAgent(
                    vehicle_id=spec.vehicle_id,
                    rally_target=rally_targets[spec.vehicle_id],
                    obstacles=[] if require_depth_cameras else obstacles,
                    ready_at=mission_start + 0.2,
                    target_altitude_m=target_alt_m,
                )
                for spec in specs
            ]
        mission_deadline = now() + mission_timeout_s
        arrived_frames = 0
        while True:
            frame = read_frame()
            positions = [item[3] for item in frame]
            command_time = now()
            if peer_network is not None:
                peer_network.exchange(command_time, positions)
            commands = []
            for index, (_spec, _drone, telemetry, position) in enumerate(frame):
                if peer_network is None:
                    neighbors = [candidate for neighbor_index, candidate in enumerate(positions) if neighbor_index != index]
                    direct_global_neighbor_reads += len(neighbors)
                else:
                    neighbors = peer_network.neighbors(index, command_time)
                    local_peer_track_counts[index] = len(neighbors)
                    peer_track_uses_by_vehicle[index] += len(neighbors)
                observation = None
                if require_depth_cameras and depth_camera_bank is not None:
                    observation = depth_camera_bank.latest(index, now=now(), max_age_s=0.35)
                    latest_depth[index] = observation
                    if observation is not None:
                        camera_observations_used[index] += 1
                commands.append(agents[index].command(
                    now=command_time,
                    global_position=position,
                    yaw_rad=math.radians(float(telemetry.yaw_deg or 0.0)),
                    neighbors=neighbors,
                    depth_observation=observation,
                ))
            record(frame, [agent.phase for agent in agents])
            for (_spec, drone, _telemetry, _position), command in zip(frame, commands):
                drone.send(command)
            arrived_frames = arrived_frames + 1 if all(agent.phase == "arrived" for agent in agents) else 0
            if arrived_frames >= max(2, math.ceil(rate_hz * 0.5)):
                break
            if now() >= mission_deadline:
                if allow_mission_timeout:
                    mission_timed_out = True
                    break
                raise TimeoutError("five-vehicle forest mission did not rally before timeout")
            sleep(period)
    finally:
        if connected:
            for drone in drones:
                try:
                    drone.land()
                except Exception:
                    pass
        if require_depth_cameras and depth_camera_bank is not None and hasattr(depth_camera_bank, "close"):
            depth_camera_bank.close()

    if connected:
        land_deadline = now() + land_timeout_s
        while True:
            frame = read_frame()
            record(frame, ["land"] * len(frame))
            if all(position[2] <= 0.15 for *_prefix, position in frame):
                break
            if now() >= land_deadline:
                break
            sleep(period)

    summary = evaluate_px4_swarm_trial(trace, rally_targets, obstacles, target_alt_m=target_alt_m)
    summary["checks"]["mission_completed_within_timeout"] = not mission_timed_out
    summary["metrics"]["mission_timed_out"] = mission_timed_out
    summary["accepted"] = all(summary["checks"].values())
    if require_depth_cameras and depth_camera_bank is not None:
        frame_counts = [int(depth_camera_bank.frame_counts.get(index, 0)) for index in range(len(specs))]
        decode_errors = [int(depth_camera_bank.decode_errors.get(index, 0)) for index in range(len(specs))]
        summary["checks"].update({
            "all_depth_cameras_streamed": all(count > 0 for count in frame_counts),
            "all_vehicles_used_fresh_depth": all(count > 0 for count in camera_observations_used),
            "controller_used_no_obstacle_truth": all(not getattr(agent, "obstacles", ()) for agent in agents),
        })
        summary["metrics"].update({
            "depth_frames_by_vehicle": frame_counts,
            "fresh_depth_observations_used_by_vehicle": camera_observations_used,
            "depth_decode_errors_by_vehicle": decode_errors,
            "controller_truth_obstacles": sum(len(getattr(agent, "obstacles", ())) for agent in agents),
        })
        if runtime_policy is not None:
            learned_agents = [agent for agent in agents if isinstance(agent, LearnedDepthForestAgent)]
            summary["checks"].update({
                "all_vehicles_used_learned_policy": len(learned_agents) == len(specs) and all(agent.policy_calls > 0 for agent in learned_agents),
                "all_policy_inputs_used_nine_depth_rays": all(
                    observation is not None and len(observation.ray_distances_m) == 9
                    for observation in latest_depth
                ),
                "exported_policy_ran_without_torch": runtime_policy.predict_calls > 0,
            })
            summary["metrics"].update({
                "navigation_policy": "ppo-forest-v1-numpy",
                "learned_policy_calls": sum(agent.policy_calls for agent in learned_agents),
                "shared_actor_predict_calls": runtime_policy.predict_calls,
                "depth_safety_overrides": sum(agent.neural_triggers for agent in learned_agents),
                "missing_depth_holds": sum(agent.sensor_holds for agent in learned_agents),
                "precision_docking_overrides": sum(agent.docking_overrides for agent in learned_agents),
                "geofence_recovery_overrides": sum(agent.recovery_overrides for agent in learned_agents),
                "local_corridor_overrides": sum(agent.corridor_overrides for agent in learned_agents),
                "emergency_latch_overrides": sum(agent.emergency_latch_overrides for agent in learned_agents),
            })
        summary["accepted"] = all(summary["checks"].values())
    if peer_network is not None:
        radio_metrics = peer_network.metrics
        blackout_minimum_separation = math.inf
        blackout_steps = 0
        if peer_broadcast_config is not None and peer_broadcast_config.blackout_windows_s:
            by_step: dict[int, list[dict]] = {}
            for row in trace:
                elapsed = row.get("mission_elapsed_s")
                if elapsed is None or not any(start <= float(elapsed) <= end
                                              for start, end in peer_broadcast_config.blackout_windows_s):
                    continue
                by_step.setdefault(int(row["step"]), []).append(row)
            blackout_steps = len(by_step)
            for rows in by_step.values():
                for index, first in enumerate(rows):
                    for second in rows[index + 1:]:
                        blackout_minimum_separation = min(blackout_minimum_separation, math.dist(
                            (float(first["x_m"]), float(first["y_m"]), float(first["alt_m"])),
                            (float(second["x_m"]), float(second["y_m"]), float(second["alt_m"])),
                        ))
        configured_loss_exercised = (
            peer_broadcast_config is not None
            and (peer_broadcast_config.packet_loss == 0.0 or radio_metrics["random_dropped_packets"] > 0)
        )
        configured_blackout_exercised = (
            peer_broadcast_config is not None
            and (not peer_broadcast_config.blackout_windows_s or radio_metrics["blackout_dropped_packets"] > 0)
        )
        summary["checks"].update({
            "neighbor_avoidance_used_no_direct_global_positions": direct_global_neighbor_reads == 0,
            "peer_radio_delivered_local_tracks": radio_metrics["delivered_packets"] > 0,
            "peer_radio_exercised_loss_and_blackout": configured_loss_exercised and configured_blackout_exercised,
            "maintained_safe_separation_during_peer_blackout": (
                not peer_broadcast_config.blackout_windows_s
                or (blackout_steps > 0 and blackout_minimum_separation >= 0.72)
            ),
        })
        summary["metrics"].update({
            "neighbor_data_source": "local-peer-radio-cache",
            "direct_global_neighbor_reads": direct_global_neighbor_reads,
            "peer_track_uses_by_vehicle": peer_track_uses_by_vehicle,
            "peer_packets_attempted": radio_metrics["attempted_packets"],
            "peer_packets_delivered": radio_metrics["delivered_packets"],
            "peer_packets_randomly_dropped": radio_metrics["random_dropped_packets"],
            "peer_packets_dropped_in_blackout": radio_metrics["blackout_dropped_packets"],
            "peer_packets_out_of_range": radio_metrics["out_of_range_packets"],
            "peer_tracks_expired": radio_metrics["stale_tracks_expired"],
            "peer_radio_range_m": peer_broadcast_config.range_m if peer_broadcast_config else None,
            "peer_radio_latency_s": peer_broadcast_config.latency_s if peer_broadcast_config else None,
            "peer_radio_packet_loss": peer_broadcast_config.packet_loss if peer_broadcast_config else None,
            "peer_radio_blackout_windows_s": peer_broadcast_config.blackout_windows_s if peer_broadcast_config else None,
            "peer_blackout_steps": blackout_steps,
            "minimum_blackout_intervehicle_distance_m": (
                round(blackout_minimum_separation, 4) if math.isfinite(blackout_minimum_separation) else None
            ),
        })
        summary["accepted"] = all(summary["checks"].values())
    return trace, summary, [agent.neural_triggers for agent in agents]


def evaluate_px4_swarm_trial(
    trace: list[dict],
    rally_targets: list[tuple[float, float]],
    obstacles: list[tuple[float, float, float]],
    *,
    target_alt_m: float = 1.8,
    escape_x_m: float = 5.5,
    minimum_separation_m: float = 0.72,
    minimum_forest_clearance_m: float = 0.10,
    vehicle_radius_m: float = 0.25,
) -> dict:
    if not trace:
        return {"accepted": False, "checks": {}, "metrics": {"vehicles": 0}, "reason": "empty trace"}
    ids = sorted({int(row["vehicle_id"]) for row in trace})
    by_vehicle = {vehicle_id: [row for row in trace if int(row["vehicle_id"]) == vehicle_id] for vehicle_id in ids}
    reached = sum(any(row.get("alt_m") is not None and float(row["alt_m"]) >= target_alt_m - 0.2 for row in rows) for rows in by_vehicle.values())
    escaped = sum(any(row.get("x_m") is not None and float(row["x_m"]) >= escape_x_m for row in rows) for rows in by_vehicle.values())
    rallied = 0
    landed = 0
    for vehicle_id, rows in by_vehicle.items():
        target = rally_targets[vehicle_id]
        if any(
            row.get("phase") in {"rally", "arrived"}
            and row.get("x_m") is not None and row.get("y_m") is not None
            and math.hypot(float(row["x_m"]) - target[0], float(row["y_m"]) - target[1]) <= 0.6
            for row in rows
        ):
            rallied += 1
        final = rows[-1]
        if final.get("phase") == "land" and final.get("alt_m") is not None and float(final["alt_m"]) <= 0.18:
            landed += 1

    minimum_forest_clearance = math.inf
    forest_contacts = 0
    for row in trace:
        if row.get("x_m") is None or row.get("y_m") is None or row.get("alt_m") is None:
            continue
        if not 0.0 <= float(row["alt_m"]) <= 3.0:
            continue
        for x, y, radius in obstacles:
            clearance = math.hypot(float(row["x_m"]) - x, float(row["y_m"]) - y) - radius - vehicle_radius_m
            minimum_forest_clearance = min(minimum_forest_clearance, clearance)
            if clearance < 0:
                forest_contacts += 1

    minimum_intervehicle_distance = math.inf
    by_step: dict[int, list[dict]] = {}
    for row in trace:
        by_step.setdefault(int(row["step"]), []).append(row)
    for rows in by_step.values():
        positioned = [row for row in rows if all(row.get(key) is not None for key in ("x_m", "y_m", "alt_m"))]
        for i, first in enumerate(positioned):
            for second in positioned[i + 1:]:
                minimum_intervehicle_distance = min(minimum_intervehicle_distance, math.dist(
                    (float(first["x_m"]), float(first["y_m"]), float(first["alt_m"])),
                    (float(second["x_m"]), float(second["y_m"]), float(second["alt_m"])),
                ))

    expected = len(rally_targets)
    checks = {
        "five_independent_vehicles": len(ids) == expected == 5,
        "all_reached_altitude": reached == expected,
        "all_escaped": escaped == expected,
        "all_rallied": rallied == expected,
        "zero_forest_contacts": forest_contacts == 0 and minimum_forest_clearance >= 0,
        "safe_forest_clearance": minimum_forest_clearance >= minimum_forest_clearance_m,
        "safe_intervehicle_separation": minimum_intervehicle_distance >= minimum_separation_m,
        "all_landed": landed == expected,
    }
    metrics = {
        "vehicles": len(ids),
        "samples": len(trace),
        "reached_altitude": reached,
        "escaped": escaped,
        "rallied": rallied,
        "landed": landed,
        "forest_contacts": forest_contacts,
        "minimum_forest_clearance_m": round(minimum_forest_clearance, 4) if math.isfinite(minimum_forest_clearance) else None,
        "minimum_intervehicle_distance_m": round(minimum_intervehicle_distance, 4) if math.isfinite(minimum_intervehicle_distance) else None,
    }
    return {"accepted": all(checks.values()), "checks": checks, "metrics": metrics}


def render_gazebo_forest_world(
    obstacles: list[tuple[float, float, float]],
    *,
    vehicle_poses_y: tuple[float, ...] | None = None,
) -> str:
    trunks = []
    for index, (x, y, radius) in enumerate(obstacles):
        trunks.append(f"""
    <model name="trunk_{index}">
      <static>true</static>
      <pose>{x:.4f} {y:.4f} 1.5 0 0 0</pose>
      <link name="link">
        <collision name="collision"><geometry><cylinder><radius>{radius:.4f}</radius><length>3.0</length></cylinder></geometry></collision>
        <visual name="visual">
          <geometry><cylinder><radius>{radius:.4f}</radius><length>3.0</length></cylinder></geometry>
          <material><ambient>0.20 0.09 0.03 1</ambient><diffuse>0.32 0.15 0.05 1</diffuse></material>
        </visual>
      </link>
    </model>""")
    vehicles = []
    for vehicle_id, pose_y in enumerate(vehicle_poses_y or ()):
        vehicles.append(f"""
    <include>
      <uri>model://x500_depth_fly</uri>
      <name>x500_depth_fly_{vehicle_id}</name>
      <pose>0 {pose_y:.4f} 0 0 0 0</pose>
    </include>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sdf version="1.9">
  <world name="flydrones_forest">
    <physics type="ode"><max_step_size>0.004</max_step_size><real_time_factor>1.0</real_time_factor><real_time_update_rate>250</real_time_update_rate></physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene><grid>true</grid><ambient>0.35 0.40 0.35 1</ambient><background>0.55 0.70 0.72 1</background><shadows>true</shadows></scene>
    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry></collision>
        <visual name="visual"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry><material><ambient>0.12 0.28 0.12 1</ambient><diffuse>0.18 0.38 0.18 1</diffuse></material></visual>
      </link>
    </model>
    <light name="sun" type="directional"><pose>0 0 100 0 0 0</pose><cast_shadows>true</cast_shadows><direction>-0.3 0.2 -0.9</direction><diffuse>0.9 0.9 0.85 1</diffuse><specular>0.2 0.2 0.2 1</specular><attenuation><range>1000</range><constant>1</constant><linear>0</linear><quadratic>0</quadratic></attenuation></light>
    {''.join(vehicles)}
    {''.join(trunks)}
    <spherical_coordinates><surface_model>EARTH_WGS84</surface_model><world_frame_orientation>ENU</world_frame_orientation><latitude_deg>47.3979710577</latitude_deg><longitude_deg>8.5461637398</longitude_deg><elevation>0</elevation></spherical_coordinates>
  </world>
</sdf>
"""


def write_px4_swarm_artifacts(
    output_dir: str | Path,
    trace: list[dict],
    summary: dict,
    *,
    neural_triggers: list[int],
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fields = [
        "step", "t_s", "mission_elapsed_s", "vehicle_id", "system_id", "phase", "x_m", "y_m", "alt_m", "yaw_deg", "battery_pct",
        "depth_nearest_m", "depth_bearing", "depth_left_m", "depth_right_m",
        "depth_rays_m", "navigation_policy", "policy_action_speed", "policy_action_yaw", "safety_override",
        "local_peer_tracks",
    ]
    with (out / "flight.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trace)
    saved = {**summary, "neural_triggers_by_vehicle": neural_triggers, "neural_triggers": sum(neural_triggers)}
    (out / "summary.json").write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = [
        "# 五机 PX4/Gazebo 神经森林 SITL 验收报告",
        "",
        f"结论：{'通过' if summary.get('accepted') else '未通过'}",
        "",
        f"神经闪避触发: {sum(neural_triggers)}",
        "",
        "## 检查项",
        "",
        *(f"- {name}: {'通过' if passed else '失败'}" for name, passed in summary.get("checks", {}).items()),
        "",
        "## 指标",
        "",
        *(f"- {name}: {value}" for name, value in summary.get("metrics", {}).items()),
    ]
    (out / "报告.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return out
