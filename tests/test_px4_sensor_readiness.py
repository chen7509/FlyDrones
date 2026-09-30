from __future__ import annotations

import copy
import hashlib
import json
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
from tools.reclassify_px4_sensor_readiness_campaign import reclassify_campaign
from tools.run_gated_camera_render_capacity_campaign_wsl import (
    validate_readiness_build_binding,
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
        "px4_revision": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
        "px4_patch_sha256": "c" * 64,
        "px4_vehicle_imu_sha256": "d" * 64,
        "thresholds": dict(THRESHOLDS),
        "schedules": {
            "development": [run.as_dict() for run in readiness_schedule("development")],
            "formal": [run.as_dict() for run in readiness_schedule("formal")],
        },
        "phase": phase,
    }


def _good_pair(run, *, rtf: float = 0.97):
    sensors = {
        "imu": "imu_sensor/imu",
        "magnetometer": "magnetometer_sensor/magnetometer",
        "gps": "navsat_sensor/navsat",
        "barometer": "air_pressure_sensor/air_pressure",
    }
    topics = {
        f"{vehicle_id}:{sensor}": {
            "topic": (
                "/world/flydrones_forest/model/"
                f"x500_depth_fly_{vehicle_id}/link/base_link/sensor/{suffix}"
            ),
            "returncode": 0,
            "message_received": True,
            "publisher": True,
            "subscriber": True,
            "publisher_count": 1,
            "subscriber_count": 1,
        }
        for vehicle_id in range(run.vehicle_count)
        for sensor, suffix in sensors.items()
    }
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
            "schema": "flydrones-px4-build-evidence-v2",
            "build_name": "px4_sitl_nolockstep",
            "px4_revision": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
            "nolockstep": True,
            "binary_sha256": "a" * 64,
            "boardconfig_sha256": "b" * 64,
            "px4_patch_sha256": "c" * 64,
            "vehicle_imu_sha256": "d" * 64,
            "vehicle_imu_patch_applied": True,
            "board_definition": "#define CONFIG_BOARD_NOLOCKSTEP 1",
        },
        "sensor_source_evidence": {
            "schema": "flydrones-gazebo-sensor-source-warmup-v1",
            "accepted": True,
            "expected_topic_count": run.vehicle_count * 4,
            "message_topic_count": run.vehicle_count * 4,
            "topics": copy.deepcopy(topics),
        },
        "sensor_topology_evidence": {
            "schema": "flydrones-px4-sensor-topic-connections-v1",
            "accepted": True,
            "expected_topic_count": run.vehicle_count * 4,
            "publisher_count": run.vehicle_count * 4,
            "subscriber_count": run.vehicle_count * 4,
            "topics": copy.deepcopy(topics),
        },
        "cleanup_evidence": {
            "schema": "flydrones-owned-process-cleanup-v1",
            "recorded_processes": run.vehicle_count + 1,
            "stopped": [
                {"pid": 100 + vehicle_id, "start_ticks": 10, "role": f"px4-{vehicle_id}"}
                for vehicle_id in range(run.vehicle_count)
            ]
            + [{"pid": 999, "start_ticks": 10, "role": "gazebo-server"}],
            "already_gone": [],
            "ownership_mismatch": [],
            "failed_to_stop": [],
        },
        "restoration_evidence": {
            "schema": "flydrones-px4-shared-restoration-v1",
            "restored": True,
            "items": {
                name: {
                    "matched": True,
                    "backup_sha256": character * 64,
                    "restored_sha256": character * 64,
                }
                for name, character in (
                    ("world", "a"),
                    ("OakD-Lite-Fly", "b"),
                    ("x500_depth_fly", "c"),
                )
            },
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


def test_readiness_pins_px4_first_imu_sample_patch():
    config = json.loads(
        (ROOT / "configs/px4_sensor_readiness.json").read_text(encoding="utf-8")
    )
    patch_path = ROOT / config["px4_patch"]
    patch_bytes = patch_path.read_bytes()
    patch_text = patch_bytes.decode("utf-8")
    launcher = (ROOT / "tools/launch_px4_sensor_readiness_wsl.sh").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "tools/run_px4_sensor_readiness_campaign_wsl.py").read_text(
        encoding="utf-8"
    )

    assert hashlib.sha256(patch_bytes).hexdigest() == config["px4_patch_sha256"]
    assert len(config["px4_vehicle_imu_sha256"]) == 64
    assert "_accel_timestamp_sample_last == 0" in patch_text
    assert "_gyro_timestamp_sample_last == 0" in patch_text
    assert "FLYDRONES_EXPECTED_PX4_PATCH_SHA256" in launcher
    assert "FLYDRONES_EXPECTED_VEHICLE_IMU_SHA256" in launcher
    assert "vehicle_imu_patch_applied" in launcher
    assert "FLYDRONES_EXPECTED_PX4_PATCH_SHA256" in runner
    assert "FLYDRONES_EXPECTED_VEHICLE_IMU_SHA256" in runner


