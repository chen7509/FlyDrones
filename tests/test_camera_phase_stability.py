import copy
import json

import pytest

from flydrones.camera_phase_stability import (
    formal_schedule,
    score_phase_campaign,
    score_phase_trial,
    smoke_schedule,
)
from tools.run_camera_phase_stability_campaign_wsl import (
    build_campaign_manifest,
    calculate_frozen_hashes,
    execute_campaign,
    validate_existing_campaign,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _config():
    return {
        "schema": "flydrones-camera-phase-stability-config-v1",
        "seed": 240901,
        "thresholds": {
            "tail_p99_ms_max": 100.0,
            "tail_max_ms_exclusive": 250.0,
            "rtf_min": 0.95,
            "frequency_hz_min": 9.5,
            "frequency_hz_max": 10.5,
            "phase_error_p95_ms_max": 8.0,
            "spacing_median_error_ms_max": 8.0,
            "sustained_degradation_ms": 5.0,
            "negative_pair_count_min": 4,
            "paired_tail_max_median_delta_ms_max": -5.0,
            "tail_p99_median_degradation_ms_max": 2.0,
            "rtf_median_degradation_max": 0.01,
        },
        "formal_schedule": [item.as_dict() for item in formal_schedule({})],
        "expected_hashes": {"launcher": "launcher-sha"},
    }


def _trial(mode="phased", pair_id=1, pair_position=2, tail_max=70.0, p99=30.0, rtf=0.98):
    name = f"camera-phase-pair-{pair_id}-{pair_position}-{mode}"
    frozen = {"policy": "p", "profile": "f", "camera_phase": "c"}
    manifest = {
        "schema": "flydrones-vio-stress-trial-v3",
        "name": name,
        "fleet_size": 5,
        "seed": 240901,
        "campaign_id": "formal-a",
        "repository_revision": "repo",
        "controller_revision": "repo",
        "px4_revision": "px4",
        "software_versions": {"gazebo": "8.15.0"},
        "frozen_hashes": frozen,
        "pair": {"id": pair_id, "position": pair_position},
        "renderer": {
            "requested_profile": "d3d12-nvidia",
            "attestation": {"accepted": True, "requested_profile": "d3d12-nvidia"},
        },
        "camera_schedule_mode": mode,
        "camera_scheduler_stop_after_trigger_count": None,
        "camera_model_evidence": {
            "schema": "flydrones-camera-model-phase-v1",
            "mode": mode,
        },
        "camera_phase_probe_closed_cleanly": True,
        "camera_scheduler_closed_cleanly": True,
        "evidence_accepted": True,
        "raw_artifact_sha256": {"camera-phase.jsonl": "abc"},
    }
    phase = {
        "schema": "flydrones-camera-phase-summary-v1",
        "mode": mode,
        "vehicle_count": 5,
        "accepted": True,
        "reasons": [],
        "target_offsets_ns": [0, 20_000_000, 40_000_000, 60_000_000, 80_000_000]
        if mode == "phased" else [0, 0, 0, 0, 0],
        "vehicles": {
            str(vehicle_id): {
                "mean_frequency_hz": 10.0,
                "phase_error_p95_ns": 4_000_000 if mode == "phased" else 0,
            }
            for vehicle_id in range(5)
        },
        "adjacent_spacing_median_error_ns": {
            f"{vehicle_id}-{(vehicle_id + 1) % 5}": 4_000_000
            for vehicle_id in range(5)
        } if mode == "phased" else {},
        "missed_trigger_count": 0,
        "queue_overflow_count": 0,
        "duplicate_trigger_count": 0,
        "duplicate_image_count": 0,
        "unmatched_trigger_count": 0,
        "unmatched_image_count": 0,
        "cross_model_error_count": 0,
        "max_simultaneous_cameras_10ms": 1 if mode == "phased" else 5,
    }
    workers = [
        {
            "mission_accepted": True,
            "landed": True,
            "state_health_failures": 0,
            "fail_closed_land": False,
            "gnss_disable_injected": True,
        }
        for _ in range(5)
    ]
    summary = {
        "schema": "flydrones-vio-stress-summary-v6",
        "name": name,
        "fleet_size": 5,
        "workers": workers,
        "geometry_separation_check_pass": True,
        "geometry_forest_clearance_check_pass": True,
        "external_vision_health_by_vehicle": {
            str(i): {"accepted": True} for i in range(5)
        },
        "post_gnss_evidence_by_vehicle": {
            str(i): {"accepted": True} for i in range(5)
        },
        "all_takeoff_chains_proven": True,
        "takeoff_chain_by_vehicle": {
            str(i): {"accepted": True} for i in range(5)
        },
        "runtime": {
            "accepted": True,
            "startup_reliability_pass": True,
            "raw_vio_by_vehicle": {
                str(i): {
                    "steady_state_valid": True,
                    "steady_state": {"p99_ms": p99, "max_ms": tail_max},
                }
                for i in range(5)
            },
            "clock": {
                "steady_state_valid": True,
                "steady_state": {"p99_ms": p99 - 1, "max_ms": tail_max - 1},
            },
            "rtf": {"steady_state": rtf},
        },
        "trial_cleanup_verified": True,
        "operational_continuity_pass": True,
        "camera_phase": phase,
    }
    return manifest, summary


def test_smoke_and_formal_schedules_are_exact_and_alternating():
    assert [(run.camera_schedule_mode, run.fleet_size) for run in smoke_schedule()] == [
        ("phased", 1),
        ("simultaneous", 5),
        ("phased", 5),
    ]
    schedule = formal_schedule({})
    assert len(schedule) == 10
    assert all(run.renderer_profile == "d3d12-nvidia" and run.fleet_size == 5 for run in schedule)
    assert [run.camera_schedule_mode for run in schedule] == [
        "simultaneous", "phased", "phased", "simultaneous", "simultaneous",
        "phased", "phased", "simultaneous", "simultaneous", "phased",
    ]
    assert {run.pair_id for run in schedule} == {1, 2, 3, 4, 5}


def test_versioned_camera_phase_config_hashes_every_changed_source():
    path = ROOT / "configs/vio_camera_phase_stability.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    actual = calculate_frozen_hashes(
        path, ROOT / config["profile"], ROOT / config["policy"]
    )

    assert config["expected_hashes"]
    assert {key: actual[key] for key in config["expected_hashes"]} == config["expected_hashes"]
    assert {
        "campaign_runner", "camera_phase_stability", "trial_runner", "launcher",
        "stopper", "camera_phase", "camera_model_configurator",
        "camera_phase_scheduler", "camera_phase_probe", "summary", "snapshot",
    }.issubset(config["expected_hashes"])


