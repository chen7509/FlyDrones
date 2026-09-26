import copy

import pytest

from flydrones.renderer_stability import campaign_schedule, score_campaign
from tools.summarize_renderer_stability import load_campaign

EXPECTED_PROFILES = (
    "default",
    "d3d12-nvidia",
    "d3d12-nvidia",
    "default",
    "default",
    "d3d12-nvidia",
    "d3d12-nvidia",
    "default",
    "default",
    "d3d12-nvidia",
)


def _trial(item):
    attestation = {
        "schema": "flydrones-gazebo-renderer-attestation-v1",
        "accepted": True,
        "requested_profile": item.renderer_profile,
        "reasons": [],
    }
    manifest = {
        "schema": "flydrones-vio-stress-trial-v3",
        "name": item.name,
        "fleet_size": 5,
        "seed": 240901,
        "campaign_id": "formal-a",
        "repository_revision": "repo-sha",
        "controller_revision": "repo-sha",
        "px4_revision": "px4-sha",
        "frozen_hashes": {"world": "world", "policy": "policy", "controller": "controller"},
        "software_versions": {"gazebo": "8.9.0", "mesa": "25.2.8"},
        "renderer": {"requested_profile": item.renderer_profile, "attestation": attestation},
        "pair": {"id": item.pair_id, "position": item.pair_position},
        "evidence_accepted": True,
        "raw_artifact_sha256": {"agent-0.csv": "sha"},
    }
    workers = [
        {
            "vehicle_id": vehicle_id,
            "mission_accepted": True,
            "landed": True,
            "fail_closed_land": False,
            "state_health_failures": 0,
            "gnss_disable_injected": True,
        }
        for vehicle_id in range(5)
    ]
    raw = {
        str(vehicle_id): {
            "steady_state_valid": True,
            "steady_state": {"p99_ms": 30.0, "max_ms": 50.0},
        }
        for vehicle_id in range(5)
    }
    summary = {
        "schema": "flydrones-vio-stress-summary-v6",
        "name": item.name,
        "fleet_size": 5,
        "renderer": manifest["renderer"],
        "workers": workers,
        "external_vision_health_by_vehicle": {
            str(vehicle_id): {"accepted": True} for vehicle_id in range(5)
        },
        "post_gnss_evidence_by_vehicle": {
            str(vehicle_id): {"accepted": True} for vehicle_id in range(5)
        },
        "takeoff_chain_by_vehicle": {
            str(vehicle_id): {"accepted": True, "reason": None, "landed": True}
            for vehicle_id in range(5)
        },
        "all_takeoff_chains_proven": True,
        "runtime": {
            "accepted": True,
            "startup_reliability_pass": True,
            "raw_vio_by_vehicle": raw,
            "clock": {
                "steady_state_valid": True,
                "steady_state": {"p99_ms": 25.0, "max_ms": 45.0},
            },
            "rtf": {"steady_state": 1.0},
        },
        "geometry_separation_check_pass": True,
        "geometry_forest_clearance_check_pass": True,
        "trial_cleanup_verified": True,
        "operational_continuity_pass": True,
    }
    return manifest, summary


def _passing_campaign():
    return [_trial(item) for item in campaign_schedule()]