def test_readiness_launcher_serializes_px4_gazebo_bridge_attachment():
    launcher = (ROOT / "tools/launch_px4_sensor_readiness_wsl.sh").read_text(
        encoding="utf-8"
    )

    assert "wait_for_vehicle_sensor_subscribers()" in launcher
    assert 'wait_for_vehicle_sensor_subscribers "$instance_id"' in launcher


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
        (
            lambda manifest, _summary: manifest["sensor_source_evidence"].pop(
                "topics"
            ),
            "sensor_source_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["sensor_topology_evidence"].pop(
                "topics"
            ),
            "sensor_topology_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["cleanup_evidence"].update(stopped=[]),
            "cleanup_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["restoration_evidence"].update(items={}),
            "restoration_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["px4_build_evidence"].update(
                binary_sha256="z" * 64
            ),
            "px4_build_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["px4_build_evidence"].update(
                px4_revision="z" * 40
            ),
            "px4_build_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["px4_build_evidence"].update(
                px4_patch_sha256="z" * 64
            ),
            "px4_build_evidence_invalid",
        ),
        (
            lambda manifest, _summary: manifest["ulog_artifacts"][0].update(
                sha256="z" * 64
            ),
            "px4_ulogs_incomplete",
        ),
        (
            lambda manifest, _summary: [
                item.update(pid=999, start_ticks=10)
                for item in manifest["cleanup_evidence"]["stopped"]
            ],
            "cleanup_evidence_invalid",
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


def test_reclassifier_rejects_output_inside_source_campaign(tmp_path):
    source = tmp_path / "formal-campaign"
    source.mkdir()

    with pytest.raises(ValueError, match="outside source campaign"):
        reclassify_campaign(
            source,
            source / "amendment",
            tmp_path / "config-does-not-need-to-exist.json",
        )


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


def test_formal_rejects_px4_revision_that_differs_from_frozen_config():
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    for manifest, _summary in pairs:
        manifest["px4_build_evidence"]["px4_revision"] = "0" * 40

    result = classify_readiness_campaign(pairs, _config("formal"), phase="formal")

    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False
    assert "px4_revision_mismatch" in result["reasons"]


def test_formal_rejects_px4_patch_that_differs_from_frozen_config():
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    for manifest, _summary in pairs:
        manifest["px4_build_evidence"]["px4_patch_sha256"] = "e" * 64

    result = classify_readiness_campaign(pairs, _config("formal"), phase="formal")

    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False
    assert "px4_patch_mismatch" in result["reasons"]


def test_formal_rejects_vehicle_imu_source_that_differs_from_frozen_config():
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    for manifest, _summary in pairs:
        manifest["px4_build_evidence"]["vehicle_imu_sha256"] = "e" * 64

    result = classify_readiness_campaign(pairs, _config("formal"), phase="formal")

    assert result["classification"] == "inconclusive_or_invalid"
    assert result["camera_rerun_eligible"] is False
    assert "px4_vehicle_imu_source_mismatch" in result["reasons"]


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
    assert "validate_readiness_build_binding(" in entry


def test_gated_camera_entry_binds_all_formal_manifests_to_exact_px4_build(tmp_path: Path):
    pairs = [_good_pair(run) for run in readiness_schedule("formal")]
    summary = classify_readiness_campaign(pairs, _config("formal"), phase="formal")
    summary_path = tmp_path / "campaign-summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    for (manifest, _), score in zip(pairs, summary["scores"], strict=True):
        target = tmp_path / score["name"] / "manifest.json"
        target.parent.mkdir()
        target.write_text(json.dumps(manifest), encoding="utf-8")
    identity = dict(pairs[0][0]["px4_build_evidence"])
    identity["px4_patch"] = "patches/px4/vehicle-imu-first-sample-dt.patch"
    camera_config = {
        "readiness_gate_inputs": {
            "summary_sha256": "e" * 64,
            "config_sha256": "f" * 64,
        },
        "px4_build_identity": identity,
    }

    result = validate_readiness_build_binding(
        summary_path=summary_path,
        summary=summary,
        readiness_config=_config("formal"),
        camera_config=camera_config,
        summary_sha256="e" * 64,
        readiness_config_sha256="f" * 64,
    )

    assert result["px4_build_identity"] == identity
    assert len(result["readiness_manifest_sha256"]) == 10

    first_manifest = tmp_path / summary["scores"][0]["name"] / "manifest.json"
    changed = json.loads(first_manifest.read_text(encoding="utf-8"))
    changed["px4_build_evidence"]["binary_sha256"] = "9" * 64
    first_manifest.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="readiness PX4 build identity mismatch"):
        validate_readiness_build_binding(
            summary_path=summary_path,
            summary=summary,
            readiness_config=_config("formal"),
            camera_config=camera_config,
            summary_sha256="e" * 64,
            readiness_config_sha256="f" * 64,
        )
