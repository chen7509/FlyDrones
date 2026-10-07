"""Contract and held-out audit for unique 50 Hz OpenVINS fast predictions."""

from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_ekf2_transform import FLOAT_MAX, PROFILE, S, _canonical_wxyz
from tools.benchmark.openvins_health_contract import CovarianceProfile

COMPONENTS = (
    "attitude_x",
    "attitude_y",
    "attitude_z",
    "position_x",
    "position_y",
    "position_z",
    "velocity_body_x",
    "velocity_body_y",
    "velocity_body_z",
)
SAMPLE_FIELDS = {
    "target_ns",
    "public_initialized",
    "visual_age_ns",
    "imu_boundary_age_ns",
    "error_attitude_position_velocity",
    "bounded_covariance12",
    "fusion_eligible",
}
RUN_FIELDS = {
    "status",
    "source_health_qualified",
    "native_health_qualified",
    "trajectory_accuracy_qualified",
    "samples",
}


def _array(value: object, shape: tuple[int, ...], name: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in "iuf":
        raise ValueError(f"invalid {name}")
    result = raw.astype(float)
    if not np.all(np.isfinite(result)) or float(np.max(np.abs(result))) > FLOAT_MAX:
        raise ValueError(f"invalid {name}")
    return result


def _bounded_fast_covariance(value: object) -> np.ndarray:
    covariance = _array(value, (12, 12), "fast covariance")
    scale = max(1.0, float(np.max(np.abs(covariance))))
    if not np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-10 * scale):
        raise ValueError("invalid fast covariance")
    covariance = (covariance + covariance.T) * 0.5
    if float(np.linalg.eigvalsh(covariance)[0]) < -1e-12 * scale:
        raise ValueError("invalid fast covariance")
    profile = CovarianceProfile()
    for indices, floor in (
        (range(0, 3), profile.attitude_variance_floor),
        (range(3, 6), profile.position_variance_floor),
        (range(6, 9), profile.velocity_variance_floor),
    ):
        for index in indices:
            covariance[index, index] = max(float(covariance[index, index]), floor)
    if float(np.linalg.eigvalsh(covariance)[0]) < -1e-10 * max(1.0, float(np.max(np.abs(covariance)))):
        raise ValueError("bounded fast covariance is not PSD")
    return covariance


def transform_fast12(state13: object, covariance12: object) -> dict:
    """Transform `(q_GtoI,p_G,v_I,omega_I)` and its native 12-state covariance."""

    state = _array(state13, (13,), "fast state")
    norm = float(np.linalg.norm(state[:4]))
    if abs(norm - 1.0) > 1e-5:
        raise ValueError("invalid fast quaternion")
    covariance = _bounded_fast_covariance(covariance12)
    r_gi = Rotation.from_quat(state[:4] / norm).as_matrix().T
    position = S @ state[4:7]
    rotation = S @ r_gi.T
    velocity = state[7:10].copy()
    angular = state[10:13].copy()
    jacobian = np.zeros((9, 12))
    jacobian[0:3, 3:6] = S
    jacobian[3:6, 0:3] = np.eye(3)
    jacobian[6:9, 6:9] = np.eye(3)
    transformed = jacobian @ covariance @ jacobian.T
    for value in (position, rotation, velocity, angular, jacobian, transformed):
        if not np.all(np.isfinite(value)) or float(np.max(np.abs(value))) > FLOAT_MAX:
            raise ValueError("invalid transformed fast value")
    return {
        "schema": "openvins-ekf2-fast-transform-v1",
        "profile": PROFILE,
        "native_covariance_profile": "openvins-fast12-gate-floor-v1",
        "position_local_frd": position.tolist(),
        "q_body_to_local_frd_wxyz": _canonical_wxyz(rotation),
        "velocity_body_frd": velocity.tolist(),
        "angular_velocity_body_frd_diagnostic_only": angular.tolist(),
        "bounded_covariance12": covariance.tolist(),
        "jacobian9x12": jacobian.tolist(),
        "covariance9x9": transformed.tolist(),
        "fusion_eligible": False,
    }


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_fast_manifest(held_out_run_ids: list[str]) -> dict:
    if (
        not isinstance(held_out_run_ids, list)
        or not held_out_run_ids
        or len(set(held_out_run_ids)) != len(held_out_run_ids)
        or any(not isinstance(value, str) or not value or any(c.isspace() for c in value) for value in held_out_run_ids)
    ):
        raise ValueError("invalid fast held-out run identities")
    profile = {
        "name": "openvins-fast12-gate-floor-v1",
        "base_covariance_profile": "px4-d6f12ad-gate-floor-v1",
        "target_rate_hz": 50,
        "maximum_visual_age_ns": 100_000_000,
        "maximum_imu_boundary_age_ns": 4_000_000,
        "profile_selected_before_held_out_runs": True,
        "hardware_calibrated": False,
    }
    return {
        "schema": "openvins-ekf2-fast-cohort-manifest-v1",
        "profile": profile,
        "profile_sha256": _canonical_sha(profile),
        "held_out_run_ids": list(held_out_run_ids),
        "minimum_component_coverage": 0.99,
        "maximum_consecutive_violations": 4,
        "truth_scope": "offline_scoring_only",
        "camera_covariance_qualification_inherited": False,
        "fusion_eligible": False,
    }


