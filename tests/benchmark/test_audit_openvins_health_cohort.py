import copy

import numpy as np
import pytest

from tools.benchmark.audit_openvins_health_cohort import audit_cohort, build_manifest
from tools.benchmark.openvins_health_contract import CovarianceProfile


def sample(
    *,
    scale=0.5,
    session_id="session-a",
    quality=0,
    reset_counter=0,
    public_initialized=True,
    health_reasons=None,
    failed_latched=False,
):
    profile = CovarianceProfile(sim_domain_qualified=False)
    covariance = np.eye(15)
    covariance[0:3, 0:3] *= profile.attitude_variance_floor
    covariance[3:6, 3:6] *= profile.position_variance_floor
    covariance[6:9, 6:9] *= profile.velocity_variance_floor
    return {
        "session_id": session_id,
        "quality": quality,
        "reset_counter": reset_counter,
        "public_initialized": public_initialized,
        "health_reasons": ["covariance_profile_unqualified"] if health_reasons is None else health_reasons,
        "failed_latched": failed_latched,
        "position_error_xyz_m": [scale * 0.25] * 3,
        "velocity_error_xyz_m_s": [scale * 0.25] * 3,
        "attitude_error_tangent_xyz_rad": [scale * np.deg2rad(10.0)] * 3,
        "bounded_covariance15": covariance.tolist(),
    }


def run(samples=None, **updates):
    value = {
        "status": "capture_completed",
        "session_id": "session-a",
        "trajectory_accuracy_qualified": True,
        "source_health_qualified": True,
        "native_health_qualified": True,
        "samples": [sample() for _ in range(100)] if samples is None else samples,
    }
    value.update(updates)
    return value


def manifest(*run_ids):
    return build_manifest(CovarianceProfile(), list(run_ids))


def test_held_out_cohort_passes_predeclared_99_percent_three_sigma_gate():
    samples = [sample() for _ in range(100)]
    samples[50] = sample(scale=1.01)
    result = audit_cohort(manifest("held-1"), {"held-1": run(samples)})
    assert result["sample_count"] == 100
    assert result["minimum_component_coverage"] == pytest.approx(0.99)
    assert result["maximum_consecutive_violations"] == 1
    assert result["covariance_sim_domain_qualified"] is True
    assert result["fusion_eligible"] is False


def test_coverage_below_99_percent_fails_without_discarding_run():
    samples = [sample() for _ in range(100)]
    samples[10] = sample(scale=1.01)
    samples[90] = sample(scale=1.01)
    result = audit_cohort(manifest("held-1"), {"held-1": run(samples)})
    assert result["minimum_component_coverage"] == pytest.approx(0.98)
    assert result["covariance_sim_domain_qualified"] is False
    assert result["run_results"][0]["retained"] is True
    assert "coverage_below_0.99" in result["reasons"]


def test_five_consecutive_violations_fail_even_when_aggregate_coverage_passes():
    samples = [sample() for _ in range(1000)]
    samples[100:105] = [sample(scale=1.01) for _ in range(5)]
    result = audit_cohort(manifest("held-1"), {"held-1": run(samples)})
    assert result["minimum_component_coverage"] == pytest.approx(0.995)
    assert result["maximum_consecutive_violations"] == 5
    assert result["covariance_sim_domain_qualified"] is False
    assert "consecutive_violations" in result["reasons"]


def test_failed_and_missing_runs_cannot_be_hidden():
    failed = audit_cohort(
        manifest("held-1", "held-2"),
        {
            "held-1": run(),
            "held-2": run(samples=[], status="capture_failed", trajectory_accuracy_qualified=False),
        },
    )
    assert failed["covariance_sim_domain_qualified"] is False
    assert failed["run_results"][1]["status"] == "capture_failed"
    assert "run_failed:held-2" in failed["reasons"]
    with pytest.raises(ValueError, match="declared run evidence"):
        audit_cohort(manifest("held-1", "held-2"), {"held-1": run()})


def test_session_truth_binding_quality_and_reset_must_remain_consistent():
    changed = [sample() for _ in range(100)]
    changed[50] = sample(session_id="session-b")
    with pytest.raises(ValueError, match="session mismatch"):
        audit_cohort(manifest("held-1"), {"held-1": run(changed)})

    quality = [sample() for _ in range(100)]
    quality[50] = sample(quality=-1, health_reasons=["native_failure"], failed_latched=True)
    result = audit_cohort(manifest("held-1"), {"held-1": run(quality)})
    assert result["covariance_sim_domain_qualified"] is False
    assert "health_not_prequalification_ready:held-1" in result["reasons"]

    reset = [sample() for _ in range(100)]
    reset[50] = sample(reset_counter=1)
    result = audit_cohort(manifest("held-1"), {"held-1": run(reset)})
    assert result["covariance_sim_domain_qualified"] is False
    assert "reset_changed:held-1" in result["reasons"]


@pytest.mark.parametrize(
    "changes",
    [
        {"quality": 1, "health_reasons": []},
        {"public_initialized": False},
        {"health_reasons": ["regular_update_stale"]},
        {"failed_latched": True, "quality": -1, "health_reasons": ["source_failure"]},
    ],
)
def test_only_unqualified_profile_may_hold_quality_at_zero_before_promotion(changes):
    rows = [sample() for _ in range(100)]
    rows[50] = sample(**changes)
    result = audit_cohort(manifest("held-1"), {"held-1": run(rows)})
    assert result["covariance_sim_domain_qualified"] is False
    assert "health_not_prequalification_ready:held-1" in result["reasons"]


def test_manifest_profile_mutation_and_unlisted_evidence_are_rejected():
    value = manifest("held-1")
    value["profile"]["position_variance_floor"] *= 2
    with pytest.raises(ValueError, match="profile digest"):
        audit_cohort(value, {"held-1": run()})
    with pytest.raises(ValueError, match="declared run evidence"):
        audit_cohort(manifest("held-1"), {"held-1": run(), "extra": run()})


@pytest.mark.parametrize("corruption", ["nan", "asymmetric", "negative", "short"])
def test_invalid_covariance_evidence_is_rejected(corruption):
    bad = sample()
    covariance = np.asarray(bad["bounded_covariance15"])
    if corruption == "nan":
        covariance[0, 0] = np.nan
    elif corruption == "asymmetric":
        covariance[0, 1] = 0.5
    elif corruption == "negative":
        covariance[0, 0] = -1
    else:
        covariance = np.ones((2, 2))
    bad["bounded_covariance15"] = covariance.tolist()
    evidence = run([bad])
    with pytest.raises(ValueError, match="covariance"):
        audit_cohort(manifest("held-1"), {"held-1": evidence})


def test_manifest_is_independent_of_mutable_profile_instance():
    profile = CovarianceProfile()
    value = build_manifest(profile, ["held-1"])
    before = copy.deepcopy(value)
    audit_cohort(value, {"held-1": run()})
    assert value == before
