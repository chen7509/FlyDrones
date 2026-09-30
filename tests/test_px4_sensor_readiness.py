from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from flydrones.camera_rerun_gate import validate_camera_rerun_gate
from flydrones.px4_sensor_readiness import (
    ReadinessThresholds,
    classify_readiness_campaign,
    readiness_schedule,
    score_readiness_run,
)

THRESHOLDS = {
    "min_rtf": 0.95,
    "scored_duration_s": 30.0,
    "wall_timeout_s": 120.0,
    "repeatability_rtf_range_max": 0.03,
    "formal_run_count": 10,
}
ROOT = Path(__file__).parents[1]


def test_readiness_uses_versioned_launcher_without_mutating_frozen_camera_inputs():
    launcher = (ROOT / "tools/launch_px4_sensor_readiness_wsl.sh").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "tools/run_px4_sensor_readiness_campaign_wsl.py").read_text(
        encoding="utf-8"
    )
    generator = (ROOT / "tools/generate_px4_sensor_readiness_world.py").read_text(
        encoding="utf-8"
    )

    assert "launch_px4_sensor_readiness_wsl.sh" in runner
    assert "generate_px4_sensor_readiness_world.py" in launcher
    assert 'platform_readiness_only="${FLYDRONES_PLATFORM_READINESS_ONLY:-0}"' in launcher
    assert 'echo "Gazebo preloaded sensor publishers timed out"' in launcher
    assert "choices=(0, 1, 2, 5)" in generator
    assert "range(args.preload_vehicles)" in generator


def _config(phase: str) -> dict[str, object]:
    return {
        "thresholds": dict(THRESHOLDS),
        "schedules": {
            "development": [run.as_dict() for run in readiness_schedule("development")],
            "formal": [run.as_dict() for run in readiness_schedule("formal")],
        },
        "phase": phase,
    }


def _good_pair(run, *, rtf: float = 0.97):
    manifest = {
        "schema": "flydrones-px4-sensor-readiness-manifest-v1",
        "name": run.name,
        "phase": run.phase,
        "vehicle_count": run.vehicle_count,
        "repetition": run.repetition,
        "sequence": run.sequence,
        "launcher_exit_code": 0,
        "platform_ready": True,
        "initial_all_healthy": True,
        "post_window_all_healthy": True,
        "scored_duration_sim_s": 30.0,
        "scored_wall_timeout_s": 120.0,
        "sensor_timeout_count": 0,
        "trial_cleanup_verified": True,
        "shared_px4_files_restored": True,
        "errors": [],
        "px4_build_evidence": {
            "schema": "flydrones-px4-build-evidence-v1",
            "build_name": "px4_sitl_nolockstep",
            "px4_revision": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
            "nolockstep": True,
            "binary_sha256": "a" * 64,
        },
        "sensor_source_evidence": {
            "schema": "flydrones-gazebo-sensor-source-warmup-v1",
            "accepted": True,
            "expected_topic_count": run.vehicle_count * 4,
            "message_topic_count": run.vehicle_count * 4,
        },
        "sensor_topology_evidence": {
            "schema": "flydrones-px4-sensor-topic-connections-v1",
            "accepted": True,
            "expected_topic_count": run.vehicle_count * 4,
            "publisher_count": run.vehicle_count * 4,
            "subscriber_count": run.vehicle_count * 4,
        },
        "cleanup_evidence": {
            "schema": "flydrones-owned-process-cleanup-v1",
            "recorded_processes": run.vehicle_count + 1,
            "ownership_mismatch": [],
            "failed_to_stop": [],
        },
        "restoration_evidence": {
            "schema": "flydrones-px4-shared-restoration-v1",
            "restored": True,
        },
        "ulog_artifacts": [
            {
                "vehicle_id": vehicle_id,
                "path": f"px4-ulogs/agent-{vehicle_id}.ulg",
                "bytes": 100,
                "sha256": f"{vehicle_id:064x}",
            }
            for vehicle_id in range(run.vehicle_count)
        ],
    }
    summary = {
        "schema": "flydrones-px4-sensor-readiness-summary-v1",
        "runtime": {"rtf": rtf},
        "vehicles": {
            str(vehicle_id): {
                "initial_healthy": True,
                "post_window_healthy": True,
            }
            for vehicle_id in range(run.vehicle_count)
        },
    }
    return manifest, summary


def test_readiness_schedules_are_exact_and_separate_development_from_formal():
    development = readiness_schedule("development")
    formal = readiness_schedule("formal")

    assert [run.vehicle_count for run in development] == [1, 2, 5]
    assert [run.sequence for run in development] == [1, 2, 3]
    assert len(formal) == 10
    assert {run.vehicle_count for run in formal} == {5}
    assert [run.repetition for run in formal] == list(range(1, 11))
    assert not ({run.name for run in development} & {run.name for run in formal})


