from tools.summarize_vio_stress_wsl import _relay_metrics, classify_trial


def _trial():
    return {
        "fleet_size": 5,
        "launch_exit_code": 0,
        "worker_exit_code": 0,
        "stop_exit_code": 0,
        "shared_px4_files_restored": True,
        "relay": {"fault_vehicle_active_published": 100, "drop_reasons": {}, "closed_cleanly": True,
                  "nonzero_offset_published_samples": 10,
                  "minimum_center_to_trunk_surface_m": 0.6,
                  "minimum_intervehicle_center_distance_m": 1.1},
        "relay_to_px4": {"matched_active_samples": 30, "matched_offset_samples": 0,
                         "median_ulog_minus_source_stamp_ms": 0},
        "visual_after_gnss_disable": {"accepted": True, "metrics": {"visual_stream_max_gap_ms": 30}},
        "workers": [{"mission_accepted": True, "landed": True, "fail_closed_land": False,
                     "gnss_disable_injected": True}] + [
                         {"mission_accepted": True, "landed": True, "fail_closed_land": False}
                         for _ in range(4)
                     ],
    }


def test_mission_success_does_not_hide_close_approach_or_bad_exit():
    trial = _trial()
    result = classify_trial(trial, {"delay_ms": 0, "dropout_duration_s": 0,
                                    "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]})
    assert result["operational_continuity_pass"]
    assert result["geometry_separation_check_pass"]
    assert result["geometry_forest_clearance_check_pass"]
    trial["relay"]["minimum_intervehicle_center_distance_m"] = 0.4282
    assert not classify_trial(trial, {"delay_ms": 0, "dropout_duration_s": 0,
                                      "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]})[
                                          "geometry_separation_check_pass"]
    trial["relay"]["minimum_intervehicle_center_distance_m"] = 1.1
    trial["relay"]["minimum_center_to_trunk_surface_m"] = 0.32
    assert not classify_trial(trial, {"delay_ms": 0, "dropout_duration_s": 0,
                                      "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]})[
                                          "operational_continuity_pass"]
    trial["worker_exit_code"] = 2
    assert not classify_trial(trial, {"delay_ms": 0, "dropout_duration_s": 0,
                                      "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]})[
                                          "operational_continuity_pass"]


def test_fault_must_be_exercised_and_safe_fail_closed_is_separate():
    trial = _trial()
    trial["workers"][0].update(mission_accepted=False, fail_closed_land=True)
    trial["worker_exit_code"] = 2
    profile = {"delay_ms": 0, "dropout_duration_s": 0,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [1, 0, 0]}
    result = classify_trial(trial, profile)
    assert not result["fault_effect_proven_at_px4"]
    assert result["fault_vehicle_fail_closed_landing_observed"]
    assert not result["fault_vehicle_verified_fail_closed_response"]
    assert not result["operational_continuity_pass"]
    trial["relay_to_px4"]["matched_offset_samples"] = 5
    assert classify_trial(trial, profile)["fault_effect_proven_at_px4"]
    assert not classify_trial(trial, profile)["fault_vehicle_verified_fail_closed_response"]


def test_delay_must_reach_px4_with_expected_source_age():
    trial = _trial()
    trial["relay"]["actual_delay_median_ms"] = 120
    profile = {"delay_ms": 120, "dropout_duration_s": 0,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]}
    assert not classify_trial(trial, profile)["fault_effect_proven_at_px4"]
    trial["relay_to_px4"]["median_ulog_minus_source_stamp_ms"] = 120
    assert classify_trial(trial, profile)["fault_effect_proven_at_px4"]


def test_cleanup_failure_cannot_be_operational_pass():
    trial = _trial()
    profile = {"delay_ms": 0, "dropout_duration_s": 0,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]}
    assert classify_trial(trial, profile)["operational_continuity_pass"]
    trial["shared_px4_files_restored"] = False
    result = classify_trial(trial, profile)
    assert result["mission_visual_geometry_pass"]
    assert not result["trial_cleanup_verified"]
    assert not result["operational_continuity_pass"]


def test_partial_relay_log_remains_scored_as_incomplete(tmp_path):
    path = tmp_path / "vio-relay.jsonl"
    path.write_text('{"event": "start"}\n{"event": "publish"', encoding="utf-8")
    metrics, _raw, _published = _relay_metrics(path, 1)
    assert metrics["malformed_log_lines"] == 1
    assert not metrics["closed_cleanly"]
