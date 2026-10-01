"""Shared SI-unit controller boundary (ENU, counterclockwise yaw).

The current backend supplies model-truth-derived odometry and camera pose.
This interface must not be described as a real VIO estimate.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Observation:
    sim_ns: int
    frame_ns: int
    rgb: np.ndarray
    depth_m: np.ndarray
    camera_pose: tuple[float, ...]
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    yaw: float
    yaw_rate: float
    goal: tuple[float, float, float]


@dataclass(frozen=True)
class Command:
    velocity_enu: tuple[float, float, float]
    yaw_rate: float


@dataclass(frozen=True)
class Decision:
    command: Command
    elapsed_wall_s: float
    evidence: dict


class Controller(Protocol):
    def reset(self, seed: int) -> None: ...
    def step(self, obs: Observation) -> Decision: ...
    def close(self) -> None: ...
