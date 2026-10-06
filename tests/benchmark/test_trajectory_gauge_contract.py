import copy
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from tools.benchmark import trajectory_gauge_contract as gauge

S = np.diag([1.0, -1.0, -1.0])


def native_state(rotation=None, position=(0, 0, 0), velocity=(0, 0, 0)):
    rotation = rotation or Rotation.identity()
    return [*rotation.as_quat(), *position, *velocity, 0, 0, 0, 0, 0, 0]


def truth_row(ns, rotation=None, position=(0, 0, 0), velocity=(0, 0, 0)):
    rotation = rotation or Rotation.identity()  # BODY_FRD to world
    flu_to_world = Rotation.from_matrix(rotation.as_matrix() @ S)
    return {
        "sim_ns": ns,
        "quaternion_xyzw": flu_to_world.as_quat().tolist(),
        "position": list(position),
        "velocity_world": list(velocity),
        "truth_for_fixture_audit_only": True,
    }


def state_row(ns, *, internal, public=False, p=(0, 0, 0), v=(0, 0, 0), rotation=None):
    state = native_state(rotation, p, v) if internal else None
    return {
        "sequence": ns // 1_000_000,
        "kind": "C",
        "sample_ns": ns,
        "receive_ns": ns + 10,
        "start_ns": ns + 20,
        "end_ns": ns + 30,
        "gray_first": 1,
        "internal_initialized": internal,
        "public_initialized": public,
        "initializer_time_s": 1.3 if internal else -1,
        "state_time_s": ns / 1e9 if internal else -1,
        "last_regular_update_s": ns / 1e9 if public else -1,
        "zupt_flag_latched": False,
        "has_moved_since_zupt": public,
        "imu_state": state,
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }


def small_input():
    states = [
        state_row(1_600_000_000, internal=False),
        state_row(2_400_000_000, internal=True, p=(0, 0, 0)),
        state_row(2_800_000_000, internal=True, public=True, p=(0.1, 0, 0), v=(0.1, 0, 0)),
        state_row(2_900_000_000, internal=True, public=True, p=(0.2, 0, 0), v=(0.1, 0, 0)),
    ]
    truth = [
        truth_row(2_400_000_000),
        truth_row(2_800_000_000, position=(0.1, 0, 0), velocity=(0.1, 0, 0)),
        truth_row(2_900_000_000, position=(0.2, 0, 0), velocity=(0.1, 0, 0)),
    ]
    profile = gauge.trajectory_contract(anchor_ns=1_622_000_000)
    session = {"session_id": "fixed-session", "reset_counter": None, "quality": None, "covariance_calibrated": False}
    capture = {"status": "capture_failed", "end_sim_ns": 3_000_000_000}
    return states, truth, profile, session, capture


def test_contract_forbids_fit_scale_timeshift_and_truth_origin_selection():
    contract = gauge.trajectory_contract(anchor_ns=1_622_000_000)
    assert contract["schema"] == "trajectory-gauge-contract-v1"
    assert contract["origin_rule"] == "first_internal_initialized_state_in_session"
    assert contract["alignment"] == "yaw_translation_4dof"
    assert contract["scale"] == 1.0
    assert contract["time_shift_ns"] == 0
    assert contract["truth_used_for_origin_selection"] is False
    assert contract["lateral_start_ns"] == 4_622_000_000
    assert contract["expected_end_ns"] == 25_000_000_000


def test_prospective_policy_has_dynamic_anchor_and_fixed_scoring():
    policy = gauge.trajectory_gauge_policy()
    assert policy["schema"] == "trajectory-gauge-policy-v1"
    assert policy["anchor_source"] == "immutable_readiness_anchor"
    assert "anchor_ns" not in policy
    assert policy["origin_rule"] == "first_internal_initialized_state_in_session"
    assert policy["alignment"] == "yaw_translation_4dof"
    assert policy["scale"] == 1.0
    assert policy["time_shift_ns"] == 0
    assert policy["lateral_start_offset_ns"] == 3_000_000_000
    assert policy["expected_duration_ns"] == 25_000_000_000
    assert policy["truth_used_for_origin_selection"] is False
    assert policy["eligible_for_px4_fusion"] is False
    assert policy["flight_ready"] is False
    assert gauge.validate_trajectory_gauge_policy(policy) == policy


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(anchor_ns=1),
    lambda row: row["screens"].update(max_position_error_m=0.5),
    lambda row: row.update(scale=1),
    lambda row: row.update(time_shift_ns=False),
    lambda row: row.update(anchor_source="truth_selected_anchor"),
    lambda row: row.update(extra="ignored"),
])
def test_prospective_policy_refuses_dynamic_anchor_or_semantic_change(mutation):
    policy = gauge.trajectory_gauge_policy()
    mutation(policy)
    with pytest.raises(ValueError, match="trajectory gauge policy"):
        gauge.validate_trajectory_gauge_policy(policy)