def _typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _sample_flags(row: object) -> np.ndarray:
    if not isinstance(row, dict) or set(row) != SAMPLE_FIELDS:
        raise ValueError("invalid fast cohort sample")
    if (
        type(row["target_ns"]) is not int
        or row["target_ns"] <= 0
        or row["public_initialized"] is not True
        or type(row["visual_age_ns"]) is not int
        or not 0 < row["visual_age_ns"] <= 100_000_000
        or type(row["imu_boundary_age_ns"]) is not int
        or not 0 < row["imu_boundary_age_ns"] <= 4_000_000
        or row["fusion_eligible"] is not False
    ):
        raise ValueError("invalid fast cohort timing/health")
    error = np.abs(_array(row["error_attitude_position_velocity"], (9,), "fast cohort error"))
    covariance = _bounded_fast_covariance(row["bounded_covariance12"])
    return error <= 3.0 * np.sqrt(np.maximum(np.diag(covariance)[:9], 0.0))


def audit_fast_cohort(manifest: object, run_evidence: object) -> dict:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("held_out_run_ids"), list):
        raise ValueError("invalid fast cohort manifest")
    expected = build_fast_manifest(manifest["held_out_run_ids"])
    if not _typed_equal(manifest, expected):
        raise ValueError("fast cohort manifest drift")
    run_ids = manifest["held_out_run_ids"]
    if not isinstance(run_evidence, dict) or set(run_evidence) != set(run_ids):
        raise ValueError("fast cohort run identity mismatch")
    passed = np.zeros(9, dtype=np.int64)
    total = np.zeros(9, dtype=np.int64)
    maximum_consecutive = 0
    reasons: list[str] = []
    run_results = []
    for run_id in run_ids:
        run = run_evidence[run_id]
        if not isinstance(run, dict) or set(run) != RUN_FIELDS or not isinstance(run["samples"], list):
            raise ValueError("invalid fast run evidence")
        run_reasons = []
        if run["status"] != "capture_completed" or not run["samples"]:
            run_reasons.append("run_failed")
        for name in ("source_health_qualified", "native_health_qualified", "trajectory_accuracy_qualified"):
            if type(run[name]) is not bool:
                raise ValueError("invalid fast run qualification")
            if not run[name]:
                run_reasons.append(name + "_failed")
        consecutive = np.zeros(9, dtype=np.int64)
        last_target = None
        for row in run["samples"]:
            flags = _sample_flags(row)
            if last_target is not None and row["target_ns"] - last_target != 20_000_000:
                raise ValueError("fast target grid is not unique 50 Hz")
            last_target = row["target_ns"]
            passed += flags.astype(np.int64)
            total += 1
            consecutive = np.where(flags, 0, consecutive + 1)
            maximum_consecutive = max(maximum_consecutive, int(np.max(consecutive)))
        if run_reasons:
            reasons.append("run_failed:" + run_id)
        run_results.append({"run_id": run_id, "sample_count": len(run["samples"]), "reasons": run_reasons, "retained": True})
    coverage = np.divide(passed, total, out=np.zeros(9, dtype=float), where=total > 0)
    if not np.all(total > 0) or float(np.min(coverage)) < manifest["minimum_component_coverage"]:
        reasons.append("coverage_below_0.99")
    if maximum_consecutive > manifest["maximum_consecutive_violations"]:
        reasons.append("consecutive_violations")
    reasons = list(dict.fromkeys(reasons))
    qualified = not reasons and bool(run_results)
    return {
        "schema": "openvins-ekf2-fast-cohort-audit-v1",
        "manifest": copy.deepcopy(manifest),
        "sample_count": int(total[0]),
        "component_coverage": dict(zip(COMPONENTS, (float(value) for value in coverage), strict=True)),
        "minimum_component_coverage": float(np.min(coverage)) if np.all(total > 0) else 0.0,
        "maximum_consecutive_violations": maximum_consecutive,
        "run_results": run_results,
        "reasons": reasons,
        "propagated_covariance_sim_domain_qualified": qualified,
        "hardware_covariance_calibrated": False,
        "truth_used_online": False,
        "fusion_eligible": False,
    }
