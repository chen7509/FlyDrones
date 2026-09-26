from flydrones.vio_stress_evidence import (
    match_relay_to_visual_odometry,
    summarize_external_vision_health,
    summarize_post_gnss_evidence,
)


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
        "estimator_aid_src_ev_pos": {
            "timestamp": timestamps,
            "fused": [1] * 20,
            "innovation_rejected": [0] * 20,
        },
        "vehicle_visual_odometry": {"timestamp": timestamps},
        "vehicle_local_position": {
            "timestamp": timestamps,
            "xy_valid": [1] * 20,
            "v_xy_valid": [1] * 20,
            "xy_reset_counter": [0] * 20,
            "vxy_reset_counter": [0] * 20,
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


def test_external_vision_health_is_proven_without_claiming_gnss_handoff():
    datasets = _datasets()
    datasets["vehicle_visual_odometry"]["timestamp"] = [index * 100_000 for index in range(70)]
    result = summarize_external_vision_health(datasets)

    assert result["accepted"]
    assert result["checks"]["visual_position_and_velocity_control_active"]
    assert result["checks"]["visual_odometry_stream_continuous"]
    assert "gnss_to_visual_handoff_proven" not in result["checks"]


def test_external_vision_health_rejects_missing_or_dead_reckoning_evidence():
    datasets = _datasets()
    del datasets["vehicle_local_position"]
    assert not summarize_external_vision_health(datasets)["accepted"]

    datasets = _datasets()
    datasets["estimator_status_flags"]["cs_inertial_dead_reckoning"][7] = 1
    assert not summarize_external_vision_health(datasets)["accepted"]


def test_external_vision_health_rejects_innovation_rejection_and_estimator_resets():
    datasets = _datasets()
    datasets["estimator_aid_src_ev_pos"]["innovation_rejected"][7] = 1
    result = summarize_external_vision_health(datasets)
    assert not result["accepted"]
    assert not result["checks"]["no_visual_innovation_rejection"]

    datasets = _datasets()
    datasets["vehicle_local_position"]["xy_reset_counter"][8:] = [1] * 12
    result = summarize_external_vision_health(datasets)
    assert not result["accepted"]
    assert not result["checks"]["no_unexplained_horizontal_estimator_reset"]


def test_external_vision_health_allows_a_reset_before_the_evidence_window():
    datasets = _datasets()
    datasets["vehicle_local_position"]["xy_reset_counter"][7:] = [1] * 13
    datasets["vehicle_visual_odometry"]["timestamp"] = [
        index * 100_000 for index in range(200)
    ]

    full_run = summarize_external_vision_health(datasets)
    after_switch = summarize_external_vision_health(datasets, start_s=8.5)

    assert not full_run["accepted"]
    assert after_switch["accepted"]
    assert after_switch["metrics"]["evidence_window_start_s"] == 8.5


def test_post_gnss_evidence_rejects_a_horizontal_reset_after_the_switch_window():
    datasets = _datasets()
    datasets["vehicle_local_position"]["xy_reset_counter"][9:] = [1] * 11

    result = summarize_post_gnss_evidence(datasets, gps_disable_s=5.5)

    assert not result["accepted"]
    assert not result["checks"]["no_unexplained_horizontal_estimator_reset"]


def test_relay_to_px4_requires_matching_transformed_pose_and_time():
    events = [
        {"active": True, "model": "x500_depth_fly_0", "source_stamp_ns": 10_000_000_000,
         "published_position_m": [2.0, -3.0, -1.0], "offset_m": [1.0, 0.0, 0.0],
         "actual_delay_ms": 120.0},
        {"active": True, "model": "x500_depth_fly_0", "source_stamp_ns": 11_000_000_000,
         "published_position_m": [3.0, -4.0, -1.0], "offset_m": [1.0, 0.0, 0.0],
         "actual_delay_ms": 120.0},
    ]
    visual = {"timestamp": [10_120_000, 11_120_000],
              "position[0]": [-3.0, -4.0], "position[1]": [2.0, 3.0],
              "position[2]": [1.0, 1.0]}
    matched = match_relay_to_visual_odometry(events, visual)
    assert matched["matched_active_samples"] == 2
    assert matched["matched_offset_samples"] == 2
    assert matched["maximum_position_error_m"] < 0.001
    assert matched["median_ulog_minus_source_stamp_ms"] == 120.0
    visual["position[1]"][1] = 30.0
    assert match_relay_to_visual_odometry(events, visual)["matched_active_samples"] == 1