def test_good_readiness_run_passes_evidence_and_performance():
    run = readiness_schedule("development")[0]
    manifest, summary = _good_pair(run)

    score = score_readiness_run(
        manifest, summary, ReadinessThresholds.from_mapping(THRESHOLDS)
    )

    assert score["evidence_valid"] is True
    assert score["performance_pass"] is True
    assert score["failures"] == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda manifest, _summary: manifest.update(launcher_exit_code=3), "launcher_failed"),
        (lambda manifest, _summary: manifest.update(platform_ready=False), "platform_not_ready"),
        (
            lambda manifest, _summary: manifest.update(initial_all_healthy=False),
            "initial_health_invalid",
        ),
        (
            lambda manifest, _summary: manifest.update(post_window_all_healthy=False),
            "post_window_health_invalid",
        ),
        (
            lambda manifest, _summary: manifest.update(scored_duration_sim_s=29.9),
            "scored_duration_incomplete",
        ),
        (
            lambda manifest, _summary: manifest.update(sensor_timeout_count=1),
            "sensor_timeout_observed",
        ),
        (
            lambda manifest, _summary: manifest.update(trial_cleanup_verified=False),
            "cleanup_not_verified",
        ),
        (
            lambda manifest, _summary: manifest.update(shared_px4_files_restored=False),
            "shared_px4_files_not_restored",
        ),
        (
            lambda manifest, _summary: manifest.update(
                ulog_artifacts=manifest["ulog_artifacts"][:-1]
            ),
            "px4_ulogs_incomplete",
        ),
        (
            lambda manifest, _summary: manifest.update(errors=["missing artifact"]),
            "artifact_collection_failed",
        ),
        (
            lambda manifest, _summary: manifest.update(px4_build_evidence={}),
            "px4_build_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["sensor_source_evidence"].update(
                message_topic_count=0
            ),
            "sensor_source_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["sensor_topology_evidence"].update(
                subscriber_count=0
            ),
            "sensor_topology_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["cleanup_evidence"].update(
                failed_to_stop=[{"pid": 123}]
            ),
            "cleanup_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest.update(restoration_evidence={}),
            "restoration_evidence_invalid",
        ),
    ],
)
def test_readiness_run_rejects_invalid_evidence(mutation, reason):
    run = readiness_schedule("development")[2]
    manifest, summary = _good_pair(run)
    mutation(manifest, summary)

    score = score_readiness_run(
        manifest, summary, ReadinessThresholds.from_mapping(THRESHOLDS)
    )

    assert score["evidence_valid"] is False
    assert score["performance_pass"] is False
    assert reason in score["evidence_failures"]


@pytest.mark.parametrize("rtf", [None, math.nan, math.inf, -math.inf])
def test_missing_or_nonfinite_rtf_is_invalid_evidence(rtf):
    run = readiness_schedule("development")[0]
    manifest, summary = _good_pair(run)
    summary["runtime"]["rtf"] = rtf

    score = score_readiness_run(
        manifest, summary, ReadinessThresholds.from_mapping(THRESHOLDS)
    )

    assert score["evidence_valid"] is False
    assert "rtf_missing_or_invalid" in score["evidence_failures"]


def test_finite_low_rtf_is_valid_performance_failure():
    run = readiness_schedule("development")[0]
    manifest, summary = _good_pair(run, rtf=0.949)

    score = score_readiness_run(
        manifest, summary, ReadinessThresholds.from_mapping(THRESHOLDS)
    )

    assert score["evidence_valid"] is True
    assert score["performance_pass"] is False
    assert score["performance_failures"] == ["rtf_below_threshold"]


def test_development_requires_one_two_and_five_vehicle_runs_to_pass():
    pairs = [_good_pair(run) for run in readiness_schedule("development")]

    result = classify_readiness_campaign(pairs, _config("development"), phase="development")

    assert result["classification"] == "development_pass"
    assert result["camera_rerun_eligible"] is False
    assert result["readiness_rate"] == 1.0

    failed = copy.deepcopy(pairs)
    failed[-1][0]["post_window_all_healthy"] = False
    result = classify_readiness_campaign(failed, _config("development"), phase="development")
    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False


def test_formal_requires_ten_of_ten_stable_realtime_runs_before_camera_rerun():
    pairs = [_good_pair(run, rtf=0.97 + (run.sequence % 2) * 0.01) for run in readiness_schedule("formal")]

    result = classify_readiness_campaign(pairs, _config("formal"), phase="formal")

    assert result["classification"] == "stable_sensor_readiness"
    assert result["camera_rerun_eligible"] is True
    assert result["readiness_rate"] == 1.0

    slow = copy.deepcopy(pairs)
    slow[0][1]["runtime"]["rtf"] = 0.90
    result = classify_readiness_campaign(slow, _config("formal"), phase="formal")
    assert result["classification"] == "baseline_below_realtime"
    assert result["camera_rerun_eligible"] is False

    invalid = copy.deepcopy(pairs)
    invalid[0][0]["sensor_timeout_count"] = 1
    result = classify_readiness_campaign(invalid, _config("formal"), phase="formal")
    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False


def test_formal_rejects_changed_or_incomplete_schedule():
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    with pytest.raises(ValueError, match="schedule"):
        classify_readiness_campaign(pairs, _config("formal") | {"schedules": {}}, phase="formal")

    result = classify_readiness_campaign(pairs[:-1], _config("formal"), phase="formal")
    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False


def test_camera_rerun_gate_accepts_only_complete_formal_pass():
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    config = _config("formal")
    passed = classify_readiness_campaign(pairs, config, phase="formal")

    gate = validate_camera_rerun_gate(passed, config)
    assert gate["accepted"] is True
    assert gate["run_count"] == 10

    failed = copy.deepcopy(passed)
    failed["scores"][-1]["evidence_valid"] = False
    with pytest.raises(ValueError, match="ten valid passing runs"):
        validate_camera_rerun_gate(failed, config)

    failed = copy.deepcopy(passed)
    failed["camera_rerun_eligible"] = False
    with pytest.raises(ValueError, match="not eligible"):
        validate_camera_rerun_gate(failed, config)


def test_gated_camera_entry_validates_readiness_before_legacy_runner():
    entry = (
        ROOT / "tools/run_gated_camera_render_capacity_campaign_wsl.py"
    ).read_text(encoding="utf-8")

    gate_call = entry.index("validate_camera_rerun_gate(")
    legacy_call = entry.index("subprocess.run(")
    assert gate_call < legacy_call
    assert "--readiness-summary-sha256" in entry
    assert "--readiness-config-sha256" in entry