def test_origin_selection_is_first_internal_and_independent_of_truth():
    states, truth, profile, session, capture = small_input()
    selected = gauge.select_origin(states, profile)
    changed = copy.deepcopy(truth)
    changed[0]["position"] = [1e6, -1e6, 1e6]
    assert selected["sample_ns"] == 2_400_000_000
    assert gauge.select_origin(states, profile) == selected
    result = gauge.audit_trajectory(states, changed, session, capture, profile)
    assert result["origin"]["sample_ns"] == 2_400_000_000
    assert result["origin"]["truth_used_for_selection"] is False


def test_yaw_gauge_rotates_position_velocity_without_hiding_tilt():
    native_origin = Rotation.from_euler("xyz", [15, -12, 23], degrees=True)
    yaw = Rotation.from_euler("z", 70, degrees=True)
    tilt = Rotation.from_euler("x", 11, degrees=True)
    truth_origin = yaw * native_origin * tilt
    g = gauge.YawTranslationGauge(
        native_state(native_origin, (1, 2, 3)),
        truth_row(0, truth_origin, (7, 8, 9)),
    )
    delta = np.array([0.3, -0.2, 0.4])
    velocity = np.array([0.5, 0.2, -0.1])
    next_native = native_origin * Rotation.from_euler("y", 9, degrees=True)
    row = g.compare(
        native_state(next_native, np.array([1, 2, 3]) + delta, velocity),
        truth_row(
            1,
            yaw * next_native * tilt,
            np.array([7, 8, 9]) + yaw.apply(delta),
            yaw.apply(velocity),
        ),
    )
    assert row["position_error_m"] < 1e-10
    assert row["velocity_error_m_s"] < 1e-10
    assert row["attitude_error_deg"] == pytest.approx(11)
    assert g.gravity_axis_error_deg == pytest.approx(11)


def test_degenerate_horizontal_heading_and_invalid_state_are_refused():
    vertical_x = Rotation.from_euler("y", 90, degrees=True)
    with pytest.raises(ValueError, match="horizontal heading"):
        gauge.YawTranslationGauge(native_state(vertical_x), truth_row(0))
    bad = native_state()
    bad[0] = float("nan")
    with pytest.raises(ValueError, match="numeric"):
        gauge.YawTranslationGauge(bad, truth_row(0))


def test_partial_capture_scores_diagnostic_but_never_qualifies():
    states, truth, profile, session, capture = small_input()
    result = gauge.audit_trajectory(states, truth, session, capture, profile)
    assert result["diagnostic_available"] is True
    assert result["startup_unavailable"] == {
        "start_ns": 1_622_000_000,
        "end_ns": 2_400_000_000,
        "duration_ns": 778_000_000,
    }
    assert result["metrics"]["max_position_error_m"] < 1e-12
    assert result["diagnostic_screens_pass"] is True
    assert result["capture_complete"] is False
    assert result["estimator_health_qualified"] is False
    assert result["post_origin_trajectory_qualified"] is False
    assert result["full_motion_trajectory_qualified"] is False
    assert result["trajectory_qualified"] is False
    assert result["fusion_eligible"] is False
    assert result["flight_ready"] is False


def test_complete_healthy_synthetic_trajectory_can_qualify_only_offline_trajectory():
    states, truth, _, session, _ = small_input()
    for ns in range(3_000_000_000, 5_000_000_000, 100_000_000):
        position = ((ns - 2_400_000_000) / 1e9 * 0.1, 0, 0)
        states.append(state_row(ns, internal=True, public=True, p=position, v=(0.1, 0, 0)))
        truth.append(truth_row(ns, position=position, velocity=(0.1, 0, 0)))
    profile = gauge.trajectory_contract(anchor_ns=1_622_000_000, total_duration_ns=5_000_000_000)
    session.update(reset_counter=0, quality=80, covariance_calibrated=True)
    result = gauge.audit_trajectory(
        states,
        truth,
        session,
        {"status": "capture_completed", "end_sim_ns": 5_000_000_000},
        profile,
    )
    assert result["post_origin_trajectory_qualified"] is True
    assert result["full_motion_trajectory_qualified"] is False
    assert result["trajectory_qualified"] is False
    assert result["estimator_health_qualified"] is True
    assert result["fusion_eligible"] is False
    assert result["flight_ready"] is False


def test_exact_truth_match_is_required_without_interpolation():
    states, truth, profile, session, capture = small_input()
    truth.pop(1)
    with pytest.raises(ValueError, match="exact truth"):
        gauge.audit_trajectory(states, truth, session, capture, profile)


