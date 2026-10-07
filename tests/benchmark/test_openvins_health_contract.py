import copy

import numpy as np
import pytest

from tools.benchmark.openvins_health_contract import CovarianceProfile, OpenVinsHealthContract


def covariance15(value=1e-3):
    return (np.eye(15) * value).tolist()


def row(
    sample_ns=3_000_000_000,
    *,
    session_id="session-a",
    internal=True,
    public=True,
    state_time_s=None,
    last_regular_update_s=2.9,
    covariance=None,
):
    return {
        "kind": "C",
        "session_id": session_id,
        "sample_ns": sample_ns,
        "internal_initialized": internal,
        "public_initialized": public,
        "state_time_s": sample_ns * 1e-9 if state_time_s is None else state_time_s,
        "last_regular_update_s": last_regular_update_s,
        "imu_covariance15": covariance15() if covariance is None else covariance,
    }


def source_health(**changes):
    value = {
        "source_healthy": True,
        "native_healthy": True,
        "source_failure": None,
        "native_failure": None,
    }
    value.update(changes)
    return value


def qualified_profile():
    return CovarianceProfile(sim_domain_qualified=True)


def test_quality_is_unknown_until_public_and_profile_are_qualified():
    contract = OpenVinsHealthContract("session-a", profile=CovarianceProfile())
    result = contract.accept_camera(row(public=False), source_health())
    assert result["quality"] == 0
    assert result["reasons"] == ["public_unavailable", "covariance_profile_unqualified"]
    assert result["fusion_eligible"] is False


def test_uninitialized_camera_has_unknown_quality_without_covariance():
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    sample = row(internal=False, public=False, state_time_s=-1, last_regular_update_s=-1, covariance=None)
    sample["imu_covariance15"] = None
    result = contract.accept_camera(sample, source_health())
    assert result["quality"] == 0
    assert result["reasons"] == ["internal_unavailable"]
    assert result["bounded_covariance15"] is None


def test_quality_one_is_minimum_positive_only_for_current_healthy_public_state():
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    result = contract.accept_camera(row(), source_health())
    assert result["quality"] == 1
    assert result["quality_semantics"] == "mavlink-minimum-positive-not-a-percentage-score"
    assert result["reset_total"] == result["reset_counter"] == 0
    assert result["covariance_profile"] == "px4-d6f12ad-gate-floor-v1"
    assert result["covariance_sim_domain_qualified"] is True
    assert result["fusion_eligible"] is False
    covariance = np.asarray(result["bounded_covariance15"])
    assert np.all(np.diag(covariance)[0:3] >= qualified_profile().attitude_variance_floor)
    assert np.all(np.diag(covariance)[3:6] >= qualified_profile().position_variance_floor)
    assert np.all(np.diag(covariance)[6:9] >= qualified_profile().velocity_variance_floor)


def test_stale_visual_update_is_unknown_but_not_latched_failure():
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    stale = contract.accept_camera(row(last_regular_update_s=2.7), source_health())
    assert stale["quality"] == 0
    assert stale["reasons"] == ["regular_update_stale"]
    recovered = contract.accept_camera(
        row(sample_ns=3_100_000_000, last_regular_update_s=3.0), source_health()
    )
    assert recovered["quality"] == 1


@pytest.mark.parametrize(
    "changed,reason",
    [
        ({"source_healthy": False, "source_failure": "camera silence"}, "source_failure"),
        ({"native_healthy": False, "native_failure": "ack timeout"}, "native_failure"),
    ],
)
def test_source_or_native_failure_latches_negative_quality(changed, reason):
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    failed = contract.accept_camera(row(), source_health(**changed))
    assert failed["quality"] == -1
    assert failed["reasons"] == [reason]
    later = contract.accept_camera(row(sample_ns=3_100_000_000), source_health())
    assert later["quality"] == -1
    assert later["reasons"] == [reason]


@pytest.mark.parametrize("corruption", ["nan", "asymmetric", "negative"])
def test_invalid_covariance_fails_closed(corruption):
    covariance = np.eye(15) * 1e-3
    if corruption == "nan":
        covariance[0, 0] = np.nan
    elif corruption == "asymmetric":
        covariance[0, 1] = 0.1
    else:
        covariance[0, 0] = -1.0
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    result = contract.accept_camera(row(covariance=covariance.tolist()), source_health())
    assert result["quality"] == -1
    assert result["reasons"] == ["covariance_invalid"]


def test_time_regression_and_public_reversion_fail_closed():
    time_contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    assert time_contract.accept_camera(row(), source_health())["quality"] == 1
    assert time_contract.accept_camera(
        row(sample_ns=2_999_999_999, state_time_s=2.999999999), source_health()
    )["reasons"] == ["sample_time_regressed"]

    public_contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    assert public_contract.accept_camera(row(), source_health())["quality"] == 1
    reverted = public_contract.accept_camera(
        row(sample_ns=3_100_000_000, internal=True, public=False, last_regular_update_s=3.0),
        source_health(),
    )
    assert reverted["quality"] == -1
    assert reverted["reasons"] == ["public_state_reverted"]


def test_state_timestamp_must_match_camera_sample():
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    result = contract.accept_camera(row(state_time_s=2.99), source_health())
    assert result["quality"] == -1
    assert result["reasons"] == ["state_time_mismatch"]


def test_explicit_session_replacement_increments_total_and_wraps_wire_counter():
    first = OpenVinsHealthContract("session-a", reset_total=255, profile=qualified_profile())
    second = first.replace_session("session-b")
    unknown = second.accept_camera(row(session_id="session-b", public=False), source_health())
    assert unknown["reset_total"] == 256
    assert unknown["reset_counter"] == 0
    assert unknown["quality"] == 0
    valid = second.accept_camera(
        row(session_id="session-b", sample_ns=3_100_000_000, last_regular_update_s=3.0),
        source_health(),
    )
    assert valid["quality"] == 1


def test_session_reuse_mismatch_and_reset_rollback_are_rejected():
    first = OpenVinsHealthContract("session-a", reset_total=3, profile=qualified_profile())
    second = first.replace_session("session-b")
    with pytest.raises(ValueError, match="session identity"):
        second.replace_session("session-a")
    mismatch = second.accept_camera(row(session_id="session-c"), source_health())
    assert mismatch["quality"] == -1
    assert mismatch["reasons"] == ["session_mismatch"]
    with pytest.raises(ValueError, match="reset total"):
        OpenVinsHealthContract("session-z", reset_total=-1, profile=qualified_profile())


def test_covariance_profile_preserves_cross_terms_and_does_not_mutate_input():
    covariance = np.eye(15) * 1e-4
    covariance[3, 6] = covariance[6, 3] = 2e-5
    original = copy.deepcopy(covariance.tolist())
    bounded = qualified_profile().bound(original)
    assert original == covariance.tolist()
    assert bounded[3][6] == bounded[6][3] == 2e-5
    assert np.linalg.eigvalsh(np.asarray(bounded)).min() >= -1e-12


def test_schema_and_boolean_integer_confusion_are_rejected():
    with pytest.raises(ValueError, match="session identity"):
        OpenVinsHealthContract(" ", profile=qualified_profile())
    with pytest.raises(ValueError, match="reset total"):
        OpenVinsHealthContract("session-a", reset_total=True, profile=qualified_profile())
    contract = OpenVinsHealthContract("session-a", profile=qualified_profile())
    malformed = row()
    malformed["sample_ns"] = True
    result = contract.accept_camera(malformed, source_health())
    assert result["quality"] == -1
    assert result["reasons"] == ["camera_state_invalid"]
