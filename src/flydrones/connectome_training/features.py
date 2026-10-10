from __future__ import annotations

import math

import numpy as np
import torch

from .dataset import SequenceFrame, TrainingSequence

FEATURE_NAMES = (
    "depth_left",
    "depth_center",
    "depth_right",
    "luminance",
    "velocity_x",
    "velocity_y",
    "velocity_z",
    "yaw_rate",
    "goal_body_x",
    "goal_body_y",
    "goal_z",
    "goal_distance",
)
MASKED_FEATURE_NAMES = (
    *FEATURE_NAMES[:3],
    "depth_valid_left",
    "depth_valid_center",
    "depth_valid_right",
    *FEATURE_NAMES[3:],
)


def feature_profile_for_names(names: tuple[str, ...]) -> str:
    if names == FEATURE_NAMES:
        return "legacy-v1"
    if names == MASKED_FEATURE_NAMES:
        return "depth-mask-v3"
    raise ValueError("unsupported input feature order")


def frame_features(frame: SequenceFrame, *, profile: str = "legacy-v1") -> np.ndarray:
    if profile not in {"legacy-v1", "depth-mask-v3"}:
        raise ValueError("unsupported feature profile")
    if profile == "legacy-v1" and frame.depth_valid is not None:
        raise ValueError("masked depth feature profile not implemented")
    if profile == "depth-mask-v3" and frame.depth_valid is None:
        raise ValueError("depth-mask-v3 requires depth_valid")
    if profile == "depth-mask-v3" and (
            not isinstance(frame.depth_m, np.ndarray)
            or frame.depth_m.dtype != np.float32):
        raise ValueError("masked depth_m requires a float32 array")
    depth = np.asarray(frame.depth_m, np.float32)
    rgb = np.asarray(frame.rgb)
    if depth.ndim != 2 or depth.shape[1] < 3:
        raise ValueError("depth_m must be a 2D image with at least three columns")
    if rgb.ndim != 3 or rgb.shape[:2] != depth.shape or rgb.shape[2] != 3:
        raise ValueError("rgb and depth_m image shapes do not match")
    coverage = []
    if profile == "depth-mask-v3":
        mask = np.asarray(frame.depth_valid)
        if (mask.dtype != np.bool_ or mask.shape != depth.shape
                or np.any(np.isinf(depth)) or np.any(depth <= 0)
                or not np.array_equal(mask, np.isfinite(depth) & (depth > 0))
                or rgb.dtype != np.uint8):
            raise ValueError("masked depth_m or depth_valid mask invalid")
        if not np.any(mask):
            raise ValueError("masked depth has no valid pixel")
    elif not np.isfinite(depth).all() or np.any(depth <= 0):
        raise ValueError("depth_m must contain positive finite values")
    position = np.asarray(frame.position_enu, np.float32)
    velocity = np.asarray(frame.velocity_enu, np.float32)
    goal = np.asarray(frame.goal_enu, np.float32)
    if position.shape != (3,) or velocity.shape != (3,) or goal.shape != (3,):
        raise ValueError("position, velocity and goal must be three-vectors")
    scalars = np.asarray([frame.yaw, frame.yaw_rate], np.float32)
    if not np.isfinite(np.concatenate([position, velocity, goal, scalars])).all():
        raise ValueError("frame state contains non-finite values")

    depth_sectors = np.array_split(depth, 3, axis=1)
    if profile == "depth-mask-v3":
        mask_sectors = np.array_split(mask, 3, axis=1)
        inverse_depth = [
            (float(np.clip(1.0 / np.median(sector[valid]), 0.0, 1.0))
             if np.any(valid) else 0.0)
            for sector, valid in zip(depth_sectors, mask_sectors, strict=True)
        ]
        coverage = [float(np.mean(valid)) for valid in mask_sectors]
    else:
        inverse_depth = [
            float(np.clip(1.0 / np.median(sector), 0.0, 1.0))
            for sector in depth_sectors
        ]
    luminance = float(np.asarray(rgb, np.float32).mean() / 255.0)
    velocity_scaled = np.clip(velocity / 5.0, -1.0, 1.0)
    yaw_rate = float(np.clip(frame.yaw_rate / math.pi, -1.0, 1.0))
    delta = goal - position
    cosine, sine = math.cos(frame.yaw), math.sin(frame.yaw)
    goal_body_x = cosine * delta[0] + sine * delta[1]
    goal_body_y = -sine * delta[0] + cosine * delta[1]
    goal_distance = float(np.linalg.norm(delta))
    goal_scaled = np.clip(
        np.asarray([goal_body_x, goal_body_y, delta[2]], np.float32) / 10.0,
        -1.0,
        1.0,
    )
    return np.asarray(
        [
            *inverse_depth,
            *coverage,
            luminance,
            *velocity_scaled.tolist(),
            yaw_rate,
            *goal_scaled.tolist(),
            np.clip(goal_distance / 20.0, 0.0, 1.0),
        ],
        np.float32,
    )


def sequence_tensors(
    sequence: TrainingSequence,
    *,
    profile: str = "legacy-v1",
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    if not sequence.frames or len(sequence.frames) != len(sequence.targets):
        raise ValueError("sequence frames and targets must have the same non-zero length")
    features = np.stack([frame_features(frame, profile=profile) for frame in sequence.frames])
    commands = np.stack(
        [
            np.asarray(
                [*target.velocity_enu, target.yaw_rate], dtype=np.float32
            )
            for target in sequence.targets
        ]
    )
    clearance = np.asarray(
        [target.minimum_clearance_m for target in sequence.targets], np.float32
    )
    if commands.shape != (len(sequence.targets), 4):
        raise ValueError("teacher commands must contain velocity_enu and yaw_rate")
    if not np.isfinite(commands).all() or not np.isfinite(clearance).all():
        raise ValueError("teacher labels contain non-finite values")
    return (
        torch.from_numpy(features).unsqueeze(0),
        torch.from_numpy(commands).unsqueeze(0),
        torch.from_numpy(clearance).unsqueeze(0),
    )