def test_single_trial_requires_phase_evidence_and_rejects_formal_fault_injection():
    manifest, summary = _trial()
    assert score_phase_trial(manifest, summary, _config())["passed"]

    missing = copy.deepcopy(summary)
    missing.pop("camera_phase")
    result = score_phase_trial(manifest, missing, _config())
    assert "camera_phase_summary_missing" in result["failures"]

    injected = copy.deepcopy(manifest)
    injected["camera_scheduler_stop_after_trigger_count"] = 3
    assert "formal_auxiliary_fault_injection" in score_phase_trial(
        injected, summary, _config()
    )["failures"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda phase: phase["vehicles"]["2"].update(mean_frequency_hz=9.4), "camera_frequency_out_of_range"),
        (lambda phase: phase["vehicles"]["2"].update(phase_error_p95_ns=8_000_001), "camera_phase_error_p95_exceeded"),
        (lambda phase: phase["adjacent_spacing_median_error_ns"].update({"2-3": 8_000_001}), "camera_spacing_error_exceeded"),
        (lambda phase: phase.update(unmatched_image_count=1), "camera_phase_integrity_error"),
    ],
)
def test_phased_hard_gates_are_independently_enforced(mutation, reason):
    manifest, summary = _trial()
    mutation(summary["camera_phase"])
    assert reason in score_phase_trial(manifest, summary, _config())["failures"]


def _formal_trials(*, improved=True):
    trials = []
    for run in formal_schedule({}):
        tail = 80.0 if run.camera_schedule_mode == "simultaneous" else (70.0 if improved else 80.0)
        p99 = 30.0 if run.camera_schedule_mode == "simultaneous" else 31.0
        trials.append(_trial(
            run.camera_schedule_mode,
            run.pair_id,
            run.pair_position,
            tail_max=tail,
            p99=p99,
            rtf=0.98,
        ))
    return trials


def test_campaign_has_supported_operational_unproven_and_rejected_verdicts():
    supported = score_phase_campaign(_formal_trials(improved=True), _config())
    assert supported["verdict"] == "supported"
    assert supported["negative_tail_max_pairs"] == 5
    assert supported["paired_tail_max_median_delta_ms"] == -10.0

    unproven = score_phase_campaign(_formal_trials(improved=False), _config())
    assert unproven["verdict"] == "operational_but_not_proven"

    rejected_trials = _formal_trials(improved=True)
    rejected_trials[1][1]["camera_phase"]["accepted"] = False
    rejected = score_phase_campaign(rejected_trials, _config())
    assert rejected["verdict"] == "rejected"


def test_campaign_detects_three_run_phased_tail_degradation():
    trials = _formal_trials(improved=True)
    phased = [trial for trial in trials if trial[0]["camera_schedule_mode"] == "phased"]
    for trial, tail in zip(phased[:3], (70.0, 73.0, 76.0)):
        for vehicle in trial[1]["runtime"]["raw_vio_by_vehicle"].values():
            vehicle["steady_state"]["max_ms"] = tail
        trial[1]["runtime"]["clock"]["steady_state"]["max_ms"] = tail - 1
    result = score_phase_campaign(trials, _config())
    assert not result["phased_no_sustained_degradation"]
    assert result["verdict"] == "operational_but_not_proven"


