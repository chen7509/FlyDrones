from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from flydrones.camera_phase import TriggerSchedulerState
from flydrones.camera_render_capacity import (
    CapacityCell,
    CapacityThresholds,
    capacity_schedule,
    classify_capacity_campaign,
    score_capacity_run,
)

THRESHOLDS = {
    "min_rtf": 0.95,
    "min_image_hz": 9.5,
    "max_image_hz": 10.5,
    "max_phase_error_p95_ns": 8_000_000,
    "max_spacing_median_error_ns": 8_000_000,
    "scored_duration_s": 30.0,
    "wall_timeout_s": 120.0,
    "repeatability_rtf_range_max": 0.03,
    "native_improvement_min": 0.05,
}


def _config() -> dict:
    return {
        "schema": "flydrones-camera-render-capacity-config-v1",
        "thresholds": dict(THRESHOLDS),
        "schedule": [run.as_dict() for run in capacity_schedule()],
    }


def _good_pair(run, *, rtf: float = 0.97) -> tuple[dict, dict]:
    active = run.cell.subscriber_count
    manifest = {
        "schema": "flydrones-camera-render-capacity-manifest-v1",
        "name": run.name,
        "cell": run.cell.name,
        "repetition": run.repetition,
        "sequence": run.sequence,
        "subscriber_count": active,
        "observer_implementation": run.cell.implementation,
        "renderer_attestation_accepted": True,
        "px4_vehicle_count": 5,
        "px4_all_healthy": True,
        "px4_all_disarmed": True,
        "px4_all_landed": True,
        "scored_duration_sim_s": 30.0,
        "scored_wall_timeout_s": 120.0,
        "depth_subscription_count_start": active,
        "depth_subscription_count_end": active,
        "trigger_stream_count": 5,
        "source_hashes_match": True,
        "native_executable_hash_match": True,
        "observer_closed_cleanly": True,
        "scheduler_closed_cleanly": True,
        "stop_exit_code": 0,
        "launcher_exit_code": 0,
        "shared_px4_files_restored": True,
        "trial_cleanup_verified": True,
        "evidence_accepted": True,
        "ulog_artifacts": [
            {
                "vehicle_id": vehicle_id,
                "path": f"px4-ulogs/agent-{vehicle_id}.ulg",
                "bytes": 100,
                "sha256": f"{vehicle_id:064x}",
            }
            for vehicle_id in range(5)
        ],
    }
    vehicles = {
        str(vehicle_id): {
            "frequency_hz": 9.5 if vehicle_id == 0 else 10.5,
            "phase_error_p95_ns": 8_000_000,
            "width": 160,
            "height": 120,
            "format": "R_FLOAT32",
        }
        for vehicle_id in range(active)
    }
    summary = {
        "schema": "flydrones-camera-render-capacity-summary-v1",
        "runtime": {
            "rtf": {"scored_window": rtf},
            "resources": {"accepted": True, "gazebo": {"samples": 3}},
        },
        "camera_phase": {
            "accepted": active > 0,
            "vehicles": vehicles,
            "adjacent_spacing_median_error_ns": 8_000_000 if active == 5 else None,
            "missed_trigger_count": 0,
            "queue_overflow_count": 0,
            "duplicate_trigger_count": 0,
            "duplicate_image_count": 0,
            "unmatched_trigger_count": 0,
            "unmatched_image_count": 0,
            "cross_model_error_count": 0,
            "depth_subscription_absent": active == 0,
            "trigger_stream_count": 5,
        },
    }
    return manifest, summary


def _campaign_rtfs(*, idle: float, native_one: float, python: float, native: float):
    values = {"idle-0": idle, "native-1": native_one, "python-5": python, "native-5": native}
    return [_good_pair(run, rtf=values[run.cell.name]) for run in capacity_schedule()]