@pytest.mark.parametrize("mutation, pattern", [
    (lambda rows: rows.__setitem__(2, {**rows[2], "sample_ns": rows[1]["sample_ns"]}), "sample"),
    (lambda rows: rows[2].__setitem__("internal_initialized", False), "internal"),
    (lambda rows: rows[3].__setitem__("public_initialized", False), "public"),
    (lambda rows: rows[2].__setitem__("state_time_s", 2.800000002), "state time"),
    (lambda rows: rows[2].__setitem__("start_ns", rows[2]["receive_ns"] - 1), "clock"),
    (lambda rows: rows[2].update(receive_ns=1, start_ns=2, end_ns=3), "clock"),
    (lambda rows: rows[3].__setitem__("initializer_time_s", 1.2), "initializer"),
    (lambda rows: rows[2].__setitem__("last_regular_update_s", -1), "regular update"),
    (lambda rows: rows[2].__setitem__("reset_counter", True), "reset counter"),
    (lambda rows: rows[2].__setitem__("quality", 101), "quality"),
])
def test_invalid_state_lifecycle_is_refused(mutation, pattern):
    states, truth, profile, session, capture = small_input()
    mutation(states)
    with pytest.raises(ValueError, match=pattern):
        gauge.audit_trajectory(states, truth, session, capture, profile)


def test_origin_after_lateral_start_is_indeterminate_not_reselected():
    states, truth, profile, session, capture = small_input()
    for row in states:
        row["internal_initialized"] = False
        row["public_initialized"] = False
        row["imu_state"] = None
        row["state_time_s"] = -1
        row["last_regular_update_s"] = -1
    late = state_row(profile["lateral_start_ns"] + 1, internal=True, public=True)
    states.append(late)
    truth.append(truth_row(late["sample_ns"]))
    result = gauge.audit_trajectory(states, truth, session, capture, profile)
    assert result["origin"]["sample_ns"] == late["sample_ns"]
    assert result["diagnostic_available"] is False
    assert "origin_after_lateral_start" in result["reasons"]


def test_known_reset_or_unknown_health_never_becomes_fusion_qualified():
    states, truth, profile, session, capture = small_input()
    unknown = gauge.audit_trajectory(states, truth, session, capture, profile)
    assert "reset_unknown" in unknown["reasons"]
    session.update(reset_counter=1, quality=80, reset_observed=True, covariance_calibrated=True)
    reset = gauge.audit_trajectory(states, truth, session, capture, profile)
    assert "reset_observed" in reset["reasons"]
    assert reset["estimator_health_qualified"] is False
    assert reset["fusion_eligible"] is False

    session.update(reset_observed=False)
    states[2]["reset_counter"] = 0
    states[3]["reset_counter"] = 1
    changed = gauge.audit_trajectory(states, truth, session, capture, profile)
    assert "reset_observed" in changed["reasons"]
    assert changed["post_origin_trajectory_qualified"] is False


def test_fixed_pr48_projection_preserves_first_origin_and_failure(tmp_path):
    archive = Path("evidence/supported-online-vio-dev-1701.zip")
    output = tmp_path / "audit.json"
    result = gauge.audit_pr48_archive(archive, output=output)
    assert json.loads(output.read_text()) == result
    assert result["archive_sha256"] == "07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2"
    assert result["origin"]["sample_ns"] == 2_400_000_000
    assert result["startup_unavailable"]["duration_ns"] == 778_000_000
    assert result["first_public_sample_ns"] == 2_800_000_000
    assert result["diagnostic_screens_pass"] is True
    assert result["metrics"]["max_position_error_m"] == pytest.approx(0.10241108255463242)
    assert result["metrics"]["max_velocity_error_m_s"] == pytest.approx(0.1506612828107049)
    assert result["metrics"]["max_attitude_error_deg"] == pytest.approx(0.9675004506458674)
    assert result["metrics"]["initial_gravity_axis_error_deg"] == pytest.approx(0.006404594036385702)
    assert result["capture_complete"] is False
    assert result["post_origin_trajectory_qualified"] is False
    assert result["full_motion_trajectory_qualified"] is False
    assert result["trajectory_qualified"] is False
    assert result["estimator_health_qualified"] is False
    assert result["fusion_eligible"] is False
    assert result["consumed_members_verified"] is True


def test_archive_hash_mismatch_and_output_overwrite_are_refused(tmp_path):
    archive = Path("evidence/supported-online-vio-dev-1701.zip")
    with pytest.raises(ValueError, match="archive SHA"):
        gauge.audit_pr48_archive(archive, expected_sha256="0" * 64)
    output = tmp_path / "audit.json"
    output.write_text("existing")
    with pytest.raises(FileExistsError):
        gauge.audit_pr48_archive(archive, output=output)
