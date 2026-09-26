import pytest

from tools.summarize_vio_stress_wsl import (
    _manifest_frozen_hash,
    _relay_metrics,
    classify_trial,
    summarize_runtime_evidence,
    verify_command_gate,
    verify_px4_land_transition,
)


def test_summary_reads_hashes_from_v2_frozen_hashes_and_keeps_v1_compatibility():
    assert _manifest_frozen_hash({"frozen_hashes": {"profile": "v2"}}, "profile") == "v2"
    assert _manifest_frozen_hash({"profile_sha256": "v1"}, "profile") == "v1"
    assert _manifest_frozen_hash({}, "profile") is None


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
        "post_gnss_evidence_by_vehicle": {
            str(vehicle_id): {"accepted": True} for vehicle_id in range(5)
        },
        "workers": [
            {"mission_accepted": True, "landed": True, "fail_closed_land": False,
             "gnss_disable_injected": True}
            for _ in range(5)
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


def test_dropout_uses_source_sim_time_gap_when_five_vehicle_simulation_slows():
    trial = _trial()
    trial["relay"].update(
        drop_reasons={"scheduled-dropout": 11},
        fault_vehicle_active_source_max_gap_ms=240,
    )
    trial["visual_after_gnss_disable"]["metrics"]["visual_stream_max_gap_ms"] = 244
    profile = {"delay_ms": 0, "dropout_duration_s": 0.4,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]}

    assert classify_trial(trial, profile)["fault_effect_proven_at_px4"]
    trial["visual_after_gnss_disable"]["metrics"]["visual_stream_max_gap_ms"] = 100
    assert not classify_trial(trial, profile)["fault_effect_proven_at_px4"]


def test_correlated_gate_and_px4_land_sequence_is_not_claimed_as_command_causality():
    trial = _trial()
    trial["worker_exit_code"] = 2
    trial["relay"].update(drop_reasons={"scheduled-dropout": 11},
                          fault_vehicle_active_source_max_gap_ms=240)
    trial["visual_after_gnss_disable"]["metrics"]["visual_stream_max_gap_ms"] = 244
    trial["workers"][0].update(mission_accepted=False, fail_closed_land=True,
                               command_gate={"verified": True},
                               px4_land_transition={"observed": True})
    profile = {"delay_ms": 0, "dropout_duration_s": 0.4,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]}

    result = classify_trial(trial, profile)
    assert result["fault_vehicle_gate_land_sequence_observed"]
    assert not result["fault_vehicle_verified_fail_closed_response"]


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


