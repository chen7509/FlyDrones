"""Causal PX4 odometry geometry without source, calibration or capture grants.

The caller must eventually bind these records to an owned DDS subscriber and
independently qualify the camera, clock, estimator and goal frame. This module
never writes a student observation or calls the recorder.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, replace
from math import atan2

import numpy as np
from scipy.spatial.transform import Rotation

_TOPIC = "/fmu/out/vehicle_odometry"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_NS = np.iinfo(np.int64).max
_MAX_US = _MAX_NS // 1000
_MAX_AGE_US = 100_000
_MAX_RECEIPT_AGE_NS = 100_000_000
_MAX_HISTORY = 256
_NED_TO_ENU = np.array(((0., 1., 0.), (1., 0., 0.), (0., 0., -1.)))


@dataclass(frozen=True)
class VehicleOdometryEvent:
    topic: str
    session_id: str
    instance: int
    sample_us: int
    publication_us: int
    receipt_monotonic_ns: int
    pose_frame: int
    velocity_frame: int
    position_ned_m: tuple[float, float, float]
    q_body_to_ned_wxyz: tuple[float, float, float, float]
    velocity_ned_m_s: tuple[float, float, float]
    omega_body_frd_rad_s: tuple[float, float, float]
    position_variance_m2: tuple[float, float, float]
    orientation_variance_rad2: tuple[float, float, float]
    velocity_variance_m2_s2: tuple[float, float, float]
    reset_counter: int
    quality: int


@dataclass(frozen=True)
class CameraExtrinsic:
    position_body_frd_m: tuple[float, float, float]
    q_camera_to_body_wxyz: tuple[float, float, float, float]
    artifact_sha256: str


@dataclass(frozen=True)
class CameraStamp:
    sample_us: int
    receipt_monotonic_ns: int


@dataclass(frozen=True)
class OdometryCameraCandidate:
    event: VehicleOdometryEvent
    camera: CameraStamp
    extrinsic_sha256: str
    position_enu_m: tuple[float, float, float]
    velocity_enu_m_s: tuple[float, float, float]
    camera_pose_enu_xyzw: tuple[float, ...]
    yaw_enu_rad: float
    yaw_rate_enu_rad_s: float
    eligible_for_live_capture: bool = False
    missing_qualification: tuple[str, ...] = (
        "dds_process_and_topic_identity", "primary_ekf2_health", "clock_epoch",
        "calibration_not_qualified", "goal_reset_policy", "ego_teacher_process",
    )


def _integer(value: object, name: str, *, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a bounded integer")
    return value


def _vector(value: object, size: int, name: str, *, nonnegative: bool = False) -> tuple[float, ...]:
    try:
        raw = np.asarray(value)
        if raw.shape != (size,) or raw.dtype.kind not in "iuf":
            raise ValueError(name)
        vector = raw.astype(np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} invalid") from exc
    if (not np.isfinite(vector).all()
            or np.any(np.abs(vector) > np.finfo(np.float32).max)
            or (nonnegative and np.any(vector < 0))):
        raise ValueError(f"{name} invalid")
    return tuple(float(v) for v in vector)


def _quaternion(value: object, name: str) -> tuple[float, float, float, float]:
    vector = np.asarray(_vector(value, 4, name))
    norm = float(np.linalg.norm(vector))
    if not .95 <= norm <= 1.05:
        raise ValueError(f"{name} norm invalid")
    # Retain the source coefficients; scipy normalizes a separate geometry view.
    return tuple(float(v) for v in vector)


def _rotation(q_wxyz: tuple[float, float, float, float]) -> Rotation:
    return Rotation.from_quat((q_wxyz[1], q_wxyz[2], q_wxyz[3], q_wxyz[0]))


def _event(value: VehicleOdometryEvent) -> VehicleOdometryEvent:
    if not isinstance(value, VehicleOdometryEvent):
        raise ValueError("PX4 odometry event missing")
    if value.topic != _TOPIC or type(value.session_id) is not str or not value.session_id:
        raise ValueError("PX4 odometry source invalid")
    _integer(value.instance, "PX4 instance", maximum=255)
    _integer(value.sample_us, "PX4 sample", maximum=_MAX_US, minimum=1)
    _integer(value.publication_us, "PX4 publication", maximum=_MAX_US, minimum=1)
    _integer(value.receipt_monotonic_ns, "PX4 receipt", maximum=_MAX_NS, minimum=1)
    if value.sample_us > value.publication_us:
        raise ValueError("PX4 sample after publication")
    if value.pose_frame != 1 or type(value.pose_frame) is not int:
        raise ValueError("PX4 pose frame is not NED")
    if value.velocity_frame != 1 or type(value.velocity_frame) is not int:
        raise ValueError("PX4 velocity frame is not NED")
    _integer(value.reset_counter, "PX4 reset", maximum=255)
    if type(value.quality) is not int or value.quality != 0:
        raise ValueError("PX4 EKF2 unused quality field unexpected")
    return replace(
        value,
        position_ned_m=_vector(value.position_ned_m, 3, "PX4 position"),
        q_body_to_ned_wxyz=_quaternion(value.q_body_to_ned_wxyz, "PX4 attitude"),
        velocity_ned_m_s=_vector(value.velocity_ned_m_s, 3, "PX4 velocity"),
        omega_body_frd_rad_s=_vector(value.omega_body_frd_rad_s, 3, "PX4 angular velocity"),
        position_variance_m2=_vector(value.position_variance_m2, 3, "PX4 position variance", nonnegative=True),
        orientation_variance_rad2=_vector(value.orientation_variance_rad2, 3, "PX4 orientation variance", nonnegative=True),
        velocity_variance_m2_s2=_vector(value.velocity_variance_m2_s2, 3, "PX4 velocity variance", nonnegative=True),
    )


def _extrinsic(value: CameraExtrinsic) -> CameraExtrinsic:
    if not isinstance(value, CameraExtrinsic) or type(value.artifact_sha256) is not str \
            or _SHA256.fullmatch(value.artifact_sha256) is None:
        raise ValueError("camera extrinsic artifact identity invalid")
    return replace(
        value,
        position_body_frd_m=_vector(value.position_body_frd_m, 3, "camera translation"),
        q_camera_to_body_wxyz=_quaternion(value.q_camera_to_body_wxyz, "camera rotation"),
    )


class Px4OdometryCausalAdapter:
    """Single-session, fail-closed odometry buffer for future DDS callbacks."""

    def __init__(self, extrinsic: CameraExtrinsic):
        self.extrinsic = _extrinsic(extrinsic)
        self._events: deque[VehicleOdometryEvent] = deque(maxlen=_MAX_HISTORY)
        self._last_camera: CameraStamp | None = None
        self.failure_reason: str | None = None

    def push(self, value: VehicleOdometryEvent) -> None:
        if self.failure_reason is not None:
            raise ValueError(f"PX4 source latched: {self.failure_reason}")
        try:
            event = _event(value)
            if self._events:
                previous = self._events[-1]
                if (event.session_id, event.instance) != (previous.session_id, previous.instance):
                    raise ValueError("PX4 session or instance changed")
                if event.reset_counter != previous.reset_counter:
                    raise ValueError("PX4 coordinate reset unresolved")
                if (event.sample_us <= previous.sample_us
                        or event.publication_us <= previous.publication_us
                        or event.receipt_monotonic_ns <= previous.receipt_monotonic_ns):
                    raise ValueError("PX4 source time regressed")
                if event.sample_us - previous.sample_us > _MAX_AGE_US:
                    raise ValueError("PX4 source sample gap")
        except ValueError as exc:
            self.failure_reason = str(exc)
            raise
        self._events.append(event)

    def at_camera(self, camera: CameraStamp) -> OdometryCameraCandidate:
        if self.failure_reason is not None:
            raise ValueError(f"PX4 source latched: {self.failure_reason}")
        if not isinstance(camera, CameraStamp):
            raise ValueError("camera timestamp missing")
        _integer(camera.sample_us, "camera sample", maximum=_MAX_US, minimum=1)
        _integer(camera.receipt_monotonic_ns, "camera receipt", maximum=_MAX_NS, minimum=1)
        if (self._last_camera is not None
                and (camera.sample_us <= self._last_camera.sample_us
                     or camera.receipt_monotonic_ns <= self._last_camera.receipt_monotonic_ns)):
            self.failure_reason = "camera time regressed"
            raise ValueError(self.failure_reason)
        self._last_camera = camera
        event = next((row for row in reversed(self._events)
                      if row.sample_us <= camera.sample_us
                      and row.publication_us <= camera.sample_us
                      and row.receipt_monotonic_ns <= camera.receipt_monotonic_ns), None)
        if event is None:
            raise ValueError("no causal PX4 state for camera")
        if (camera.sample_us - event.sample_us > _MAX_AGE_US
                or camera.receipt_monotonic_ns - event.receipt_monotonic_ns > _MAX_RECEIPT_AGE_NS):
            self.failure_reason = "PX4 state stale at camera"
            raise ValueError(self.failure_reason)
        body = _rotation(event.q_body_to_ned_wxyz).as_matrix()
        optical = _rotation(self.extrinsic.q_camera_to_body_wxyz).as_matrix()
        world_body = _NED_TO_ENU @ body
        forward = world_body[:2, 0]
        denominator = float(forward @ forward)
        if denominator < .01:
            raise ValueError("yaw rate singular near vertical body axis")
        body_omega = np.asarray(event.omega_body_frd_rad_s)
        forward_dot = world_body @ np.array((0., body_omega[2], -body_omega[1]))
        yaw_rate = (forward[0] * forward_dot[1] - forward[1] * forward_dot[0]) / denominator
        camera_position = _NED_TO_ENU @ (
            np.asarray(event.position_ned_m) + body @ np.asarray(self.extrinsic.position_body_frd_m)
        )
        camera_q = Rotation.from_matrix(world_body @ optical).as_quat()
        return OdometryCameraCandidate(
            event=event,
            camera=camera,
            extrinsic_sha256=self.extrinsic.artifact_sha256,
            position_enu_m=tuple(float(v) for v in _NED_TO_ENU @ np.asarray(event.position_ned_m)),
            velocity_enu_m_s=tuple(float(v) for v in _NED_TO_ENU @ np.asarray(event.velocity_ned_m_s)),
            camera_pose_enu_xyzw=tuple(float(v) for v in (*camera_position, *camera_q)),
            yaw_enu_rad=atan2(forward[1], forward[0]),
            yaw_rate_enu_rad_s=float(yaw_rate),
        )
