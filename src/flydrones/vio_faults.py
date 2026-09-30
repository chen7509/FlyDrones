"""Deterministic perturbations for the Gazebo-to-PX4 visual odometry stream."""

from __future__ import annotations

import heapq
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

PROFILE_SCHEMA = "flydrones-vio-fault-v1"


def _vector(value: tuple[float, ...], name: str) -> tuple[float, float, float]:
    if len(value) != 3 or not all(math.isfinite(float(part)) for part in value):
        raise ValueError(f"{name} must contain three finite numbers")
    return tuple(float(part) for part in value)


@dataclass(frozen=True)
class FaultProfile:
    vehicle_id: int
    seed: int
    delay_ms: float = 0.0
    dropout_start_s: float = 0.0
    dropout_duration_s: float = 0.0
    drop_probability: float = 0.0
    drift_mps: tuple[float, float, float] = (0.0, 0.0, 0.0)
    false_pose_start_s: float = 0.0
    false_pose_duration_s: float = 0.0
    false_pose_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_queue: int = 512
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PROFILE_SCHEMA:
            raise ValueError(f"unsupported fault profile schema: {self.schema}")
        if type(self.vehicle_id) is not int or not 0 <= self.vehicle_id <= 4:
            raise ValueError("vehicle_id must be an integer from 0 to 4")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        for name in ("delay_ms", "dropout_start_s", "dropout_duration_s", "false_pose_start_s", "false_pose_duration_s"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not math.isfinite(float(self.drop_probability)) or not 0.0 <= self.drop_probability <= 1.0:
            raise ValueError("drop_probability must be between zero and one")
        if type(self.max_queue) is not int or self.max_queue < 1:
            raise ValueError("max_queue must be a positive integer")
        object.__setattr__(self, "drift_mps", _vector(self.drift_mps, "drift_mps"))
        object.__setattr__(self, "false_pose_offset_m", _vector(self.false_pose_offset_m, "false_pose_offset_m"))

    @classmethod
    def from_json(cls, path: str | Path) -> FaultProfile:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("fault profile must be a JSON object")
        return cls(**data)


@dataclass(frozen=True)
class FaultDecision:
    reason: str
    active: bool
    due_at: float | None
    offset_m: tuple[float, float, float]


@dataclass(frozen=True)
class QueuedOdometry:
    model_name: str
    payload: bytes
    source_stamp_ns: int
    received_at: float
    due_at: float
    offset_m: tuple[float, float, float]
    active: bool


class FaultStream:
    """Apply one seeded profile and retain at most ``max_queue`` samples."""

    def __init__(self, profile: FaultProfile) -> None:
        self.profile = profile
        self.random = random.Random(profile.seed)
        self._queue: list[tuple[float, int, QueuedOdometry]] = []
        self._sequence = 0

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def enqueue(
        self,
        model_name: str,
        payload: bytes,
        source_stamp_ns: int,
        *,
        now: float,
        activation_at: float | None,
    ) -> FaultDecision:
        if not math.isfinite(now) or activation_at is not None and (not math.isfinite(activation_at) or activation_at > now):
            raise ValueError("invalid monotonic fault timing")
        active = model_name == f"x500_depth_fly_{self.profile.vehicle_id}" and activation_at is not None
        elapsed = max(0.0, now - activation_at) if active else 0.0
        offset = (0.0, 0.0, 0.0)
        if active:
            if self.profile.dropout_start_s <= elapsed < self.profile.dropout_start_s + self.profile.dropout_duration_s:
                return FaultDecision("scheduled-dropout", True, None, offset)
            if self.random.random() < self.profile.drop_probability:
                return FaultDecision("random-dropout", True, None, offset)
            drift = self.profile.drift_mps
            offset = tuple(component * elapsed for component in drift)
            if self.profile.false_pose_start_s <= elapsed < self.profile.false_pose_start_s + self.profile.false_pose_duration_s:
                offset = tuple(offset[i] + self.profile.false_pose_offset_m[i] for i in range(3))
        if len(self._queue) >= self.profile.max_queue:
            return FaultDecision("queue-full", active, None, offset)
        due_at = now + (self.profile.delay_ms / 1000.0 if active else 0.0)
        item = QueuedOdometry(model_name, payload, source_stamp_ns, now, due_at, offset, active)
        heapq.heappush(self._queue, (due_at, self._sequence, item))
        self._sequence += 1
        return FaultDecision("queued", active, due_at, offset)

    def pop_ready(self, now: float) -> list[QueuedOdometry]:
        if not math.isfinite(now):
            raise ValueError("now must be finite")
        ready: list[QueuedOdometry] = []
        while self._queue and self._queue[0][0] <= now + 1e-9:
            ready.append(heapq.heappop(self._queue)[2])
        return ready


def route_model_from_frame(frame_id: str, model_names: set[str]) -> str | None:
    """Reject cross-vehicle and malformed frame IDs before publishing."""
    if not frame_id.endswith("/odom"):
        return None
    model_name = frame_id[:-5]
    return model_name if model_name in model_names else None


def read_activation(path: str | Path, *, vehicle_id: int, now: float) -> float | None:
    """Read a marker from the vehicle that disabled GNSS fusion."""
    try:
        marker = json.loads(Path(path).read_text(encoding="utf-8"))
        value = float(marker["monotonic_s"])
        if marker["vehicle_id"] == vehicle_id and math.isfinite(value) and value <= now:
            return value
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def write_activation(path: str | Path, *, vehicle_id: int, monotonic_s: float) -> None:
    """Atomically publish the successful GNSS-fault time to the relay."""
    if type(vehicle_id) is not int or not math.isfinite(monotonic_s):
        raise ValueError("invalid activation marker")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps({"vehicle_id": vehicle_id, "monotonic_s": monotonic_s}) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