def test_operational_pass_requires_post_gnss_evidence_for_every_vehicle():
    trial = _trial()
    profile = {"delay_ms": 0, "dropout_duration_s": 0,
               "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]}

    trial["post_gnss_evidence_by_vehicle"]["4"]["accepted"] = False
    assert not classify_trial(trial, profile)["operational_continuity_pass"]

    trial = _trial()
    trial["workers"][4]["gnss_disable_injected"] = False
    assert not classify_trial(trial, profile)["operational_continuity_pass"]


def test_partial_relay_log_remains_scored_as_incomplete(tmp_path):
    path = tmp_path / "vio-relay.jsonl"
    path.write_text('{"event": "start"}\n{"event": "publish"', encoding="utf-8")
    metrics, _raw, _published = _relay_metrics(path, 1)
    assert metrics["malformed_log_lines"] == 1
    assert not metrics["closed_cleanly"]


def test_command_gate_requires_relay_gap_no_later_setpoints_and_prompt_land_request():
    rows = [
        {"monotonic_s": "10.20", "command_sent": "True", "command_sent_at_s": "10.20",
         "vision_age_at_send_s": "0.20", "phase": "escaping"},
        {"monotonic_s": "10.30", "command_sent": "False", "phase": "fail_closed"},
    ]
    metrics = {
        "last_state_health_reason": "stale-vio-frame",
        "fail_closed_triggered_at_s": 10.30,
        "last_command_sent_at_s": 10.20,
        "land_command_at_s": 10.31,
        "land_request_sent": True,
    }
    publishes = [
        {"model": "x500_depth_fly_0", "received_at": 10.00, "published_at": 10.01},
        {"model": "x500_depth_fly_0", "received_at": 10.43, "published_at": 10.44},
    ]

    evidence = verify_command_gate(rows, metrics, publishes)
    assert evidence["verified"]
    assert evidence["relay_gap_covering_trigger_s"] == 0.43
    rows[1]["command_sent"] = "True"
    assert not verify_command_gate(rows, metrics, publishes)["verified"]
    rows[1]["command_sent"] = "False"
    rows[0]["vision_age_at_send_s"] = "0.26"
    assert not verify_command_gate(rows, metrics, publishes)["verified"]
    rows[0]["vision_age_at_send_s"] = "0.20"
    metrics["land_request_sent"] = False
    assert not verify_command_gate(rows, metrics, publishes)["verified"]


def test_px4_land_transition_must_follow_the_correlated_gate_time():
    relay_clock = [(10.29, 22.985), (10.30, 22.995), (10.31, 23.005)]
    status = {"timestamp": [22_800_000, 22_996_000, 23_008_000, 23_270_000],
              "nav_state": [14, 14, 18, 18]}

    evidence = verify_px4_land_transition(10.30, relay_clock, status)
    assert evidence["observed"]
    assert evidence["transition_after_gate_s"] == 0.013
    status["nav_state"] = [18, 18, 18, 18]
    assert not verify_px4_land_transition(10.30, relay_clock, status)["observed"]


def test_runtime_evidence_separates_startup_tail_and_computes_rtf(tmp_path):
    (tmp_path / "clock-probe.csv").write_text(
        "monotonic_s,sim_ns,wall_gap_ms,sim_gap_ms,seen\n"
        "1.0,0,0,0,1\n"
        "1.6,600000000,600,600,2\n"
        "10.0,9000000000,20,20,3\n"
        "11.0,10000000000,20,1000,4\n",
        encoding="utf-8",
    )
    (tmp_path / "resource-probe.csv").write_text(
        "monotonic_s,pid,cpu_user_s,cpu_system_s,rss_bytes,threads\n10.0,1,2,1,1000,8\n",
        encoding="utf-8",
    )
    (tmp_path / "gpu-probe.csv").write_text(
        "monotonic_s,gpu_utilization_percent,memory_used_mib\n10.0,unavailable,unavailable\n",
        encoding="utf-8",
    )
    raw = {
        "x500_depth_fly_0": [(1.0, [0, 0, 0]), (1.6, [0, 0, 0]), (10.0, [0, 0, 0]), (10.02, [0, 0, 0])],
        **{
            f"x500_depth_fly_{vehicle_id}": [(10.0, [0, 0, 0]), (10.02, [0, 0, 0])]
            for vehicle_id in range(1, 5)
        },
    }
    worker_rows = [[{"monotonic_s": "10.0", "state_healthy": "True", "phase": "escaping"}]
                   for _ in range(5)]

    evidence = summarize_runtime_evidence(tmp_path, raw=raw, worker_rows=worker_rows, fleet_size=5)

    assert evidence["accepted"]
    assert evidence["steady_state_epoch_monotonic_s"] == 10.0
    assert evidence["clock"]["full_run"]["max_ms"] == 600.0
    assert evidence["clock"]["steady_state"]["max_ms"] == 20.0
    assert evidence["raw_vio_by_vehicle"]["0"]["full_run"]["max_ms"] == 8400.0
    assert evidence["raw_vio_by_vehicle"]["0"]["steady_state"]["max_ms"] == pytest.approx(20.0)
    assert evidence["rtf"]["full_run"] == pytest.approx(1.0)
    assert evidence["rtf"]["steady_state"] == pytest.approx(1.0)
    assert evidence["gpu_metrics_available"] is False


def test_missing_probe_evidence_is_not_silently_accepted(tmp_path):
    evidence = summarize_runtime_evidence(tmp_path, raw={}, worker_rows=[], fleet_size=5)

    assert not evidence["accepted"]
    assert "clock-probe.csv missing" in evidence["errors"]
    assert "steady-state epoch unavailable" in evidence["errors"]


def test_probe_rows_before_shared_epoch_do_not_count_as_steady_state(tmp_path):
    (tmp_path / "clock-probe.csv").write_text(
        "monotonic_s,sim_ns,wall_gap_ms,sim_gap_ms,seen\n1.0,0,0,0,1\n1.1,100000000,100,100,2\n",
        encoding="utf-8",
    )
    (tmp_path / "resource-probe.csv").write_text(
        "monotonic_s,pid,cpu_user_s,cpu_system_s,rss_bytes,threads\n1.0,1,2,1,1000,8\n",
        encoding="utf-8",
    )
    (tmp_path / "gpu-probe.csv").write_text(
        "monotonic_s,gpu_utilization_percent,memory_used_mib\n1.0,unavailable,unavailable\n",
        encoding="utf-8",
    )
    raw = {
        f"x500_depth_fly_{vehicle_id}": [(1.0, [0, 0, 0]), (1.1, [0, 0, 0])]
        for vehicle_id in range(5)
    }
    worker_rows = [[{"monotonic_s": "10.0", "state_healthy": "True", "phase": "escaping"}]
                   for _ in range(5)]

    evidence = summarize_runtime_evidence(tmp_path, raw=raw, worker_rows=worker_rows, fleet_size=5)

    assert not evidence["accepted"]
    assert "steady-state clock gaps missing" in evidence["errors"]
    assert "steady-state raw VIO gaps missing for vehicle 0" in evidence["errors"]


def test_successful_steady_metrics_cannot_hide_startup_failure():
    trial = _trial()
    trial["launch_exit_code"] = 3
    trial["runtime"] = {"accepted": True, "startup_reliability_pass": False}
    result = classify_trial(
        trial,
        {"delay_ms": 0, "dropout_duration_s": 0, "drift_mps": [0, 0, 0], "false_pose_offset_m": [0, 0, 0]},
    )

    assert not result["operational_continuity_pass"]


def test_missing_runtime_evidence_cannot_be_hidden_by_successful_mission():
    trial = _trial()
    trial["runtime"] = {"accepted": False, "startup_reliability_pass": False}

    result = classify_trial(
        trial,
        {"delay_ms": 0, "dropout_duration_s": 0, "drift_mps": [0, 0, 0],
         "false_pose_offset_m": [0, 0, 0]},
    )

    assert not result["operational_continuity_pass"]