def test_capacity_schedule_is_exact_and_immutable():
    schedule = capacity_schedule()
    assert [run.cell.name for run in schedule] == [
        "idle-0", "native-1", "python-5", "native-5",
        "native-5", "python-5", "native-1", "idle-0",
        "python-5", "idle-0", "native-5", "native-1",
    ]
    assert [run.sequence for run in schedule] == list(range(1, 13))
    assert len({run.name for run in schedule}) == 12
    assert {(run.cell.name, run.cell.subscriber_count, run.cell.implementation) for run in schedule} == {
        ("idle-0", 0, "native-cpp"),
        ("native-1", 1, "native-cpp"),
        ("python-5", 5, "python"),
        ("native-5", 5, "native-cpp"),
    }
    assert {run.cell.name: run.repetition for run in schedule[-4:]} == {
        "python-5": 3,
        "idle-0": 3,
        "native-5": 3,
        "native-1": 3,
    }


def test_shared_phase_vectors_match_python_scheduler():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/camera_phase_vectors.json").read_text(encoding="utf-8")
    )
    state = TriggerSchedulerState(
        vehicle_count=fixture["vehicle_count"],
        epoch_ns=fixture["epoch_ns"],
        dispatch_delay_ns=fixture["dispatch_delay_ns"],
    )
    for vector in fixture["vectors"]:
        slots = state.advance(vector["sim_ns"])
        assert [slot.vehicle_id for slot in slots] == vector["expected_vehicle_ids"], vector["name"]
        assert [slot.planned_sim_ns for slot in slots] == vector["expected_planned_ns"], vector["name"]
        assert [slot.vehicle_id for slot in state.last_missed_slots] == vector["expected_missed_vehicle_ids"], vector["name"]


def test_capacity_cell_rejects_unknown_identity_and_invalid_numeric_types():
    with pytest.raises(ValueError, match="cell name"):
        CapacityCell("other", 5, "native-cpp")
    with pytest.raises(ValueError, match="subscriber_count"):
        CapacityCell("native-5", True, "native-cpp")
    with pytest.raises(ValueError, match="implementation"):
        CapacityCell("native-5", 5, "rust")


def test_thresholds_accept_exact_frozen_values_and_reject_relaxed_or_non_finite_values():
    thresholds = CapacityThresholds.from_mapping(THRESHOLDS)
    assert thresholds.min_rtf == 0.95
    assert thresholds.min_image_hz == 9.5
    assert thresholds.max_image_hz == 10.5
    assert thresholds.max_phase_error_p95_ns == 8_000_000
    assert thresholds.max_spacing_median_error_ns == 8_000_000
    assert thresholds.scored_duration_s == 30.0
    assert thresholds.wall_timeout_s == 120.0
    assert thresholds.repeatability_rtf_range_max == 0.03
    assert thresholds.native_improvement_min == 0.05

    for key, value in {
        "min_rtf": 0.94,
        "min_image_hz": 9.4,
        "max_image_hz": 10.6,
        "max_phase_error_p95_ns": 8_000_001,
        "max_spacing_median_error_ns": 8_000_001,
        "scored_duration_s": 29.0,
        "wall_timeout_s": 121.0,
        "repeatability_rtf_range_max": 0.031,
        "native_improvement_min": 0.049,
    }.items():
        changed = dict(THRESHOLDS)
        changed[key] = value
        with pytest.raises(ValueError, match=key):
            CapacityThresholds.from_mapping(changed)

    for bad in (True, math.nan, math.inf):
        changed = dict(THRESHOLDS)
        changed["min_rtf"] = bad
        with pytest.raises(ValueError, match="min_rtf"):
            CapacityThresholds.from_mapping(changed)


