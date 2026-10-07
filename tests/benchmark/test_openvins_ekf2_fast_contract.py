import copy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_ekf2_fast_contract import (
    COMPONENTS,
    audit_fast_cohort,
    build_fast_manifest,
    transform_fast12,
)


def test_fast_transform_keeps_unique_body_velocity_and_all_cross_covariance():
    state = [*Rotation.from_euler("xyz", [17, -9, 31], degrees=True).as_quat(), 1, 2, 3, 4, -2, 1.5, 0.1, 0.2, -0.3]
    factor = np.arange(1, 13 * 13 + 1, dtype=float).reshape(13, 13)[:12]
    covariance = factor @ factor.T * 1e-8
    result = transform_fast12(state, covariance)
    jacobian = np.asarray(result["jacobian9x12"])
    expected = jacobian @ np.asarray(result["bounded_covariance12"]) @ jacobian.T
    np.testing.assert_allclose(result["velocity_body_frd"], state[7:10])
    np.testing.assert_allclose(result["covariance9x9"], expected, atol=1e-12)
    assert np.count_nonzero(np.asarray(result["covariance9x9"]) - np.diag(np.diag(result["covariance9x9"]))) > 0
    assert result["fusion_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s, c: s.__setitem__(0, float("nan")),
        lambda s, c: s.__setitem__(3, 0.0),
        lambda s, c: c.__setitem__((0, 0), -1.0),
        lambda s, c: c.__setitem__((0, 1), 1.0),
    ],
)
def test_fast_transform_rejects_bad_native_evidence(mutation):
    state = np.array([0, 0, 0, 1, *([0] * 9)], dtype=float)
    covariance = np.eye(12) * 1e-3
    mutation(state, covariance)
    with pytest.raises(ValueError):
        transform_fast12(state, covariance)


def sample(index=0, *, violation=None):
    error = np.zeros(9)
    if violation is not None:
        error[violation] = 1.0
    return {
        "target_ns": 1 + index * 20_000_000,
        "public_initialized": True,
        "visual_age_ns": 20_000_000,
        "imu_boundary_age_ns": 4_000_000,
        "error_attitude_position_velocity": error.tolist(),
        "bounded_covariance12": (np.eye(12) * 0.01).tolist(),
        "fusion_eligible": False,
    }


def run(samples):
    return {
        "status": "capture_completed",
        "source_health_qualified": True,
        "native_health_qualified": True,
        "trajectory_accuracy_qualified": True,
        "samples": samples,
    }


def test_fast_cohort_requires_prospective_exact_runs_and_passes_coverage():
    manifest = build_fast_manifest(["held-a", "held-b"])
    evidence = {"held-a": run([sample(i) for i in range(100)]), "held-b": run([sample(i) for i in range(100)])}
    result = audit_fast_cohort(manifest, evidence)
    assert result["propagated_covariance_sim_domain_qualified"] is True
    assert result["sample_count"] == 200
    assert result["component_coverage"] == {name: 1.0 for name in COMPONENTS}
    assert result["fusion_eligible"] is False


def test_fast_cohort_retains_failures_and_rejects_manifest_or_coverage_drift():
    manifest = build_fast_manifest(["held-a"])
    bad = {"held-a": run([sample(i, violation=0) for i in range(100)])}
    result = audit_fast_cohort(manifest, bad)
    assert result["propagated_covariance_sim_domain_qualified"] is False
    assert "coverage_below_0.99" in result["reasons"]
    drift = copy.deepcopy(manifest)
    drift["minimum_component_coverage"] = 0.98
    with pytest.raises(ValueError):
        audit_fast_cohort(drift, bad)
