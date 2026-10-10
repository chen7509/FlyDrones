"""Pure pinned OpenVINS IMU-state transform for the PX4 ODOMETRY contract.

This module does not serialize, publish, open a socket, inspect PX4 parameters,
or decide health.  Its covariance input is the already bounded 15x15 matrix
owned by :mod:`openvins_health_contract`.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

PROFILE = "px4-d6f12ad-body-tangent"
S = np.diag([1.0, -1.0, -1.0])
FLOAT_MAX = float(np.finfo(np.float32).max)


def _array(value: object, shape: tuple[int, ...]) -> np.ndarray:
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in "iuf":
        raise ValueError("invalid numeric shape/type")
    result = raw.astype(float)
    if not np.isfinite(result).all() or float(np.max(np.abs(result))) > FLOAT_MAX:
        raise ValueError("nonfinite or float32-unrepresentable value")
    return result


def _canonical_wxyz(rotation: np.ndarray) -> list[float]:
    xyzw = Rotation.from_matrix(rotation).as_quat()
    first = next(value for value in xyzw[[3, 0, 1, 2]] if value != 0)
    if first < 0:
        xyzw = -xyzw
    return [float(xyzw[3]), *xyzw[:3].tolist()]


def _skew(value: np.ndarray) -> np.ndarray:
    x, y, z = value
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def convert_imu15(state16: object, bounded_covariance15: object, *, profile: str = PROFILE) -> dict:
    """Transform one pinned OpenVINS IMU state without making it publishable.

    ``state16`` is ``(q_GtoI_xyzw, p_IinG, v_IinG, bg, ba)``.  OpenVINS uses
    JPL quaternion coefficients; interpreting them as Hamilton yields
    ``R_GI.T``.  The covariance error order is
    ``(theta_I, p_G, v_G, bg, ba)``.  The returned covariance order is
    ``(p_LOCAL_FRD, theta_BODY_FRD, v_BODY_FRD)``.
    """

    if profile != PROFILE:
        raise ValueError("unverified consumer or mounting profile")
    state = _array(state16, (16,))
    covariance = _array(bounded_covariance15, (15, 15))
    quaternion_norm = float(np.linalg.norm(state[:4]))
    if abs(quaternion_norm - 1.0) > 1e-5:
        raise ValueError("invalid quaternion norm")

    covariance_scale = max(1.0, float(np.max(np.abs(covariance))))
    if not np.allclose(covariance, covariance.T, atol=1e-10 * covariance_scale, rtol=0):
        raise ValueError("covariance must be symmetric PSD")
    covariance = (covariance + covariance.T) * 0.5
    if float(np.linalg.eigvalsh(covariance)[0]) < -1e-12 * covariance_scale:
        raise ValueError("covariance must be symmetric PSD")

    # Hamilton(q_xyzw) = JPL(q_xyzw).T.
    r_gi = Rotation.from_quat(state[:4] / quaternion_norm).as_matrix().T
    r_body_to_local_frd = S @ r_gi.T
    position_local_frd = S @ state[4:7]
    velocity_body_frd = r_gi @ state[7:10]

    jacobian = np.zeros((9, 15))
    jacobian[0:3, 3:6] = S
    jacobian[3:6, 0:3] = np.eye(3)
    jacobian[6:9, 0:3] = _skew(velocity_body_frd)
    jacobian[6:9, 6:9] = r_gi
    transformed = jacobian @ covariance @ jacobian.T

    for value in (position_local_frd, velocity_body_frd, jacobian, transformed):
        if not np.isfinite(value).all() or float(np.max(np.abs(value))) > FLOAT_MAX:
            raise ValueError("transformed value is not float32-representable")
    transformed_scale = max(1.0, float(np.max(np.abs(transformed))))
    if not np.allclose(transformed, transformed.T, atol=1e-10 * transformed_scale, rtol=0):
        raise ValueError("transformed covariance is not symmetric")
    transformed = (transformed + transformed.T) * 0.5
    if float(np.linalg.eigvalsh(transformed)[0]) < -1e-10 * transformed_scale:
        raise ValueError("transformed covariance is not PSD")

    diagonal = np.diag(transformed)
    return {
        "profile": profile,
        "position_local_frd": position_local_frd.tolist(),
        "q_body_to_local_frd_wxyz": _canonical_wxyz(r_body_to_local_frd),
        "velocity_body_frd": velocity_body_frd.tolist(),
        "jacobian9x15": jacobian.tolist(),
        "covariance9x9": transformed.tolist(),
        "position_variance": diagonal[0:3].tolist(),
        "attitude_variance_body_tangent": diagonal[3:6].tolist(),
        "velocity_variance_body": diagonal[6:9].tolist(),
    }