@pytest.mark.parametrize("cell_name", ["idle-0", "native-1", "python-5", "native-5"])
def test_good_capacity_run_has_valid_evidence_and_passes_performance(cell_name):
    run = next(run for run in capacity_schedule() if run.cell.name == cell_name)
    manifest, summary = _good_pair(run)
    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))
    assert result["evidence_valid"] is True
    assert result["performance_pass"] is True
    assert result["failures"] == []


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda m, s: m.update(renderer_attestation_accepted=False), "renderer_attestation_rejected"),
        (lambda m, s: m.update(px4_all_healthy=False), "px4_health_invalid"),
        (lambda m, s: m.update(px4_all_disarmed=False), "px4_not_disarmed"),
        (lambda m, s: m.update(px4_all_landed=False), "px4_not_landed"),
        (lambda m, s: m.update(scored_duration_sim_s=29.999), "scored_duration_incomplete"),
        (lambda m, s: m.update(depth_subscription_count_end=4), "subscriber_count_mismatch"),
        (lambda m, s: m.update(trigger_stream_count=4), "trigger_stream_count_mismatch"),
        (lambda m, s: m.update(source_hashes_match=False), "source_hash_mismatch"),
        (lambda m, s: m.update(native_executable_hash_match=False), "native_executable_hash_mismatch"),
        (lambda m, s: m.update(observer_closed_cleanly=False), "observer_not_clean"),
        (lambda m, s: m.update(scheduler_closed_cleanly=False), "scheduler_not_clean"),
        (lambda m, s: m.update(stop_exit_code=1), "stop_failed"),
        (lambda m, s: m.update(launcher_exit_code=1), "launcher_failed"),
        (lambda m, s: m.update(shared_px4_files_restored=False), "shared_px4_files_not_restored"),
        (lambda m, s: m.update(trial_cleanup_verified=False), "cleanup_not_verified"),
        (lambda m, s: m.update(evidence_accepted=False), "manifest_evidence_rejected"),
        (lambda m, s: m.update(ulog_artifacts=m["ulog_artifacts"][:-1]), "px4_ulogs_incomplete"),
        (lambda m, s: s["runtime"]["resources"].update(accepted=False), "resource_evidence_invalid"),
        (lambda m, s: s["camera_phase"].update(queue_overflow_count=1), "camera_integrity_error"),
        (lambda m, s: s["camera_phase"].update(unmatched_image_count=1), "camera_integrity_error"),
        (lambda m, s: s["camera_phase"]["vehicles"]["0"].update(width=161), "camera_dimensions_invalid"),
        (lambda m, s: s["camera_phase"]["vehicles"]["0"].update(format="L_INT8"), "camera_format_invalid"),
    ],
)
def test_capacity_run_rejects_invalid_evidence(mutate, reason):
    run = next(run for run in capacity_schedule() if run.cell.name == "native-5")
    manifest, summary = _good_pair(run)
    mutate(manifest, summary)
    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))
    assert result["evidence_valid"] is False
    assert reason in result["failures"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda s: s["runtime"]["rtf"].update(scored_window=0.949999), "rtf_below_threshold"),
        (lambda s: s["camera_phase"]["vehicles"]["0"].update(frequency_hz=9.499), "image_frequency_out_of_range"),
        (lambda s: s["camera_phase"]["vehicles"]["0"].update(frequency_hz=10.501), "image_frequency_out_of_range"),
        (lambda s: s["camera_phase"]["vehicles"]["0"].update(phase_error_p95_ns=8_000_001), "phase_error_p95_exceeded"),
        (lambda s: s["camera_phase"].update(adjacent_spacing_median_error_ns=8_000_001), "spacing_error_exceeded"),
    ],
)
def test_capacity_run_preserves_valid_evidence_when_performance_fails(mutate, reason):
    run = next(run for run in capacity_schedule() if run.cell.name == "native-5")
    manifest, summary = _good_pair(run)
    mutate(summary)
    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))
    assert result["evidence_valid"] is True
    assert result["performance_pass"] is False
    assert reason in result["failures"]


def test_capacity_run_preserves_valid_evidence_when_phase_summary_rejects_only_performance():
    run = next(run for run in capacity_schedule() if run.cell.name == "native-1")
    manifest, summary = _good_pair(run)
    summary["camera_phase"]["accepted"] = False
    summary["camera_phase"]["reasons"] = ["phase_error_p95_exceeded"]
    summary["camera_phase"]["vehicles"]["0"]["phase_error_p95_ns"] = 8_200_000

    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))

    assert result["evidence_valid"] is True
    assert result["performance_pass"] is False
    assert result["evidence_failures"] == []
    assert result["performance_failures"] == ["phase_error_p95_exceeded"]


