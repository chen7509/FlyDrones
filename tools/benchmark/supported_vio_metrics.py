"""Offline first-pose gauge diagnostics; no estimator or fusion output path."""

import math

import numpy as np
from scipy.spatial.transform import Rotation

FLU_FRD = np.diag([1.0, -1.0, -1.0])


def vector(value, size):
    if len(value) != size or any(type(x) is bool or not isinstance(x, (int, float, np.number)) for x in value):
        raise ValueError("invalid numeric vector")
    a = np.asarray(value, dtype=float)
    if a.shape != (size,) or not np.isfinite(a).all() or np.max(np.abs(a)) > 1e10:
        raise ValueError("nonfinite or unsupported magnitude")
    return a


def orientation(value):
    q = vector(value, 4)
    if abs(np.linalg.norm(q) - 1) > 1e-5:
        raise ValueError("non-unit quaternion")
    return Rotation.from_quat(q).as_matrix()


def native(value):
    # Pinned camera producer emits q,p,v,b_g,b_a, not fast-state13.
    s = vector(value, 16)
    return orientation(s[:4]), s[4:7], s[7:10]


def physical(value):
    return (orientation(value["quaternion_xyzw"]) @ FLU_FRD, vector(value["position"], 3), vector(value["velocity_world"], 3))


class FixedGauge:
    """Camera IMU-state global velocity, NOT fast predictor body-frame velocity.

    Numerical JPL q_GtoI interpreted as Hamilton yields its transpose, I-to-G.
    Full initial rotation/translation is fixed for offline comparison only.
    """

    def __init__(self, native_origin, truth_origin):
        rn, pn, _ = native(native_origin)
        rt, pt, _ = physical(truth_origin)
        self.rotation = rt @ rn.T
        self.native_origin, self.truth_origin = pn.copy(), pt.copy()
        self.gravity_axis_error_deg = math.degrees(math.acos(float(np.clip(self.rotation[2, 2], -1, 1))))

    def compare(self, native_state, truth_state):
        rn, pn, vn = native(native_state)
        rt, pt, vt = physical(truth_state)
        dn, dt = pn - self.native_origin, pt - self.truth_origin
        aligned = self.rotation @ dn + self.truth_origin
        return {
            "position_aligned": aligned.tolist(),
            "position_error_m": float(np.linalg.norm(aligned - pt)),
            "velocity_error_m_s": float(np.linalg.norm(self.rotation @ vn - vt)),
            "attitude_error_deg": float(np.degrees(Rotation.from_matrix(rt.T @ self.rotation @ rn).magnitude())),
            "displacement_error_lower_bound_m": float(abs(np.linalg.norm(dn) - np.linalg.norm(dt))),
            "eligible_for_px4_fusion": False,
        }