def test_campaign_enforces_p99_and_rtf_median_degradation_limits():
    p99_trials = _formal_trials(improved=True)
    for manifest, summary in p99_trials:
        if manifest["camera_schedule_mode"] == "phased":
            for vehicle in summary["runtime"]["raw_vio_by_vehicle"].values():
                vehicle["steady_state"]["p99_ms"] = 32.1
            summary["runtime"]["clock"]["steady_state"]["p99_ms"] = 31.1
    p99 = score_phase_campaign(p99_trials, _config())
    assert p99["tail_p99_median_degradation_ms"] > 2.0
    assert p99["verdict"] == "operational_but_not_proven"

    rtf_trials = _formal_trials(improved=True)
    for manifest, summary in rtf_trials:
        if manifest["camera_schedule_mode"] == "phased":
            summary["runtime"]["rtf"]["steady_state"] = 0.969
    rtf = score_phase_campaign(rtf_trials, _config())
    assert rtf["rtf_median_degradation"] > 0.01
    assert rtf["verdict"] == "operational_but_not_proven"


def test_simultaneous_trend_is_reported_without_rejecting_supported_phased_result():
    trials = _formal_trials(improved=True)
    simultaneous = [
        trial for trial in trials if trial[0]["camera_schedule_mode"] == "simultaneous"
    ]
    for trial, tail in zip(simultaneous[:3], (80.0, 86.0, 92.0)):
        for vehicle in trial[1]["runtime"]["raw_vio_by_vehicle"].values():
            vehicle["steady_state"]["max_ms"] = tail
        trial[1]["runtime"]["clock"]["steady_state"]["max_ms"] = tail - 1

    result = score_phase_campaign(trials, _config())

    assert not result["simultaneous_no_sustained_degradation"]
    assert result["verdict"] == "supported"


@pytest.mark.parametrize("mutation", ["thresholds", "hashes", "schedule", "mode"])
def test_existing_campaign_rejects_frozen_drift(tmp_path, mutation):
    expected = build_campaign_manifest(
        campaign_id="formal-a", phase="formal", config=_config(),
        profile=tmp_path / "baseline.json", model=tmp_path / "policy.npz",
        controller_revision="rev", frozen_hashes={"runner": "hash"},
    )
    existing = copy.deepcopy(expected)
    if mutation == "thresholds":
        existing["thresholds"]["phase_error_p95_ms_max"] = 9.0
    elif mutation == "hashes":
        existing["frozen_hashes"]["runner"] = "other"
    elif mutation == "schedule":
        existing["schedule"] = existing["schedule"][:-1]
    else:
        existing["schedule"][0]["camera_schedule_mode"] = "phased"
    with pytest.raises(RuntimeError, match="frozen campaign manifest mismatch"):
        validate_existing_campaign(existing, expected)


def test_formal_execution_stops_after_any_failed_trial_and_preserves_it(tmp_path):
    calls = []
    campaign_dir = tmp_path / "formal-a"

    def fake_run_trial(**kwargs):
        calls.append(kwargs)
        trial_dir = kwargs["output_root"] / kwargs["name"]
        trial_dir.mkdir(parents=True)
        manifest, summary = _trial(
            kwargs["camera_schedule_mode"], kwargs["pair_id"], kwargs["pair_position"]
        )
        manifest["name"] = kwargs["name"]
        summary["name"] = kwargs["name"]
        (trial_dir / "trial-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (trial_dir / "stress-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return manifest

    result = execute_campaign(
        campaign_id="formal-a", phase="formal", profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz", campaign_dir=campaign_dir, config=_config(),
        controller_revision="rev", frozen_hashes={"runner": "hash"},
        run_trial_fn=fake_run_trial,
        summarize_trial_fn=lambda path: json.loads((path / "stress-summary.json").read_text()),
        resources_free_fn=lambda: True,
        trial_score_fn=lambda _m, _s, _c: {"passed": False, "failures": ["phase_failed"]},
    )
    assert len(calls) == 1
    assert result["stopped_after"] == formal_schedule({})[0].name
    assert (campaign_dir / calls[0]["name"] / "trial-manifest.json").is_file()


def test_resume_only_accepts_complete_matching_trial(tmp_path):
    campaign_dir = tmp_path / "formal-a"
    campaign_dir.mkdir()
    expected = build_campaign_manifest(
        campaign_id="formal-a", phase="formal", config=_config(),
        profile=tmp_path / "baseline.json", model=tmp_path / "policy.npz",
        controller_revision="rev", frozen_hashes={"runner": "hash"},
    )
    (campaign_dir / "campaign-manifest.json").write_text(json.dumps(expected), encoding="utf-8")
    first = formal_schedule({})[0]
    trial_dir = campaign_dir / first.name
    trial_dir.mkdir()
    (trial_dir / "trial-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete"):
        execute_campaign(
            campaign_id="formal-a", phase="formal", profile=tmp_path / "baseline.json",
            model=tmp_path / "policy.npz", campaign_dir=campaign_dir, config=_config(),
            controller_revision="rev", frozen_hashes={"runner": "hash"},
            resources_free_fn=lambda: True,
        )
