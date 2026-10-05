"""Offline diagnosis only: truth never enters an estimator or control output."""

from __future__ import annotations

import hashlib
import math

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_online_shadow import encode_packet, validate_ack


def _stamp(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("invalid timestamp")
    return value


def _vector(value, size=3):
    try:
        valid = len(value) == size and all(type(v) in (float, int) and math.isfinite(v) for v in value)
    except (TypeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError("invalid finite vector")
    return np.array(value, dtype=float)


def _ordered(rows, key):
    stamps = [_stamp(row[key]) for row in rows]
    if not stamps or any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("empty/duplicate/regressed source")
    return dict(zip(stamps, rows))


def audit_inertial_window(imu, truth, start_ns, end_ns, *, gravity):
    """Exact4ms endpoint closure, no interpolation or calibration fit.

    Gyroscope is not integrated here: physical rotations only transform sampled
    specific force for a source diagnostic, never for an estimated trajectory.
    """
    start_ns, end_ns = _stamp(start_ns), _stamp(end_ns)
    if end_ns <= start_ns or (end_ns - start_ns) % 4_000_000:
        raise ValueError("invalid window bounds")
    source = _ordered([r for r in imu if r["kind"] == "imu"], "sample_ns")
    physical = _ordered(truth, "sim_ns")
    stamps = list(range(start_ns, end_ns + 1, 4_000_000))
    expected = set(stamps)
    for rows in [source, physical]:
        if {s for s in rows if start_ns <= s <= end_ns} != expected:
            raise ValueError("missing endpoint or nonuniform sample grid")
    gravity = _vector(gravity)
    measured, physics_accel, velocity = [], [], []
    for stamp in stamps:
        t = physical[stamp]
        q = _vector(t["quaternion_xyzw"], 4)
        if abs(np.linalg.norm(q) - 1) > 1e-6:
            raise ValueError("nonunit physical quaternion")
        measured.append(Rotation.from_quat(q).apply(_vector(source[stamp]["accel_flu"])) + gravity)
        physics_accel.append(_vector(t["accel_world"]))
        velocity.append(_vector(t["velocity_world"]))
    measured, physics_accel = np.array(measured), np.array(physics_accel)
    dt = np.diff(np.array(stamps, dtype=np.int64)).astype(float) * 1e-9

    def integrate(values):
        return np.sum((values[:-1] + values[1:]) * 0.5 * dt[:, None], axis=0)

    actual = velocity[-1] - velocity[0]
    sensor_dv, physics_dv = integrate(measured), integrate(physics_accel)
    return dict(
        start_ns=start_ns,
        end_ns=end_ns,
        samples=len(stamps),
        physical_endpoint_delta_velocity_m_s=actual.tolist(),
        sensor_integrated_delta_velocity_m_s=sensor_dv.tolist(),
        physics_accel_integrated_delta_velocity_m_s=physics_dv.tolist(),
        sensor_velocity_closure_m_s=(sensor_dv - actual).tolist(),
        physics_velocity_closure_m_s=(physics_dv - actual).tolist(),
        sensor_velocity_closure_norm_m_s=float(np.linalg.norm(sensor_dv - actual)),
        physics_velocity_closure_norm_m_s=float(np.linalg.norm(physics_dv - actual)),
        sensor_minus_physics_integral_m_s=(sensor_dv - physics_dv).tolist(),
        root_cause_proven=False,
        fusion_eligible=False,
        scope="sampled acceleration versus endpoint velocity; does not resolve unobserved1ms motion",
    )


def audit_imu_delivery(raw, requests, acks):
    """Prove recorded input/packet identity; not a new native parser execution."""
    source = _ordered([r for r in raw if r["kind"] == "imu"], "sample_ns")
    if len(requests) != len(acks):
        raise ValueError("incomplete request acknowledgements")
    matched = []
    for sequence, (request, ack) in enumerate(zip(requests, acks)):
        if type(request["sequence"]) is not int or request["sequence"] != sequence:
            raise ValueError("request sequence mismatch")
        action = request["action"]
        if action["kind"] not in ("camera", "imu"):
            raise ValueError("unexpected request kind")
        kind = "I" if action["kind"] == "imu" else "C"
        validate_ack(
            ack, sequence=sequence, kind=kind, dispatch_ns=request["dispatch_ns"], acknowledged_ns=ack["acknowledged_ns"]
        )
        if _stamp(ack["sample_ns"]) != _stamp(action["sample_ns"]) or ack["source_arrival_ns"] != action["source_arrival_ns"]:
            raise ValueError("acknowledged sample/arrival mismatch")
        if ack["dispatch_ns"] != request["dispatch_ns"]:
            raise ValueError("acknowledged dispatch mismatch")
        if kind == "C":
            continue  # Image bytes are outside this IMU-specific audit.
        stamp = action["sample_ns"]
        if stamp not in source:
            raise ValueError("IMU request without raw sample")
        row = source[stamp]
        if action["source_arrival_ns"] != row["arrival_monotonic_ns"]:
            raise ValueError("raw arrival differs from request")
        for original, packed in [("gyro_flu", "wm"), ("accel_flu", "am")]:
            if not np.array_equal(_vector(row[original]) * [1, -1, -1], _vector(action[packed])):
                raise ValueError("raw FLU to native FRD mismatch")
        packet = encode_packet(action, sequence=sequence, dispatch_ns=request["dispatch_ns"])
        if len(packet) != request["bytes"] or hashlib.sha256(packet).hexdigest() != request["packet_sha256"]:
            raise ValueError("packet bytes/hash mismatch")
        matched.append(stamp)
    if matched != list(source):
        raise ValueError("raw IMU missing, duplicated or reordered in native requests")
    return dict(
        matched_imu_packets=len(matched),
        all_recorded_requests=len(requests),
        scope="recorded packet identity and acknowledgements; no new native execution",
        fusion_eligible=False,
    )
