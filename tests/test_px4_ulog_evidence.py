from __future__ import annotations

from flydrones.px4_ulog_evidence import summarize_fusion_evidence


def test_fusion_evidence_proves_external_vision_replaces_gnss_without_dead_reckoning():
    datasets = {
        "estimator_status_flags": {
            "timestamp": [10_000_000, 20_000_000, 30_000_000, 40_000_000],
            "cs_ev_pos": [False, True, True, True],
            "cs_ev_vel": [False, True, True, True],
            "cs_gnss_pos": [True, True, False, False],
            "cs_gnss_vel": [True, True, False, False],
            "cs_inertial_dead_reckoning": [False, False, False, False],
        },
        "estimator_aid_src_ev_pos": {
            "timestamp": [19_000_000, 29_900_000, 30_100_000, 31_000_000, 39_000_000],
            "fused": [True, True, True, True, True],
            "innovation_rejected": [False, False, False, False, False],
        },
        "estimator_aid_src_gnss_pos": {
            "timestamp": [19_000_000, 29_900_000],
            "fused": [True, True],
            "innovation_rejected": [False, False],
        },
        "estimator_aid_src_gnss_vel": {
            "timestamp": [19_000_000, 29_900_000],
            "fused": [True, True],
            "innovation_rejected": [False, False],
        },
        "vehicle_visual_odometry": {
            "timestamp": list(range(29_900_000, 40_000_001, 100_000)),
        },
        "vehicle_local_position": {
            "timestamp": [29_900_000, 30_020_000, 31_000_000, 40_000_000],
            "xy_reset_counter": [1, 2, 2, 2],
            "delta_xy[0]": [0.0, -4.0, -4.0, -4.0],
            "delta_xy[1]": [0.0, -0.05, -0.05, -0.05],
            "xy_valid": [True, True, True, True],
            "v_xy_valid": [True, True, True, True],
        },
    }

    evidence = summarize_fusion_evidence(datasets)

    assert evidence["accepted"], evidence
    assert evidence["checks"]["external_vision_position_fused_after_gnss_loss"]
    assert evidence["checks"]["external_vision_velocity_control_active_after_gnss_loss"]
    assert evidence["checks"]["gnss_fusion_stopped"]
    assert evidence["checks"]["no_inertial_dead_reckoning_after_switch"]
    assert evidence["metrics"]["switch_timestamp_s"] == 30.0
    assert evidence["metrics"]["external_vision_position_fused_samples_after_switch"] == 3
    assert evidence["metrics"]["local_origin_reset_delta_m"] > 4.0


def test_fusion_evidence_rejects_a_parameter_only_claim_without_actual_ev_fusion():
    datasets = {
        "estimator_status_flags": {
            "timestamp": [10_000_000, 20_000_000],
            "cs_ev_pos": [False, False],
            "cs_ev_vel": [False, False],
            "cs_gnss_pos": [True, False],
            "cs_gnss_vel": [True, False],
            "cs_inertial_dead_reckoning": [False, True],
        },
        "estimator_aid_src_ev_pos": {
            "timestamp": [20_000_000],
            "fused": [False],
            "innovation_rejected": [True],
        },
        "estimator_aid_src_gnss_pos": {"timestamp": [10_000_000], "fused": [True]},
        "estimator_aid_src_gnss_vel": {"timestamp": [10_000_000], "fused": [True]},
        "vehicle_visual_odometry": {"timestamp": [20_000_000]},
        "vehicle_local_position": {
            "timestamp": [10_000_000, 20_000_000],
            "xy_reset_counter": [1, 1],
            "delta_xy[0]": [0.0, 0.0],
            "delta_xy[1]": [0.0, 0.0],
            "xy_valid": [True, False],
            "v_xy_valid": [True, False],
        },
    }

    evidence = summarize_fusion_evidence(datasets)

    assert not evidence["accepted"]
    assert not evidence["checks"]["external_vision_position_fused_after_gnss_loss"]
