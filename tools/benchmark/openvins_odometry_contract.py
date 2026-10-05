"""Offline pinned-PX4 body-tangent ODOMETRY contract. No transport or fusion authorization."""

from __future__ import annotations

import importlib.metadata

import numpy as np
from scipy.spatial.transform import Rotation

PROFILE = "px4-d6f12ad-body-tangent"
S = np.diag([1.0, -1.0, -1.0])
FLOAT_MAX = np.finfo(np.float32).max


def _array(value, shape):
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in "iuf":
        raise ValueError("invalid numeric shape/type")
    result = raw.astype(float)
    if not np.isfinite(result).all() or np.max(np.abs(result)) > FLOAT_MAX:
        raise ValueError("nonfinite or unrepresentable numeric value")
    return result


def convert_native(state13, covariance12, *, profile=PROFILE):
    """Identity FRD IMU/body extrinsic only; arbitrary-heading down-positive local frame.

    Pose covariance uses position_LOCAL_FRD and BODY rotation-vector error,
    as required by the pinned PX4 receiver, NOT generic Euler-angle variance.
    Native upstream approximate covariance quality is not improved by conversion.
    """
    if profile != PROFILE:
        raise ValueError("unverified consumer or mounting profile")
    state = _array(state13, (13,))
    cov = _array(covariance12, (12, 12))
    norm = np.linalg.norm(state[:4])
    if abs(norm - 1) > 1e-5:
        raise ValueError("invalid quaternion norm")
    if not np.allclose(cov, cov.T, atol=1e-8, rtol=0) or np.linalg.eigvalsh(cov).min() < -1e-8:
        raise ValueError("covariance must be symmetric PSD")
    # Hamilton(q_xyzw) = JPL(q_xyzw).T; hence S * R_GI.T.
    r_bl = S @ Rotation.from_quat(state[:4] / norm).as_matrix()
    q = Rotation.from_matrix(r_bl).as_quat()
    # SciPy1.10 supports as_quat() but not canonical=. Choose sign explicitly:
    # positive w, breaking the exact w=0 tie by the first nonzero x/y/z.
    first = next(value for value in q[[3, 0, 1, 2]] if value != 0)
    if first < 0:
        q = -q
    jac = np.zeros((12, 12))
    jac[:3, 3:6] = S
    jac[3:6, :3] = np.eye(3)
    jac[6:, 6:] = np.eye(6)
    transformed = jac @ cov @ jac.T
    return {
        "profile": profile,
        "position": (S @ state[4:7]).tolist(),
        "q_wxyz": [float(q[3]), *q[:3].tolist()],
        "velocity_body": state[7:10].tolist(),
        "angular_velocity_body": state[10:13].tolist(),
        "covariance12": transformed.tolist(),
        "pose_covariance": transformed[:6, :6][np.triu_indices(6)].tolist(),
        "velocity_covariance": transformed[6:, 6:][np.triu_indices(6)].tolist(),
    }


class ShadowSession:
    """Validate caller-supplied clock/reset evidence for file-only diagnostic records.

    Does not detect real resets, synchronize clocks or infer arrival from IMU time.
    New clock/estimator sessions require a new instance, never silently reset history.
    """

    def __init__(self, session_id, clock_id, *, wire_offset_ns, max_age_ns):
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or not isinstance(clock_id, str)
            or not clock_id.strip()
            or type(wire_offset_ns) is not int
            or type(max_age_ns) is not int
            or max_age_ns <= 0
        ):
            raise ValueError("invalid explicit session contract")
        self.session_id, self.clock_id = session_id, clock_id
        self.wire_offset_ns, self.max_age_ns = wire_offset_ns, max_age_ns
        self.last_wire_us = None
        self.last_sample_ns = None
        self.last_reset_total = None

    def accept(self, row, *, session_id, clock_id, observed_ns, reset_total, quality):
        if (
            session_id != self.session_id
            or clock_id != self.clock_id
            or type(observed_ns) is not int
            or type(reset_total) is not int
            or reset_total < 0
            or type(quality) is not int
            or not -1 <= quality <= 100
        ):
            raise ValueError("missing or invalid clock/session/reset/quality evidence")
        if (
            type(row.get("target_ns")) is not int
            or row["target_ns"] <= 0
            or row.get("success") is not True
            or row.get("internal_initialized") is not True
            or type(row.get("public_initialized")) is not bool
        ):
            raise ValueError("unavailable or invalid native prediction")
        sample = row["target_ns"]
        wire_us = (sample + self.wire_offset_ns) // 1000
        if (
            not 0 <= observed_ns - sample <= self.max_age_ns
            or not 0 < wire_us < 2**64
            or (self.last_wire_us is not None and wire_us <= self.last_wire_us)
            or (self.last_sample_ns is not None and sample <= self.last_sample_ns)
            or (self.last_reset_total is not None and reset_total - self.last_reset_total not in (0, 1))
        ):
            raise ValueError("stale, duplicate, overflowed or regressed clock/reset")
        g = convert_native(row["state13"], row["covariance12"])
        fields = {
            "time_usec": wire_us,
            "frame_id": 20,
            "child_frame_id": 12,
            "x": g["position"][0],
            "y": g["position"][1],
            "z": g["position"][2],
            "q": g["q_wxyz"],
            "vx": g["velocity_body"][0],
            "vy": g["velocity_body"][1],
            "vz": g["velocity_body"][2],
            "rollspeed": g["angular_velocity_body"][0],
            "pitchspeed": g["angular_velocity_body"][1],
            "yawspeed": g["angular_velocity_body"][2],
            "pose_covariance": g["pose_covariance"],
            "velocity_covariance": g["velocity_covariance"],
            "reset_counter": reset_total % 256,
            "estimator_type": 3,
            "quality": quality,
        }
        reasons = ["offline_only", "covariance_uncalibrated"]
        if not row["public_initialized"]:
            reasons.append("public_not_initialized")
        if quality <= 0:
            reasons.append("quality_unknown" if quality == 0 else "quality_failed")
        self.last_wire_us, self.last_sample_ns, self.last_reset_total = wire_us, sample, reset_total
        return {"profile": PROFILE, "fields": fields, "reasons": reasons, "eligible_for_px4_fusion": False}


