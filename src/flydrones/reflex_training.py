"""Fast, interpretable training for the first two fly-like control stages.

This is a lightweight teacher policy, not a replacement for the MaleCNS
connectome. It learns seven non-negative gains while keeping the signs of the
optomotor, haltere and looming pathways fixed. The resulting policy can be
evaluated quickly, then distilled into the full connectome readout.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np

from .motor.command import FlightCommand


@dataclass(frozen=True)
class FlyObservation:
    vertical_flow: float = 0.0
    rotation: float = 0.0
    yaw_rate: float = 0.0
    loom_left: float = 0.0
    loom_right: float = 0.0
    target_bearing: float = 0.0


@dataclass(frozen=True)
class ReflexParameters:
    vertical_gain: float = 1.8
    optomotor_gain: float = 1.6
    haltere_gain: float = 0.9
    loom_turn_gain: float = 2.2
    loom_brake_gain: float = 0.9
    target_gain: float = 1.0
    cruise: float = 0.72

    NAMES: ClassVar[tuple[str, ...]] = (
        "vertical_gain",
        "optomotor_gain",
        "haltere_gain",
        "loom_turn_gain",
        "loom_brake_gain",
        "target_gain",
        "cruise",
    )
    BOUNDS: ClassVar[tuple[tuple[float, float], ...]] = (
        (0.0, 6.0),
        (0.0, 6.0),
        (0.0, 4.0),
        (0.0, 8.0),
        (0.0, 3.0),
        (0.0, 4.0),
        (0.15, 1.0),
    )

    def to_vector(self) -> np.ndarray:
        return np.asarray([getattr(self, name) for name in self.NAMES], dtype=float)

    @classmethod
    def from_vector(cls, values) -> ReflexParameters:
        raw = np.asarray(values, dtype=float)
        if raw.shape != (len(cls.NAMES),):
            raise ValueError(f"expected {len(cls.NAMES)} policy parameters, got {raw.shape}")
        clipped = [float(np.clip(value, lo, hi)) for value, (lo, hi) in zip(raw, cls.BOUNDS)]
        return cls(**dict(zip(cls.NAMES, clipped)))


class FlyReflexPolicy:
    """Biologically signed reflex pathways with trainable magnitudes."""

    def __init__(self, params: ReflexParameters | None = None):
        self.params = params or ReflexParameters()

    def act(self, observation: FlyObservation) -> FlightCommand:
        p = self.params
        looming = max(observation.loom_left, observation.loom_right)
        throttle = math.tanh(p.vertical_gain * observation.vertical_flow)
        yaw_drive = (
            p.optomotor_gain * observation.rotation
            - p.haltere_gain * observation.yaw_rate
            + p.loom_turn_gain * (observation.loom_left - observation.loom_right)
            + p.target_gain * observation.target_bearing
        )
        forward = float(np.clip(p.cruise - p.loom_brake_gain * looming, -1.0, 1.0))
        return FlightCommand(
            throttle=throttle,
            yaw=math.tanh(yaw_drive),
            forward=forward,
            note="trained fly reflex teacher",
        )


def load_reflex_policy(path: str | Path) -> FlyReflexPolicy:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != "flydrones-reflex-policy-v1":
        raise ValueError(f"unsupported reflex policy format: {payload.get('format')!r}")
    parameters = payload.get("parameters", {})
    missing = [name for name in ReflexParameters.NAMES if name not in parameters]
    if missing:
        raise ValueError(f"reflex policy is missing parameters: {', '.join(missing)}")
    return FlyReflexPolicy(ReflexParameters.from_vector([parameters[name] for name in ReflexParameters.NAMES]))


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def evaluate_stabilization(policy: FlyReflexPolicy, episodes: int = 200, seed: int = 0) -> dict[str, float]:
    """Random angular/vertical impulses with noisy vision, latency-like smoothing and wind."""
    rng = np.random.default_rng(seed)
    successes = 0
    rms_vertical: list[float] = []
    rms_yaw: list[float] = []
    dt = 0.05

    for _ in range(episodes):
        vertical_speed = float(rng.uniform(-1.2, 1.2))
        yaw_rate = float(rng.uniform(-1.8, 1.8))
        vertical_wind = float(rng.uniform(-0.12, 0.12))
        yaw_wind = float(rng.uniform(-0.18, 0.18))
        filtered_flow = 0.0
        filtered_rotation = 0.0
        tail_vertical: list[float] = []
        tail_yaw: list[float] = []

        for step in range(120):
            flow = -vertical_speed + rng.normal(0.0, 0.035)
            rotation = -yaw_rate + rng.normal(0.0, 0.035)
            filtered_flow = 0.72 * filtered_flow + 0.28 * flow
            filtered_rotation = 0.72 * filtered_rotation + 0.28 * rotation
            command = policy.act(
                FlyObservation(
                    vertical_flow=filtered_flow,
                    rotation=filtered_rotation,
                    yaw_rate=yaw_rate + rng.normal(0.0, 0.025),
                )
            )
            vertical_speed += (1.65 * command.throttle - 0.65 * vertical_speed + vertical_wind) * dt
            yaw_rate += (2.2 * command.yaw - 0.75 * yaw_rate + yaw_wind) * dt
            if step >= 60:
                tail_vertical.append(vertical_speed)
                tail_yaw.append(yaw_rate)

        vrms = math.sqrt(float(np.mean(np.square(tail_vertical))))
        yrms = math.sqrt(float(np.mean(np.square(tail_yaw))))
        rms_vertical.append(vrms)
        rms_yaw.append(yrms)
        successes += int(vrms <= 0.13 and yrms <= 0.16)

    mean_v = float(np.mean(rms_vertical))
    mean_y = float(np.mean(rms_yaw))
    success_rate = successes / max(1, episodes)
    return {
        "episodes": int(episodes),
        "success_rate": round(success_rate, 6),
        "collision_rate": 0.0,
        "minimum_clearance_m": 99.0,
        "mean_rms_vertical_speed": round(mean_v, 6),
        "mean_rms_yaw_rate": round(mean_y, 6),
        "score": round(20.0 * success_rate - 4.0 * mean_v - 3.0 * mean_y, 6),
    }


def evaluate_looming(policy: FlyReflexPolicy, episodes: int = 300, seed: int = 0) -> dict[str, float]:
    """Approach an offset obstacle, turn away on looming, then reacquire the target."""
    rng = np.random.default_rng(seed)
    successes = collisions = 0
    clearances: list[float] = []
    progress_values: list[float] = []
    dt = 0.05
    obstacle_radius = 0.28
    vehicle_radius = 0.12

    for _ in range(episodes):
        side = -1.0 if rng.random() < 0.5 else 1.0
        obstacle = np.array([0.0, side * rng.uniform(0.12, 0.42)])
        position = np.array([-3.2, rng.uniform(-0.12, 0.12)])
        target = np.array([3.4, 0.0])
        heading = float(rng.uniform(-0.08, 0.08))
        speed = 0.0
        yaw_rate = 0.0
        wind = float(rng.uniform(-0.08, 0.08))
        min_clearance = float("inf")
        collided = False

        for _step in range(220):
            to_obstacle = obstacle - position
            obstacle_distance = float(np.linalg.norm(to_obstacle))
            obstacle_bearing = _wrap(math.atan2(to_obstacle[1], to_obstacle[0]) - heading)
            ahead = max(0.0, math.cos(obstacle_bearing))
            closing = max(0.0, speed * ahead)
            proximity = float(np.clip((3.0 - obstacle_distance) / 2.65, 0.0, 1.0))
            loom = proximity * float(np.clip(0.2 + closing / 1.4, 0.0, 1.0)) if abs(obstacle_bearing) < 1.25 else 0.0
            loom *= float(rng.uniform(0.94, 1.06))
            loom_left = loom if obstacle_bearing < 0 else 0.0
            loom_right = loom if obstacle_bearing >= 0 else 0.0

            to_target = target - position
            target_bearing = _wrap(math.atan2(to_target[1], to_target[0]) - heading)
            command = policy.act(
                FlyObservation(
                    rotation=-yaw_rate + rng.normal(0.0, 0.02),
                    yaw_rate=yaw_rate + rng.normal(0.0, 0.02),
                    loom_left=loom_left,
                    loom_right=loom_right,
                    target_bearing=float(np.clip(target_bearing, -1.0, 1.0)),
                )
            )
            desired_speed = max(0.0, command.forward) * 1.8
            speed += (desired_speed - speed) * 0.22
            desired_yaw_rate = command.yaw * 1.9
            yaw_rate += (desired_yaw_rate - yaw_rate) * 0.28
            heading += yaw_rate * dt
            position += np.array([math.cos(heading), math.sin(heading)]) * speed * dt
            position[1] += wind * dt

            clearance = float(np.linalg.norm(position - obstacle) - obstacle_radius - vehicle_radius)
            min_clearance = min(min_clearance, clearance)
            if clearance <= 0:
                collided = True
                break
            if position[0] >= target[0] - 0.15 and abs(position[1]) <= 0.75:
                break

        reached = position[0] >= target[0] - 0.15 and abs(position[1]) <= 0.75
        collisions += int(collided)
        successes += int(reached and not collided and min_clearance >= 0.55)
        clearances.append(min_clearance)
        progress_values.append(float(np.clip((position[0] + 3.2) / 6.45, 0.0, 1.0)))

    success_rate = successes / max(1, episodes)
    collision_rate = collisions / max(1, episodes)
    mean_clearance = float(np.mean(clearances))
    minimum_clearance = float(np.min(clearances))
    mean_progress = float(np.mean(progress_values))
    return {
        "episodes": int(episodes),
        "success_rate": round(success_rate, 6),
        "collision_rate": round(collision_rate, 6),
        "minimum_clearance_m": round(minimum_clearance, 6),
        "mean_clearance_m": round(mean_clearance, 6),
        "mean_progress": round(mean_progress, 6),
        "score": round(30.0 * success_rate - 35.0 * collision_rate + 3.0 * mean_progress + 2.0 * min(mean_clearance, 1.5), 6),
    }


def evaluate_gap_corridor(policy: FlyReflexPolicy, episodes: int = 1000, seed: int = 0) -> dict[str, float]:
    """Pass a randomized two-post gap and follow a locally observed curved corridor."""
    rng = np.random.default_rng(seed)
    successes = collisions = 0
    clearances: list[float] = []
    progress_values: list[float] = []
    dt = 0.05
    post_radius = 0.32
    vehicle_radius = 0.12

    for _ in range(episodes):
        gap_center = float(rng.uniform(-0.55, 0.55))
        gap_width = float(rng.uniform(1.9, 2.5))
        post_offset = gap_width / 2 + post_radius
        posts = (np.array([0.0, gap_center - post_offset]), np.array([0.0, gap_center + post_offset]))
        curve_amplitude = float(rng.uniform(-0.42, 0.42))
        corridor_half_width = float(rng.uniform(1.05, 1.28))
        position = np.array([-3.8, rng.uniform(-0.35, 0.35)])
        heading = float(rng.uniform(-0.10, 0.10))
        speed = yaw_rate = 0.0
        crosswind = float(rng.uniform(-0.06, 0.06))
        min_clearance = float("inf")
        collided = False

        def corridor_center(x_position: float) -> float:
            if x_position <= 0.4:
                return gap_center
            phase = float(np.clip((x_position - 0.4) / 4.0, 0.0, 1.0))
            return (1 - phase) * gap_center + curve_amplitude * math.sin(math.pi * phase)

        for _step in range(260):
            loom_left = loom_right = 0.0
            for post in posts:
                relative = post - position
                distance = float(np.linalg.norm(relative))
                bearing = _wrap(math.atan2(relative[1], relative[0]) - heading)
                ahead = max(0.0, math.cos(bearing))
                proximity = float(np.clip((2.8 - distance) / 2.45, 0.0, 1.0))
                loom = proximity * float(np.clip(0.15 + speed * ahead / 1.4, 0.0, 1.0)) if abs(bearing) < 1.25 else 0.0
                if bearing < 0:
                    loom_left = max(loom_left, loom)
                else:
                    loom_right = max(loom_right, loom)

            if position[0] > 0.25:
                center = corridor_center(float(position[0]))
                left_clearance = position[1] - (center - corridor_half_width) - vehicle_radius
                right_clearance = (center + corridor_half_width) - position[1] - vehicle_radius
                wall_range = 0.85
                loom_left = max(loom_left, float(np.clip((wall_range - left_clearance) / wall_range, 0.0, 1.0)))
                loom_right = max(loom_right, float(np.clip((wall_range - right_clearance) / wall_range, 0.0, 1.0)))

            lookahead_x = 0.65 if position[0] < 0.25 else min(4.4, position[0] + 1.15)
            local_target = np.array([lookahead_x, corridor_center(float(lookahead_x))])
            relative_target = local_target - position
            target_bearing = _wrap(math.atan2(relative_target[1], relative_target[0]) - heading)
            command = policy.act(
                FlyObservation(
                    rotation=-yaw_rate + rng.normal(0.0, 0.018),
                    yaw_rate=yaw_rate + rng.normal(0.0, 0.018),
                    loom_left=loom_left * rng.uniform(0.95, 1.05),
                    loom_right=loom_right * rng.uniform(0.95, 1.05),
                    target_bearing=float(np.clip(target_bearing, -1.0, 1.0)),
                )
            )
            desired_speed = max(0.0, command.forward) * 1.7
            speed += (desired_speed - speed) * 0.22
            yaw_rate += (command.yaw * 1.9 - yaw_rate) * 0.28
            heading += yaw_rate * dt
            position += np.array([math.cos(heading), math.sin(heading)]) * speed * dt
            position[1] += crosswind * dt

            post_clearance = min(float(np.linalg.norm(position - post) - post_radius - vehicle_radius) for post in posts)
            if position[0] > 0.25:
                center = corridor_center(float(position[0]))
                wall_clearance = corridor_half_width - abs(position[1] - center) - vehicle_radius
            else:
                wall_clearance = float("inf")
            clearance = min(post_clearance, wall_clearance)
            min_clearance = min(min_clearance, clearance)
            if clearance <= 0:
                collided = True
                break
            if position[0] >= 4.2:
                break

        reached = position[0] >= 4.2
        collisions += int(collided)
        successes += int(reached and not collided and min_clearance >= 0.70)
        clearances.append(min_clearance)
        progress_values.append(float(np.clip((position[0] + 3.8) / 8.0, 0.0, 1.0)))

    success_rate = successes / max(1, episodes)
    collision_rate = collisions / max(1, episodes)
    mean_clearance = float(np.mean(clearances))
    minimum_clearance = float(np.min(clearances))
    mean_progress = float(np.mean(progress_values))
    return {
        "episodes": int(episodes),
        "success_rate": round(success_rate, 6),
        "collision_rate": round(collision_rate, 6),
        "minimum_clearance_m": round(minimum_clearance, 6),
        "mean_clearance_m": round(mean_clearance, 6),
        "mean_progress": round(mean_progress, 6),
        "score": round(35.0 * success_rate - 40.0 * collision_rate + 4.0 * mean_progress + 2.0 * min(mean_clearance, 1.5), 6),
    }


def train_reflex_policy(
    initial: ReflexParameters | None = None,
    generations: int = 32,
    population: int = 56,
    episodes_per_candidate: int = 24,
    seed: int = 42,
) -> tuple[FlyReflexPolicy, list[dict[str, float]]]:
    """Cross-entropy optimization over the seven interpretable pathway gains."""
    rng = np.random.default_rng(seed)
    mean = (initial or ReflexParameters()).to_vector()
    bounds = np.asarray(ReflexParameters.BOUNDS, dtype=float)
    std = (bounds[:, 1] - bounds[:, 0]) * 0.20
    elite_count = max(4, population // 5)
    history: list[dict[str, float]] = []
    best_vector = mean.copy()
    best_score = -float("inf")

    for generation in range(generations):
        candidates = rng.normal(mean, std, size=(population, mean.size))
        candidates = np.clip(candidates, bounds[:, 0], bounds[:, 1])
        scores = np.empty(population, dtype=float)
        for index, vector in enumerate(candidates):
            policy = FlyReflexPolicy(ReflexParameters.from_vector(vector))
            evaluation_seed = seed * 100_000 + generation * population + index
            stable = evaluate_stabilization(policy, episodes=max(8, episodes_per_candidate // 2), seed=evaluation_seed)
            looming = evaluate_looming(policy, episodes=episodes_per_candidate, seed=evaluation_seed + 1)
            scores[index] = stable["score"] + looming["score"]
        order = np.argsort(scores)[::-1]
        elite = candidates[order[:elite_count]]
        mean = 0.25 * mean + 0.75 * elite.mean(axis=0)
        std = np.maximum(0.03 * (bounds[:, 1] - bounds[:, 0]), 0.65 * std + 0.35 * elite.std(axis=0))
        if scores[order[0]] > best_score:
            best_score = float(scores[order[0]])
            best_vector = candidates[order[0]].copy()
        history.append(
            {
                "generation": generation,
                "best_score": round(best_score, 6),
                "generation_best_score": round(float(scores[order[0]]), 6),
                "elite_mean_score": round(float(scores[order[:elite_count]].mean()), 6),
            }
        )

    return FlyReflexPolicy(ReflexParameters.from_vector(best_vector)), history


def train_gap_corridor_policy(
    initial: FlyReflexPolicy,
    generations: int = 16,
    population: int = 40,
    episodes_per_candidate: int = 12,
    seed: int = 31415,
) -> tuple[FlyReflexPolicy, list[dict[str, float]]]:
    """Continue training the four navigation gains while preserving stabilization gains."""
    rng = np.random.default_rng(seed)
    fixed = initial.params.to_vector()[:3]
    bounds = np.asarray(ReflexParameters.BOUNDS[3:], dtype=float)
    mean = initial.params.to_vector()[3:]
    std = (bounds[:, 1] - bounds[:, 0]) * 0.14
    elite_count = max(4, population // 5)
    best_vector = mean.copy()
    best_score = -float("inf")
    history: list[dict[str, float]] = []

    for generation in range(generations):
        candidates = np.clip(rng.normal(mean, std, size=(population, mean.size)), bounds[:, 0], bounds[:, 1])
        scores = np.empty(population, dtype=float)
        for index, navigation in enumerate(candidates):
            params = ReflexParameters.from_vector(np.concatenate([fixed, navigation]))
            policy = FlyReflexPolicy(params)
            evaluation_seed = seed * 100_000 + generation * population + index
            looming = evaluate_looming(policy, episodes=max(4, episodes_per_candidate // 2), seed=evaluation_seed)
            gap = evaluate_gap_corridor(policy, episodes=episodes_per_candidate, seed=evaluation_seed + 1)
            clearance_penalty = 90.0 * max(0.0, 0.76 - gap["minimum_clearance_m"])
            loom_penalty = 40.0 * max(0.0, 0.90 - looming["minimum_clearance_m"])
            scores[index] = looming["score"] + gap["score"] - clearance_penalty - loom_penalty
        order = np.argsort(scores)[::-1]
        elite = candidates[order[:elite_count]]
        mean = 0.20 * mean + 0.80 * elite.mean(axis=0)
        std = np.maximum(0.025 * (bounds[:, 1] - bounds[:, 0]), 0.62 * std + 0.38 * elite.std(axis=0))
        if scores[order[0]] > best_score:
            best_score = float(scores[order[0]])
            best_vector = candidates[order[0]].copy()
        history.append(
            {
                "generation": generation,
                "best_score": round(best_score, 6),
                "generation_best_score": round(float(scores[order[0]]), 6),
                "elite_mean_score": round(float(scores[order[:elite_count]].mean()), 6),
            }
        )

    parameters = ReflexParameters.from_vector(np.concatenate([fixed, best_vector]))
    return FlyReflexPolicy(parameters), history


def save_training_artifacts(
    output_dir: str | Path,
    policy: FlyReflexPolicy,
    metrics: dict,
    history: list[dict],
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "flydrones-reflex-policy-v1",
        "role": "fast teacher for connectome readout distillation",
        "parameters": asdict(policy.params),
        "metrics": metrics,
    }
    (out / "reflex-policy.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if history:
        fields = list(history[0])
        with (out / "training-history.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(history)
    else:
        (out / "training-history.csv").write_text("generation,best_score\n", encoding="utf-8")

    stable = metrics.get("stabilization", {})
    looming = metrics.get("looming", {})
    gap = metrics.get("gap_and_corridor", {})
    report = [
        "# 果蝇反射教师训练报告",
        "",
        "该策略固定了果蝇式通路方向，只训练七个通路增益。它用于快速训练和向完整连接组蒸馏。",
        "",
        "## 视动稳定",
        "",
        f"- 回合：{stable.get('episodes')}",
        f"- 成功率：{stable.get('success_rate')}",
        f"- 平均垂直速度 RMS：{stable.get('mean_rms_vertical_speed')}",
        f"- 平均偏航速度 RMS：{stable.get('mean_rms_yaw_rate')}",
        "",
        "## 逼近避让",
        "",
        f"- 回合：{looming.get('episodes')}",
        f"- 成功率：{looming.get('success_rate')}",
        f"- 碰撞率：{looming.get('collision_rate')}",
        f"- 最小净空：{looming.get('minimum_clearance_m')} m",
        f"- 平均净空：{looming.get('mean_clearance_m')} m",
    ]
    if gap:
        report.extend(
            [
                "",
                "## 缝隙与走廊",
                "",
                f"- 回合：{gap.get('episodes')}",
                f"- 成功率：{gap.get('success_rate')}",
                f"- 碰撞率：{gap.get('collision_rate')}",
                f"- 最小净空：{gap.get('minimum_clearance_m')} m",
                f"- 平均净空：{gap.get('mean_clearance_m')} m",
            ]
        )
    report.extend([
        "",
        "## 参数",
        "",
    ])
    report.extend(f"- {name}: {value:.6f}" for name, value in asdict(policy.params).items())
    (out / "报告.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return out
