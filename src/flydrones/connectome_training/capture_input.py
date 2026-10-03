"""Fail-closed provenance gate for future PX4/Gazebo student data capture.

This gate validates supplied evidence; it does not produce EKF2 estimates or
certify a live estimator, calibration, or EGO container by itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from flydrones.benchmark.contract import Observation
from flydrones.connectome_training.corpus_config import CorpusConfig

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_FRAME_AGE_NS = 100_000_000
_MAX_ESTIMATOR_AGE_NS = 100_000_000
_MAX_CAMERA_POSE_OFFSET_NS = 50_000_000
_ODOMETRY_SOURCE = "px4_ekf2"
_CAMERA_POSE_SOURCE = "px4_ekf2_calibrated_camera"


@dataclass(frozen=True)
class CaptureInputEvidence:
    odometry_source: str
    camera_pose_source: str
    estimator_sim_ns: int
    camera_pose_sim_ns: int
    xy_valid: bool
    z_valid: bool
    heading_valid: bool
    calibration_verified: bool
    calibration_sha256: str
    teacher_commit: str
    teacher_image_id: str
    teacher_image_inspected: bool


def _finite_vector(value: object, size: int, label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalid") from exc
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{label} invalid")
    return array


def validate_capture_input(
    backend: object,
    observation: Observation,
    evidence: CaptureInputEvidence,
    config: CorpusConfig,
) -> None:
    """Reject truth, stale, uncalibrated or unverified teacher inputs.

    The live producer must supply the evidence from actual PX4 and image
    streams; a synthetic passing test is not a flight or fusion result.
    """
    if not isinstance(observation, Observation) or not isinstance(evidence, CaptureInputEvidence):
        raise ValueError("capture observation or evidence invalid")
    if (getattr(backend, "odometry_source", None) != evidence.odometry_source
            or getattr(backend, "camera_pose_source", None) != evidence.camera_pose_source):
        raise ValueError("backend source does not match capture evidence")
    if (evidence.odometry_source != _ODOMETRY_SOURCE
            or evidence.camera_pose_source != _CAMERA_POSE_SOURCE):
        raise ValueError("capture requires deployment-visible PX4 estimator source")
    if (type(observation.sim_ns) is not int or observation.sim_ns <= 0
            or type(observation.frame_ns) is not int
            or not 0 <= observation.sim_ns - observation.frame_ns <= _MAX_FRAME_AGE_NS):
        raise ValueError("camera frame is stale or out of order")
    if (type(evidence.estimator_sim_ns) is not int
            or not 0 <= observation.sim_ns - evidence.estimator_sim_ns <= _MAX_ESTIMATOR_AGE_NS):
        raise ValueError("PX4 estimator sample is stale or in the future")
    if (type(evidence.camera_pose_sim_ns) is not int
            or not 0 <= evidence.camera_pose_sim_ns <= observation.sim_ns
            or abs(evidence.camera_pose_sim_ns - observation.frame_ns)
            > _MAX_CAMERA_POSE_OFFSET_NS):
        raise ValueError("camera pose and frame timestamps are misaligned")
    if not all(type(value) is bool and value for value in (
            evidence.xy_valid, evidence.z_valid, evidence.heading_valid)):
        raise ValueError("PX4 estimator position or heading invalid")
    if (evidence.calibration_verified is not True
            or not isinstance(evidence.calibration_sha256, str)
            or _SHA256.fullmatch(evidence.calibration_sha256) is None):
        raise ValueError("camera extrinsic calibration is not verified")
    if (evidence.teacher_commit != config.teacher_commit
            or evidence.teacher_image_id != config.teacher_image_id
            or evidence.teacher_image_inspected is not True):
        raise ValueError("teacher identity is not inspected and pinned")
    if (not isinstance(observation.rgb, np.ndarray) or observation.rgb.dtype != np.uint8
            or observation.rgb.ndim != 3 or observation.rgb.shape[2] != 3
            or min(observation.rgb.shape[:2]) < 1
            or not isinstance(observation.depth_m, np.ndarray)
            or observation.depth_m.shape != observation.rgb.shape[:2]
            or not np.issubdtype(observation.depth_m.dtype, np.floating)
            or not np.all(np.isfinite(observation.depth_m))
            or np.any(observation.depth_m < 0)):
        raise ValueError("RGB-D depth frame invalid")
    quaternion = _finite_vector(observation.camera_pose, 7, "camera pose")[3:]
    if not .95 <= float(np.linalg.norm(quaternion)) <= 1.05:
        raise ValueError("camera pose quaternion invalid")
    for label, value in (
            ("position", observation.position),
            ("velocity", observation.velocity),
            ("goal", observation.goal)):
        _finite_vector(value, 3, f"observation {label}")
    _finite_vector((observation.yaw, observation.yaw_rate), 2, "observation attitude")
