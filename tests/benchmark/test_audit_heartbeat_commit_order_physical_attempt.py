import copy

import pytest


def valid_summary():
    return {
        "capture_status": "capture_completed",
        "errors": [],
        "end_sim_ns": 25_000_000_000,
        "px4_exit_code": 0,
        "native_exit_code": 0,
        "writer_counts": {"imu": 6251, "info": 251, "depth": 251, "rgb": 251, "heartbeat": 24},
        "fanout_committed": 7028,
        "fanout_failure": None,
        "fanout_refusals": [],
        "heartbeat_observed": 24,
        "heartbeat_reconciled": 24,
        "heartbeat_pending": [],
        "heartbeat_failure": None,
        "native_reference_pre": 25000,
        "native_reference_post": 25000,
        "motion_support_steps": 22380,
        "motion_active_steps": 1600,
        "motion_commands": 22380,
        "motion_absolute_impulse_ns": 41.6,
        "motion_signed_impulse_ns": 0.0,
        "motion_anchor_ns": 2_621_000_000,
        "physics_records": 50000,
        "runtime_mapping": True,
        "runtime_closure": False,
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "completion_command_returncode": 0,
        "completion_launcher_returncode": 0,
        "completion_destination_exists": True,
        "completion_resources_after": [],
        "supervisor_capture_status": "capture_completed",
        "supervisor_worker_exit": 0,
        "supervisor_no_executing": True,
        "supervisor_group_absent": True,
        "supervisor_sigkill": False,
        "supervisor_descendants_qualified": False,
        "ulog_count": 1,
        "ulog_identity_verified": True,
        "trajectory_reference": "native-reference-canary-overwritten-v1",
        "trajectory_reference_count": 25000,
        "trajectory": {
            "capture_complete": True,
            "public_coverage_qualified": True,
            "diagnostic_available": True,
            "diagnostic_screens_pass": False,
            "estimator_health_qualified": False,
            "trajectory_qualified": False,
            "reasons": ["reset_unknown", "quality_unknown", "covariance_uncalibrated", "accuracy_screen_failed"],
            "metrics": {"max_position_error_m": 47.719, "max_velocity_error_m_s": 4.058},
        },
    }


def test_completed_attempt_qualifies_evidence_but_keeps_flight_gates_closed():
    from tools.benchmark.audit_heartbeat_commit_order_physical_attempt import classify_summary

    result = classify_summary(valid_summary())
    assert result["attempt_evidence_qualified"] is True
    assert result["classification"] == "completed-physical-run-vio-accuracy-and-health-failure"
    assert result["physical_execution_qualified"] is True
    assert result["heartbeat_commit_order_physically_verified"] is True
    assert result["vio_accuracy_qualified"] is False
    assert result["estimator_health_qualified"] is False
    assert result["fruit_fly_policy_failure"] is False
    assert result["flight_ready"] is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("writer_counts", "imu"), 6250),
        (("fanout_committed",), 7027),
        (("heartbeat_pending",), [{"observation_sequence": 23}]),
        (("native_reference_post",), 24999),
        (("motion_active_steps",), 1599),
        (("completion_resources_after",), ["px4"]),
        (("supervisor_group_absent",), False),
        (("ulog_identity_verified",), False),
        (("trajectory", "capture_complete"), False),
        (("trajectory", "diagnostic_screens_pass"), True),
    ],
)
def test_attempt_audit_rejects_drift_or_overclaim(path, value):
    from tools.benchmark.audit_heartbeat_commit_order_physical_attempt import classify_summary

    summary = copy.deepcopy(valid_summary())
    target = summary
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert classify_summary(summary)["attempt_evidence_qualified"] is False


def test_attempt_audit_rejects_missing_accuracy_failure_reason():
    from tools.benchmark.audit_heartbeat_commit_order_physical_attempt import classify_summary

    summary = valid_summary()
    summary["trajectory"]["reasons"].remove("accuracy_screen_failed")
    assert classify_summary(summary)["attempt_evidence_qualified"] is False


def test_native_reference_adapter_requires_each_step_canary_overwrite():
    from tools.benchmark.audit_heartbeat_commit_order_physical_attempt import native_reference_truth

    rows = [
        {
            "pre_ns": 1_000_000,
            "post_ns": 1_000_000,
            "canary_overwritten": True,
            "position": [1, 2, 3],
            "velocity_world": [0, 0, 0],
            "accel_world": [0, 0, 0],
            "angular_world": [0, 0, 0],
            "quaternion_xyzw": [0, 0, 0, 1],
            "truth_for_abort_audit_only": True,
        }
    ]
    converted = native_reference_truth(rows)
    assert converted[0]["sim_ns"] == 1_000_000
    assert converted[0]["truth_for_fixture_audit_only"] is True
    rows[0]["canary_overwritten"] = False
    with pytest.raises(ValueError):
        native_reference_truth(rows)
