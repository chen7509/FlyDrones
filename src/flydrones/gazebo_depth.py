"""Per-vehicle Gazebo depth-camera input for PX4 forest trials."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DepthObservation:
    captured_at: float
    nearest_distance_m: float
    obstacle_bearing: float
    left_clearance_m: float
    right_clearance_m: float
    valid_fraction: float
    ray_distances_m: tuple[float, ...] = ()


def decode_depth_image(message) -> np.ndarray:
    """Decode a Gazebo R_FLOAT32 image, including images with padded rows."""
    width = int(message.width)
    height = int(message.height)
    row_bytes = width * np.dtype(np.float32).itemsize
    step = int(message.step or row_bytes)
    if width <= 0 or height <= 0 or step < row_bytes:
        raise ValueError("invalid Gazebo depth image dimensions")
    raw = memoryview(message.data)
    if len(raw) < step * height:
        raise ValueError("truncated Gazebo depth image")
    if step == row_bytes:
        return np.frombuffer(raw[: row_bytes * height], dtype=np.float32).reshape(height, width).copy()
    rows = [np.frombuffer(raw[row * step : row * step + row_bytes], dtype=np.float32) for row in range(height)]
    return np.stack(rows)


def _near_quantile(values: np.ndarray, default: float) -> float:
    finite = values[np.isfinite(values) & (values > 0.2)]
    if finite.size == 0:
        return default
    return float(np.percentile(finite, 5.0))


def summarize_depth_frame(
    depth: np.ndarray,
    *,
    captured_at: float,
    far_distance_m: float = 19.1,
) -> DepthObservation:
    """Reduce one depth frame to the local signals used by the reflex controller.

    The middle vertical strip avoids the ground and sky. The nearest five-percent
    quantile is stable against isolated invalid pixels while still reacting to a
    tree trunk spanning several camera columns.
    """
    if depth.ndim != 2 or min(depth.shape) < 2:
        raise ValueError("depth frame must be a two-dimensional image")
    height, width = depth.shape
    top = max(0, int(height * 0.20))
    bottom = min(height, max(top + 1, int(height * 0.60)))
    band = np.asarray(depth[top:bottom], dtype=np.float32)
    valid = np.isfinite(band) & (band > 0.2) & (band <= far_distance_m)
    valid_fraction = float(np.count_nonzero(valid) / band.size)
    nearest = _near_quantile(band, far_distance_m)

    near_mask = valid & (band <= min(far_distance_m, nearest + 0.18))
    columns = np.nonzero(near_mask)[1]
    if columns.size:
        obstacle_bearing = float((np.median(columns) / max(1, width - 1)) * 2.0 - 1.0)
    else:
        obstacle_bearing = 0.0
    midpoint = width // 2
    edges = np.linspace(0, width, 10, dtype=int)
    ray_distances = tuple(
        _near_quantile(band[:, edges[index] : edges[index + 1]], far_distance_m)
        for index in range(9)
    )
    return DepthObservation(
        captured_at=float(captured_at),
        nearest_distance_m=nearest,
        obstacle_bearing=obstacle_bearing,
        left_clearance_m=_near_quantile(band[:, :midpoint], far_distance_m),
        right_clearance_m=_near_quantile(band[:, midpoint:], far_distance_m),
        valid_fraction=valid_fraction,
        ray_distances_m=ray_distances,
    )


class DepthCameraBank:
    """Subscribe to one namespaced Gazebo depth topic for each vehicle."""

    def __init__(
        self,
        vehicle_topics: Mapping[int, str],
        *,
        node_factory: Callable[[], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.topics = dict(vehicle_topics)
        self._node_factory = node_factory
        self._clock = clock
        self._node = None
        self._lock = threading.Lock()
        self._latest: dict[int, DepthObservation] = {}
        self.frame_counts = {vehicle_id: 0 for vehicle_id in self.topics}
        self.decode_errors = {vehicle_id: 0 for vehicle_id in self.topics}

    def start(self) -> None:
        if self._node is not None:
            return
        if self._node_factory is None:
            from gz.transport13 import Node

            self._node_factory = Node
        from gz.msgs10.image_pb2 import Image

        self._node = self._node_factory()
        if self._node is None:
            raise RuntimeError("Gazebo transport node is unavailable")
        for vehicle_id, topic in self.topics.items():
            callback = self._callback_for(vehicle_id)
            subscribed = self._node.subscribe(Image, topic, callback)
            if subscribed is False:
                raise RuntimeError(f"failed to subscribe to Gazebo depth topic: {topic}")

    def _callback_for(self, vehicle_id: int):
        def receive(message) -> None:
            try:
                observation = summarize_depth_frame(decode_depth_image(message), captured_at=self._clock())
            except (TypeError, ValueError):
                with self._lock:
                    self.decode_errors[vehicle_id] += 1
                return
            with self._lock:
                self._latest[vehicle_id] = observation
                self.frame_counts[vehicle_id] += 1

        return receive

    def latest(self, vehicle_id: int, *, now: float | None = None, max_age_s: float = 0.35) -> DepthObservation | None:
        timestamp = self._clock() if now is None else now
        with self._lock:
            observation = self._latest.get(vehicle_id)
        if observation is None or not math.isfinite(observation.captured_at):
            return None
        if timestamp - observation.captured_at > max_age_s:
            return None
        return observation

    def wait_until_ready(self, timeout_s: float = 10.0) -> bool:
        deadline = self._clock() + timeout_s
        while self._clock() < deadline:
            with self._lock:
                if all(self.frame_counts.get(vehicle_id, 0) > 0 for vehicle_id in self.topics):
                    return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        node = self._node
        if node is None:
            return
        for topic in self.topics.values():
            node.unsubscribe(topic)
        self._node = None
        time.sleep(0.05)


def px4_depth_camera_topics(
    *,
    world_name: str = "flydrones_forest",
    model_prefix: str = "x500_depth_fly",
    count: int = 5,
) -> dict[int, str]:
    return {
        vehicle_id: (
            f"/world/{world_name}/model/{model_prefix}_{vehicle_id}"
            "/link/camera_link/sensor/StereoOV7251/depth_image"
        )
        for vehicle_id in range(count)
    }
