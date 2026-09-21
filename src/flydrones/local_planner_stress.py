"""Deterministic randomized stress scenarios for the hybrid local planner."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from .hybrid_agent import HybridPlannerAgent
from .local_planner import LocalPlannerConfig, PlannerPeer


@dataclass(frozen=True)
class StressScenario:
    kind: str
    start: tuple[float, float, float]
    target: tuple[float, float]
    obstacle_points: tuple[tuple[float, float], ...]
    peers: tuple[PlannerPeer, ...]


@dataclass(frozen=True)
class _StressOutcome:
    accepted: bool
    kind: str
    reached_target: bool
    static_contact: bool
    peer_contact: bool
    finite_state: bool
    inside_geofence: bool
    minimum_static_clearance_m: float | None
    minimum_peer_separation_m: float | None
    steps: int


class _ForwardPolicy:
    def predict(self, _observation):
        return np.asarray((1.0, 0.0), dtype=np.float32)


def _generate_scenarios(rng: random.Random, scenario_count: int) -> list[StressScenario]:
    scenarios: list[StressScenario] = []
    kinds = ("frontal-trunk", "head-on-peer", "crossing-peer", "udp-stale-peer")
    for index in range(scenario_count):
        kind = kinds[index % len(kinds)]
        start_y = rng.uniform(-0.25, 0.25)
        start = (0.0, start_y, 1.8)
        target = (3.8 + rng.uniform(-0.15, 0.15), start_y + rng.uniform(-0.08, 0.08))
        obstacles: tuple[tuple[float, float], ...] = ()
        peers: tuple[PlannerPeer, ...] = ()

        if kind == "frontal-trunk":
            opening_side = -1.0 if rng.random() < 0.5 else 1.0
            obstacles = (
                (
                    1.35 + rng.uniform(0.0, 0.20),
                    start_y - opening_side * (0.20 + rng.uniform(0.0, 0.05)),
                ),
                (2.20 + rng.uniform(-0.10, 0.10), start_y - opening_side * 1.55),
            )
        elif kind == "head-on-peer":
            lane_side = -1.0 if rng.random() < 0.5 else 1.0
            peers = (
                PlannerPeer(
                    sender_id=10 + index,
                    position=(
                        2.65 + rng.uniform(-0.10, 0.10),
                        start_y + lane_side * rng.uniform(0.55, 0.70),
                        1.8,
                    ),
                    velocity=(-0.45 + rng.uniform(-0.04, 0.04), rng.uniform(-0.02, 0.02), 0.0),
                    age_s=0.05,
                ),
            )
        elif kind == "crossing-peer":
            side = -1.0 if rng.random() < 0.5 else 1.0
            peers = (
                PlannerPeer(
                    sender_id=10 + index,
                    position=(1.75 + rng.uniform(-0.08, 0.08), start_y + side * 1.75, 1.8),
                    velocity=(rng.uniform(-0.02, 0.02), -side * (0.65 + rng.uniform(-0.04, 0.04)), 0.0),
                    age_s=0.08,
                ),
            )
        else:
            side = -1.0 if rng.random() < 0.5 else 1.0
            peers = (
                PlannerPeer(
                    sender_id=10 + index,
                    position=(1.90 + rng.uniform(-0.08, 0.08), start_y + side * 1.90, 1.8),
                    velocity=(rng.uniform(-0.02, 0.02), -side * (0.72 + rng.uniform(-0.04, 0.04)), 0.0),
                    age_s=0.55,
                ),
            )
        scenarios.append(StressScenario(kind, start, target, obstacles, peers))
    return scenarios


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _depth_observation(
    *,
    now: float,
    position: tuple[float, float, float],
    world_heading: float,
    obstacles: tuple[tuple[float, float], ...],
    config: LocalPlannerConfig,
):
    ray_count = 9
    ray_width = config.horizontal_fov_rad / ray_count
    rays = [config.sensor_range_m] * ray_count
    for obstacle_x, obstacle_y in obstacles:
        dx = obstacle_x - position[0]
        dy = obstacle_y - position[1]
        distance = math.hypot(dx, dy)
        if distance > config.sensor_range_m:
            continue
        relative = _wrap_angle(math.atan2(dy, dx) - world_heading)
        raw_index = (relative + config.horizontal_fov_rad / 2.0) / ray_width - 0.5
        index = int(round(raw_index))
        if not 0 <= index < ray_count:
            continue
        ray_offset = -config.horizontal_fov_rad / 2.0 + (index + 0.5) * ray_width
        if abs(_wrap_angle(relative - ray_offset)) <= ray_width * 0.55:
            rays[index] = min(rays[index], max(0.05, distance))
    return SimpleNamespace(captured_at=now, ray_distances_m=tuple(rays))


def _actual_peer(peer: PlannerPeer, elapsed_s: float) -> tuple[float, float, float]:
    return tuple(peer.position[index] + peer.velocity[index] * elapsed_s for index in range(3))


def _reported_peers(scenario: StressScenario, elapsed_s: float) -> tuple[PlannerPeer, ...]:
    reported: list[PlannerPeer] = []
    for peer in scenario.peers:
        age = peer.age_s
        delayed_time = elapsed_s - age
        delayed_position = _actual_peer(peer, delayed_time)
        reported.append(
            PlannerPeer(
                sender_id=peer.sender_id,
                position=delayed_position,
                velocity=peer.velocity,
                age_s=age,
            )
        )
    return tuple(reported)


def _run_scenario(scenario: StressScenario) -> _StressOutcome:
    # Keep execution clearance above the public 0.60/0.90 m contract even
    # between discrete 20 Hz integration samples.
    config = LocalPlannerConfig(static_margin_m=0.60, peer_minimum_m=1.25)
    agent = HybridPlannerAgent(
        0,
        scenario.target,
        _ForwardPolicy(),
        config=config,
        corridor_center_y=scenario.start[1],
        deadlock_land_after_s=18.0,
        enable_local_bypass=False,
    )
    dt = 0.05
    maximum_steps = int(20.0 / dt)
    replan_every = 4
    position = list(scenario.start)
    velocity = [0.0, 0.0, 0.0]
    world_heading = math.atan2(scenario.target[1] - position[1], scenario.target[0] - position[0])
    command = None
    reached = False
    static_contact = False
    peer_contact = False
    finite_state = True
    inside_geofence = True
    minimum_static = math.inf
    minimum_peer = math.inf
    steps = 0

    for step in range(maximum_steps):
        elapsed = step * dt
        yaw_rad = _wrap_angle(math.pi / 2.0 - world_heading)
        if step % replan_every == 0 or command is None:
            observation = _depth_observation(
                now=elapsed,
                position=tuple(position),
                world_heading=world_heading,
                obstacles=scenario.obstacle_points,
                config=config,
            )
            command = agent.command(
                now=elapsed,
                global_position=tuple(position),
                velocity=tuple(velocity),
                yaw_rad=yaw_rad,
                peers=_reported_peers(scenario, elapsed),
                depth_observation=observation,
            )
        if agent.phase == "arrived":
            reached = True
            steps = step
            break

        desired_forward = command.forward * config.max_speed_mps
        desired_lateral = command.lateral * config.max_speed_mps
        desired_vx = desired_forward * math.cos(world_heading) + desired_lateral * math.sin(world_heading)
        desired_vy = desired_forward * math.sin(world_heading) - desired_lateral * math.cos(world_heading)
        delta_x = desired_vx - velocity[0]
        delta_y = desired_vy - velocity[1]
        delta_norm = math.hypot(delta_x, delta_y)
        maximum_delta = config.max_acceleration_mps2 * dt
        if delta_norm > maximum_delta:
            scale = maximum_delta / delta_norm
            delta_x *= scale
            delta_y *= scale
        velocity[0] += delta_x
        velocity[1] += delta_y
        position[0] += velocity[0] * dt
        position[1] += velocity[1] * dt
        world_heading = _wrap_angle(
            world_heading - command.yaw * config.max_yaw_rate_rad_s * dt
        )
        steps = step + 1

        finite_state = all(math.isfinite(value) for value in (*position, *velocity, world_heading))
        inside_geofence = -2.0 <= position[0] <= 6.0 and -4.0 <= position[1] <= 4.0
        for obstacle in scenario.obstacle_points:
            clearance = math.hypot(position[0] - obstacle[0], position[1] - obstacle[1])
            minimum_static = min(minimum_static, clearance)
            if clearance < 0.60 - 1e-9:
                static_contact = True
        for peer in scenario.peers:
            peer_position = _actual_peer(peer, elapsed + dt)
            separation = math.sqrt(sum((position[index] - peer_position[index]) ** 2 for index in range(3)))
            minimum_peer = min(minimum_peer, separation)
            if separation < 0.90 - 1e-9:
                peer_contact = True
        if not finite_state or not inside_geofence or static_contact or peer_contact:
            break

    accepted = reached and finite_state and inside_geofence and not static_contact and not peer_contact
    return _StressOutcome(
        accepted=accepted,
        kind=scenario.kind,
        reached_target=reached,
        static_contact=static_contact,
        peer_contact=peer_contact,
        finite_state=finite_state,
        inside_geofence=inside_geofence,
        minimum_static_clearance_m=None if math.isinf(minimum_static) else round(minimum_static, 6),
        minimum_peer_separation_m=None if math.isinf(minimum_peer) else round(minimum_peer, 6),
        steps=steps,
    )


def _aggregate_outcomes(outcomes: list[_StressOutcome]) -> dict:
    static_clearances = [
        outcome.minimum_static_clearance_m
        for outcome in outcomes
        if outcome.minimum_static_clearance_m is not None
    ]
    peer_separations = [
        outcome.minimum_peer_separation_m
        for outcome in outcomes
        if outcome.minimum_peer_separation_m is not None
    ]
    kinds = sorted({outcome.kind for outcome in outcomes})
    return {
        "scenarios": len(outcomes),
        "passed": sum(outcome.accepted for outcome in outcomes),
        "timeouts": sum(not outcome.reached_target for outcome in outcomes),
        "static_contacts": sum(outcome.static_contact for outcome in outcomes),
        "peer_contacts": sum(outcome.peer_contact for outcome in outcomes),
        "non_finite_states": sum(not outcome.finite_state for outcome in outcomes),
        "geofence_departures": sum(not outcome.inside_geofence for outcome in outcomes),
        "minimum_static_clearance_m": min(static_clearances, default=math.inf),
        "minimum_peer_separation_m": min(peer_separations, default=math.inf),
        "maximum_steps": max((outcome.steps for outcome in outcomes), default=0),
        "scenario_classes": {kind: sum(outcome.kind == kind for outcome in outcomes) for kind in kinds},
    }


def run_local_planner_stress(seed: int = 20260921, scenario_count: int = 100) -> dict:
    if scenario_count <= 0:
        raise ValueError("scenario count must be positive")
    rng = random.Random(int(seed))
    scenarios = _generate_scenarios(rng, int(scenario_count))
    outcomes = [_run_scenario(scenario) for scenario in scenarios]
    metrics = _aggregate_outcomes(outcomes)
    return {"accepted": all(outcome.accepted for outcome in outcomes), "metrics": metrics}