def encode_shadow(record):
    """Return MAVLink2 bytes in memory using the verified package; never send them."""
    if record.get("profile") != PROFILE or record.get("eligible_for_px4_fusion") is not False:
        raise ValueError("only explicit offline records supported")
    fields = record["fields"]
    expected = {
        "time_usec",
        "frame_id",
        "child_frame_id",
        "x",
        "y",
        "z",
        "q",
        "vx",
        "vy",
        "vz",
        "rollspeed",
        "pitchspeed",
        "yawspeed",
        "pose_covariance",
        "velocity_covariance",
        "reset_counter",
        "estimator_type",
        "quality",
    }
    bounds = {
        "time_usec": (1, 2**64 - 1),
        "frame_id": (20, 20),
        "child_frame_id": (12, 12),
        "reset_counter": (0, 255),
        "estimator_type": (3, 3),
        "quality": (-1, 100),
    }
    if set(fields) != expected or any(type(fields[k]) is not int or not lo <= fields[k] <= hi for k, (lo, hi) in bounds.items()):
        raise ValueError("invalid or changed packet fields")
    _array([fields[k] for k in ["x", "y", "z", "vx", "vy", "vz", "rollspeed", "pitchspeed", "yawspeed"]], (9,))
    if abs(np.linalg.norm(_array(fields["q"], (4,))) - 1) > 1e-5:
        raise ValueError("invalid packet quaternion")
    for key in ["pose_covariance", "velocity_covariance"]:
        upper = _array(fields[key], (21,))
        matrix = np.zeros((6, 6))
        matrix[np.triu_indices(6)] = upper
        matrix = matrix + np.triu(matrix, 1).T
        if np.linalg.eigvalsh(matrix).min() < -1e-8:
            raise ValueError("invalid packet covariance")
    if importlib.metadata.version("pymavlink") != "2.4.49":
        raise ValueError("unverified pymavlink version")
    from pymavlink.dialects.v20 import common

    message = common.MAVLink_odometry_message(**fields)
    encoder = common.MAVLink(None, srcSystem=1, srcComponent=191)
    return message.pack(encoder)


def convert_frozen_records(rows):
    """Geometry for already audited native records; missing runtime evidence stays missing."""
    converted = []
    for row in rows:
        reasons = [
            "offline_only",
            "covariance_uncalibrated",
            "live_clock_and_arrival_missing",
            "reset_evidence_missing",
            "quality_evidence_missing",
        ]
        if type(row.get("success")) is not bool or type(row.get("public_initialized")) is not bool:
            raise ValueError("invalid audited record flags")
        if not row["public_initialized"]:
            reasons.append("public_not_initialized")
        geometry = None
        if row["success"]:
            geometry = convert_native(row["state13"], row["covariance12"])
        else:
            if row["state13"] is not None or row["covariance12"] is not None:
                raise ValueError("failed propagation has nonnull state")
            reasons.append("propagation_unavailable")
        converted.append(
            {
                "target_ns": row["target_ns"],
                "geometry": geometry,
                "reasons": reasons,
                "wire_packet": None,
                "eligible_for_px4_fusion": False,
            }
        )
    return converted
