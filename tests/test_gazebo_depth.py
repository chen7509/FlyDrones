from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from flydrones.gazebo_depth import (
    DepthCameraBank,
    DepthObservation,
    decode_depth_image,
    px4_depth_camera_topics,
    summarize_depth_frame,
)


def test_decode_depth_image_reads_float32_rows_and_ignores_padding():
    pixels = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
    padded = b"".join(row.tobytes() + b"PAD!" for row in pixels)
    message = SimpleNamespace(width=3, height=2, step=16, pixel_format_type=13, data=padded)

    decoded = decode_depth_image(message)

    np.testing.assert_array_equal(decoded, pixels)


def test_summarize_depth_frame_finds_obstacle_and_clearer_side():
    depth = np.full((60, 100), np.inf, dtype=np.float32)
    depth[12:36, 28:45] = 0.85
    depth[12:36, 45:52] = 1.30

    observation = summarize_depth_frame(depth, captured_at=7.5)

    assert observation.captured_at == 7.5
    assert 0.80 <= observation.nearest_distance_m <= 0.90
    assert observation.obstacle_bearing < 0
    assert observation.right_clearance_m > observation.left_clearance_m
    assert observation.valid_fraction > 0.05
    assert len(observation.ray_distances_m) == 9
    assert min(observation.ray_distances_m) < 1.0
    assert observation.ray_distances_m[-1] > observation.ray_distances_m[3]


def test_depth_camera_bank_keeps_each_vehicle_topic_and_rejects_stale_frames():
    bank = DepthCameraBank(
        vehicle_topics={
            0: "/world/forest/model/x500_depth_fly_0/link/camera_link/sensor/StereoOV7251/depth_image",
            1: "/world/forest/model/x500_depth_fly_1/link/camera_link/sensor/StereoOV7251/depth_image",
        },
        node_factory=lambda: None,
    )
    bank._latest[0] = DepthObservation(4.8, 1.0, -0.2, 0.9, 4.0, 0.2)
    bank._latest[1] = DepthObservation(3.0, 0.8, 0.1, 2.0, 1.0, 0.2)

    assert bank.latest(0, now=5.0, max_age_s=0.3) is bank._latest[0]
    assert bank.latest(1, now=5.0, max_age_s=0.3) is None
    assert bank.topics[0].endswith("x500_depth_fly_0/link/camera_link/sensor/StereoOV7251/depth_image")


def test_px4_depth_camera_topics_are_unique_per_vehicle():
    topics = px4_depth_camera_topics()

    assert len(topics) == 5
    assert len(set(topics.values())) == 5
    assert topics[4].endswith("x500_depth_fly_4/link/camera_link/sensor/StereoOV7251/depth_image")
