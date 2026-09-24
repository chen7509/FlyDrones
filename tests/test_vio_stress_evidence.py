from flydrones.vio_stress_evidence import summarize_post_gnss_evidence


def _datasets(*, gnss_before=True):
    timestamps = [second * 1_000_000 for second in range(1, 21)]
    return {
        "estimator_status_flags": {
            "timestamp": timestamps,
            "cs_ev_pos": [1] * 20,
            "cs_ev_vel": [1] * 20,
            "cs_gnss_pos": [int(gnss_before)] * 5 + [0] * 15,
            "cs_gnss_vel": [int(gnss_before)] * 5 + [0] * 15,
            "cs_inertial_dead_reckoning": [0] * 20,
        },
        "estimator_aid_src_ev_pos": {"timestamp": timestamps, "fused": [1] * 20},
        "vehicle_visual_odometry": {"timestamp": timestamps},
        "vehicle_local_position": {
            "timestamp": timestamps,
            "xy_valid": [1] * 20,
            "v_xy_valid": [1] * 20,
        },
    }


def test_post_gnss_continuity_is_separate_from_prior_handoff():
    result = summarize_post_gnss_evidence(_datasets(gnss_before=False), gps_disable_s=5.5)
    assert result["checks"]["visual_position_fused_after_gnss_disable"]
    assert result["accepted"]
    assert not result["checks"]["gnss_to_visual_handoff_proven"]


def test_post_gnss_handoff_requires_prior_gnss_and_ev_fusion():
    result = summarize_post_gnss_evidence(_datasets(), gps_disable_s=5.5)
    assert result["accepted"]
    assert result["checks"]["gnss_to_visual_handoff_proven"]


def test_missing_disable_or_invalid_local_position_rejects_continuity():
    assert not summarize_post_gnss_evidence(_datasets(), gps_disable_s=None)["accepted"]
    datasets = _datasets()
    datasets["vehicle_local_position"]["xy_valid"][-1] = 0
    assert not summarize_post_gnss_evidence(datasets, gps_disable_s=5.5)["accepted"]


def test_even_transient_inertial_dead_reckoning_is_reported_as_not_continuous():
    datasets = _datasets()
    datasets["estimator_status_flags"]["cs_ev_pos"][7] = 0
    datasets["estimator_status_flags"]["cs_ev_vel"][7] = 0
    datasets["estimator_status_flags"]["cs_inertial_dead_reckoning"][7] = 1
    result = summarize_post_gnss_evidence(datasets, gps_disable_s=5.5)
    assert not result["accepted"]
    assert not result["checks"]["visual_position_and_velocity_control_active"]
    assert not result["checks"]["no_observed_inertial_dead_reckoning"]
    assert result["metrics"]["dead_reckoning_observed_duration_s"] == 1.0