@pytest.mark.parametrize("reasons", [[], ["unknown_rejection"], "phase_error_p95_exceeded"])
def test_capacity_run_rejects_unexplained_or_malformed_phase_summary_rejection(reasons):
    run = next(run for run in capacity_schedule() if run.cell.name == "native-1")
    manifest, summary = _good_pair(run)
    summary["camera_phase"]["accepted"] = False
    summary["camera_phase"]["reasons"] = reasons

    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))

    assert result["evidence_valid"] is False
    assert "camera_phase_summary_rejected" in result["evidence_failures"]


def test_idle_cell_requires_explicit_absence_and_never_requires_images():
    run = next(run for run in capacity_schedule() if run.cell.name == "idle-0")
    manifest, summary = _good_pair(run)
    assert score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))["performance_pass"]
    summary["camera_phase"]["depth_subscription_absent"] = False
    result = score_capacity_run(manifest, summary, CapacityThresholds.from_mapping(THRESHOLDS))
    assert result["evidence_valid"] is False
    assert "unexpected_depth_subscription" in result["failures"]


def test_campaign_rejects_changed_schedule_before_classification():
    config = _config()
    config["schedule"][0]["cell"] = "native-1"
    with pytest.raises(ValueError, match="schedule"):
        classify_capacity_campaign(
            _campaign_rtfs(idle=0.98, native_one=0.97, python=0.55, native=0.97),
            config,
        )


@pytest.mark.parametrize(
    ("rtfs", "classification", "eligible"),
    [
        ({"idle": 0.94, "native_one": 0.97, "python": 0.55, "native": 0.96}, "host_or_baseline_capacity_failure", False),
        ({"idle": 0.98, "native_one": 0.97, "python": 0.55, "native": 0.96}, "python_transport_boundary", True),
        ({"idle": 0.98, "native_one": 0.97, "python": 0.55, "native": 0.59}, "sustained_render_transport_capacity", False),
        ({"idle": 0.98, "native_one": 0.97, "python": 0.55, "native": 0.60}, "mixed_python_and_render_capacity", False),
    ],
)
def test_campaign_classifies_root_cause(rtfs, classification, eligible):
    result = classify_capacity_campaign(_campaign_rtfs(**rtfs), _config())
    assert result["classification"] == classification
    assert result["production_integration_eligible"] is eligible


def test_campaign_requires_every_native_five_run_to_pass():
    pairs = _campaign_rtfs(idle=0.98, native_one=0.97, python=0.55, native=0.96)
    index = next(i for i, (m, _s) in enumerate(pairs) if m["cell"] == "native-5")
    pairs[index][1]["runtime"]["rtf"]["scored_window"] = 0.949
    result = classify_capacity_campaign(pairs, _config())
    assert result["production_integration_eligible"] is False


def test_campaign_is_inconclusive_for_missing_duplicate_invalid_or_unstable_runs():
    complete = _campaign_rtfs(idle=0.98, native_one=0.97, python=0.55, native=0.96)

    assert classify_capacity_campaign(complete[:-1], _config())["classification"] == "non_monotonic_or_inconclusive"

    duplicated = copy.deepcopy(complete)
    duplicated[-1] = copy.deepcopy(duplicated[0])
    assert classify_capacity_campaign(duplicated, _config())["classification"] == "non_monotonic_or_inconclusive"

    invalid = copy.deepcopy(complete)
    invalid[0][0]["trial_cleanup_verified"] = False
    assert classify_capacity_campaign(invalid, _config())["classification"] == "non_monotonic_or_inconclusive"

    unstable = copy.deepcopy(complete)
    idle_indexes = [i for i, (manifest, _summary) in enumerate(unstable) if manifest["cell"] == "idle-0"]
    for index, rtf in zip(idle_indexes, (0.95, 0.98, 0.981), strict=True):
        unstable[index][1]["runtime"]["rtf"]["scored_window"] = rtf
    assert classify_capacity_campaign(unstable, _config())["classification"] == "non_monotonic_or_inconclusive"
