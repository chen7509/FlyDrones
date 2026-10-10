"""Pure, bounded input gate for the pinned EGO ROS bridge.

Valid syntax is not live PX4/camera provenance or teacher-reference causality.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Callable

import numpy as np

OBSERVATION_FIELDS = frozenset({
    "sim_ns", "frame_ns", "rgb", "depth_m", "camera_pose",
    "position", "velocity", "yaw", "yaw_rate", "goal",
})
MAX_PACKET_BYTES = 8_000_000
MAX_FRAME_AGE_NS = 100_000_000
MAX_TIMESTAMP_NS = 2**63 - 1


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate observation field")
        value[key] = item
    return value


def _nonfinite_token(token: str) -> None:
    raise ValueError("nonfinite observation JSON token: " + token)


def _timestamp(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_NS:
        raise ValueError("invalid " + label)
    return value


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError("invalid " + label)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid " + label) from exc
    if not math.isfinite(number):
        raise ValueError("invalid " + label)
    return number


def _vector(value: object, size: int, label: str) -> list[float]:
    if type(value) is not list or len(value) != size:
        raise ValueError("invalid " + label)
    return [_number(item, label) for item in value]


def _image(value: object, shape: tuple[int, ...], dtype: np.dtype, label: str) -> np.ndarray:
    if type(value) is not dict or value.keys() != {"shape", "data"}:
        raise ValueError("invalid " + label + " encoding")
    actual_shape = value["shape"]
    if (type(actual_shape) is not list or len(actual_shape) != len(shape)
            or any(type(size) is not int or size != expected
                   for size, expected in zip(actual_shape, shape))):
        raise ValueError("invalid " + label + " shape")
    encoded = value["data"]
    expected_bytes = math.prod(shape) * dtype.itemsize
    expected_chars = 4 * ((expected_bytes + 2) // 3)
    if type(encoded) is not str or len(encoded) != expected_chars:
        raise ValueError("invalid " + label + " length")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid " + label + " base64") from exc
    if len(raw) != expected_bytes:
        raise ValueError("invalid " + label + " length")
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


def decode_observation(payload: bytes) -> dict:
    """Decode exactly one deployment-visible observation without ROS side effects."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_PACKET_BYTES:
        raise ValueError("invalid observation packet length")
    try:
        data = json.loads(payload, object_pairs_hook=_unique_pairs,
                          parse_constant=_nonfinite_token)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid observation JSON") from exc
    if type(data) is not dict or data.keys() != OBSERVATION_FIELDS:
        raise ValueError("unexpected observation fields")

    sim_ns = _timestamp(data["sim_ns"], "sim time")
    frame_ns = _timestamp(data["frame_ns"], "camera time")
    if frame_ns > sim_ns or sim_ns - frame_ns > MAX_FRAME_AGE_NS:
        raise ValueError("camera frame is future or stale")
    pose = _vector(data["camera_pose"], 7, "camera pose")
    q_norm = math.sqrt(sum(value * value for value in pose[3:]))
    if abs(q_norm - 1.) > 1e-3:
        raise ValueError("invalid camera quaternion")
    for key in ("position", "velocity", "goal"):
        data[key] = _vector(data[key], 3, key)
    for key in ("yaw", "yaw_rate"):
        data[key] = _number(data[key], key)
    data["camera_pose"] = pose
    data["rgb"] = _image(data["rgb"], (120, 160, 3), np.dtype("u1"), "RGB")
    depth = _image(data["depth_m"], (120, 160), np.dtype("<f4"), "depth")
    finite = np.isfinite(depth)
    if np.any(np.isinf(depth)) or np.any(finite & (depth <= 0)) or not np.any(finite):
        raise ValueError("invalid depth values")
    data["depth_m"] = depth
    return data


class ObservationSequence:
    """One-client monotonic times; repeated 10 Hz frames may accompany newer state."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last_sim_ns = -1
        self.last_frame_ns = -1

    def accept(self, observation: dict) -> None:
        sim_ns, frame_ns = observation["sim_ns"], observation["frame_ns"]
        if sim_ns <= self.last_sim_ns or frame_ns < self.last_frame_ns:
            raise ValueError("observation time regressed or repeated")
        self.last_sim_ns = sim_ns
        self.last_frame_ns = frame_ns


def handle_observation_packet(
    payload: bytes, sequence: ObservationSequence, publish: Callable[[dict], None],
) -> dict:
    """Only publish after the complete packet and temporal sequence pass."""
    observation = decode_observation(payload)
    sequence.accept(observation)
    publish(observation)
    return observation