def test_schedule_is_exactly_the_approved_five_ab_ba_pairs():
    schedule = campaign_schedule()

    assert len(schedule) == 10
    assert tuple(item.renderer_profile for item in schedule) == EXPECTED_PROFILES
    assert sum(item.renderer_profile == "default" for item in schedule) == 5
    assert sum(item.renderer_profile == "d3d12-nvidia" for item in schedule) == 5
    assert [(item.pair_id, item.pair_position) for item in schedule] == [
        (pair_id, position) for pair_id in range(1, 6) for position in (1, 2)
    ]
    assert all(
        item.name == (
            f"renderer-pair-{item.pair_id}-{item.pair_position}-{item.renderer_profile}"
        )
        for item in schedule
    )


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "profile", "seed", "hash"])
def test_campaign_rejects_schedule_or_frozen_input_drift(mutation):
    trials = _passing_campaign()
    if mutation == "duplicate":
        trials[1][0]["name"] = trials[0][0]["name"]
    elif mutation == "missing":
        trials.pop()
    elif mutation == "profile":
        trials[1][0]["renderer"]["requested_profile"] = "default"
    elif mutation == "seed":
        trials[2][0]["seed"] = 7
    else:
        trials[4][0]["frozen_hashes"]["world"] = "changed"

    result = score_campaign(trials)

    assert not result["formal_artifacts_complete"]
    assert not result["d3d12_stability_gate_pass"]
    assert result["validation_failures"]


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("mission", "mission_count_not_5"),
        ("landing", "landing_count_not_5"),
        ("clearance", "safety_geometry_failed"),
        ("vio_gate", "normal_run_vio_gate_triggered"),
        ("ulog", "per_vehicle_external_vision_evidence_rejected"),
        ("post_gnss", "per_vehicle_post_gnss_evidence_rejected"),
        ("takeoff", "per_vehicle_takeoff_chain_rejected"),
        ("raw_max", "raw_vio_max_not_below_250_ms"),
        ("clock_max", "clock_max_not_below_250_ms"),
        ("p99", "tail_p99_above_100_ms"),
        ("rtf", "rtf_below_0_95"),
        ("cleanup", "cleanup_not_verified"),
    ],
)
def test_every_d3d12_hard_gate_is_fail_closed(mutation, expected_reason):
    trials = _passing_campaign()
    _manifest, summary = trials[1]
    if mutation == "mission":
        summary["workers"][4]["mission_accepted"] = False
    elif mutation == "landing":
        summary["workers"][4]["landed"] = False
    elif mutation == "clearance":
        summary["geometry_forest_clearance_check_pass"] = False
    elif mutation == "vio_gate":
        summary["workers"][0]["state_health_failures"] = 1
        summary["workers"][0]["fail_closed_land"] = True
    elif mutation == "ulog":
        summary["external_vision_health_by_vehicle"]["3"]["accepted"] = False
    elif mutation == "post_gnss":
        summary["post_gnss_evidence_by_vehicle"]["3"]["accepted"] = False
    elif mutation == "takeoff":
        summary["takeoff_chain_by_vehicle"]["3"].update({
            "accepted": False,
            "reason": "gazebo-motor-command-missing",
        })
        summary["all_takeoff_chains_proven"] = False
    elif mutation == "raw_max":
        summary["runtime"]["raw_vio_by_vehicle"]["2"]["steady_state"]["max_ms"] = 250.0
    elif mutation == "clock_max":
        summary["runtime"]["clock"]["steady_state"]["max_ms"] = 250.0
    elif mutation == "p99":
        summary["runtime"]["raw_vio_by_vehicle"]["1"]["steady_state"]["p99_ms"] = 100.1
    elif mutation == "rtf":
        summary["runtime"]["rtf"]["steady_state"] = 0.949
    else:
        summary["trial_cleanup_verified"] = False

    result = score_campaign(trials)

    assert not result["d3d12_stability_gate_pass"]
    failed = next(item for item in result["trials"] if item["name"] == trials[1][0]["name"])
    assert expected_reason in failed["failures"]


def test_default_failure_is_preserved_without_erasing_a_passing_d3d12_gate():
    trials = _passing_campaign()
    trials[0][1]["workers"][0]["mission_accepted"] = False

    result = score_campaign(trials)

    assert result["d3d12_stability_gate_pass"]
    assert "mission_count_not_5" in result["trials"][0]["failures"]
    assert len(result["pairs"]) == 5
    assert all(set(pair["deltas"]) == {"tail_p99_ms", "tail_max_ms", "rtf", "mission_count"}
               for pair in result["pairs"])
    assert len(result["renderer_aggregates"]["d3d12-nvidia"]["tail_p99_ms"]) == 5


def test_rejected_renderer_attestation_is_a_recorded_d3d12_failure():
    trials = _passing_campaign()
    trials[1][0]["renderer"]["attestation"]["accepted"] = False
    trials[1][0]["renderer"]["attestation"]["reasons"] = ["d3d12_not_active"]

    result = score_campaign(copy.deepcopy(trials))

    assert not result["d3d12_stability_gate_pass"]
    assert "renderer_attestation_rejected" in result["trials"][1]["failures"]


def test_legacy_v2_manifest_is_explicitly_rejected_for_missing_takeoff_chain():
    manifest, summary = _trial(campaign_schedule()[0])
    manifest["schema"] = "flydrones-vio-stress-trial-v2"
    summary.pop("takeoff_chain_by_vehicle")
    summary["all_takeoff_chains_proven"] = False

    result = score_campaign([(manifest, summary)] + _passing_campaign()[1:])

    assert "legacy_takeoff_evidence" in result["trials"][0]["failures"]


def test_campaign_loader_preserves_all_ten_slots_when_artifacts_are_missing(tmp_path):
    trials = load_campaign(tmp_path)

    assert len(trials) == 10
    result = score_campaign(trials)
    assert not result["formal_artifacts_complete"]
    assert not result["d3d12_stability_gate_pass"]


def test_three_consecutive_worsening_d3d12_tails_fail_the_trend_gate():
    trials = _passing_campaign()
    d3d12_indices = [1, 2, 5, 6, 9]
    for trial_index, p99 in zip(d3d12_indices, (30.0, 40.0, 50.0, 50.0, 50.0)):
        for vehicle in trials[trial_index][1]["runtime"]["raw_vio_by_vehicle"].values():
            vehicle["steady_state"]["p99_ms"] = p99

    result = score_campaign(trials)

    assert not result["d3d12_no_sustained_degradation"]
    assert not result["d3d12_stability_gate_pass"]
    assert "d3d12_sustained_tail_degradation" in result["campaign_failures"]
