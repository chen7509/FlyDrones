from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from flydrones.camera_render_capacity import capacity_schedule
from tools.run_camera_render_capacity_campaign_wsl import (
    build_capacity_campaign_manifest,
    calculate_capacity_frozen_hashes,
    execute_capacity_campaign,
    validate_existing_campaign,
)

ROOT = Path(__file__).resolve().parents[1]


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


def _config() -> dict[str, object]:
    return {
        "schema": "flydrones-camera-render-capacity-config-v1",
        "profile": "configs/vio_fault_profiles/baseline.json",
        "policy": "docs/results/vio-stress/policy-checkpoint.npz",
        "renderer_profile": "d3d12-nvidia",
        "world": "flydrones_forest",
        "camera_model": "assets/gazebo/models/OakD-Lite-Fly",
        "vehicle_model": "assets/gazebo/models/x500_depth_fly",
        "vehicle_count": 5,
        "readiness_timeout_s": 45.0,
        "scored_duration_s": 30.0,
        "wall_timeout_s": 120.0,
        "px4_build_name": "px4_sitl_nolockstep",
        "px4_revision": "px4-revision",
        "px4_build_identity": {
            "schema": "flydrones-px4-build-evidence-v2",
            "build_name": "px4_sitl_nolockstep",
            "px4_revision": "px4-revision",
            "binary_sha256": "a" * 64,
            "boardconfig_sha256": "b" * 64,
            "px4_patch": "patches/px4/vehicle-imu-first-sample-dt.patch",
            "px4_patch_sha256": "cd36509e63b3709770366a17a07cca67591be409c02a4475ecd3508923d8fd94",
            "vehicle_imu_sha256": "d" * 64,
            "vehicle_imu_patch_applied": True,
            "nolockstep": True,
            "board_definition": "#define CONFIG_BOARD_NOLOCKSTEP 1",
        },
        "readiness_gate_inputs": {
            "summary_sha256": "e" * 64,
            "config_sha256": "f" * 64,
        },
        "software_versions": {"gz_transport": "13.6.0", "gz_msgs": "10.4.0"},
        "thresholds": dict(THRESHOLDS),
        "schedule": [run.as_dict() for run in capacity_schedule()],
        "expected_hashes": {"runner": "hash"},
    }


def _pair(run, *, rtf: float = 0.97) -> tuple[dict[str, object], dict[str, object]]:
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
        "px4_build_identity_match": True,
        "observer_closed_cleanly": True,
        "scheduler_closed_cleanly": True,
        "stop_exit_code": 0,
        "launcher_exit_code": 0,
        "shared_px4_files_restored": True,
        "trial_cleanup_verified": True,
        "evidence_accepted": True,
        "ulog_artifacts": [
            {
                "vehicle_id": vehicle,
                "path": f"px4-ulogs/agent-{vehicle}.ulg",
                "bytes": 100,
                "sha256": f"{vehicle:064x}",
            }
            for vehicle in range(5)
        ],
    }
    summary = {
        "schema": "flydrones-camera-render-capacity-summary-v1",
        "runtime": {
            "rtf": {"scored_window": rtf},
            "resources": {"accepted": True, "gazebo": {"samples": 3}},
        },
        "camera_phase": {
            "accepted": active > 0,
            "vehicles": {
                str(vehicle): {
                    "frequency_hz": 10.0,
                    "phase_error_p95_ns": 4_000_000,
                    "width": 160,
                    "height": 120,
                    "format": "R_FLOAT32",
                }
                for vehicle in range(active)
            },
            "adjacent_spacing_median_error_ns": 4_000_000 if active == 5 else None,
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


def test_campaign_manifest_freezes_identity_versions_paths_hashes_and_order():
    config = _config()
    manifest = build_capacity_campaign_manifest(
        config,
        campaign_id="capacity-a",
        frozen_hashes={"runner": "hash"},
    )

    assert manifest["schema"] == "flydrones-camera-render-capacity-campaign-v1"
    assert manifest["campaign_id"] == "capacity-a"
    assert manifest["px4_revision"] == "px4-revision"
    assert manifest["px4_build_identity"] == config["px4_build_identity"]
    assert manifest["readiness_gate_inputs"] == config["readiness_gate_inputs"]
    assert manifest["renderer_profile"] == "d3d12-nvidia"
    assert manifest["profile"] == config["profile"]
    assert manifest["policy"] == config["policy"]
    assert manifest["camera_model"] == config["camera_model"]
    assert manifest["vehicle_model"] == config["vehicle_model"]
    assert manifest["software_versions"] == config["software_versions"]
    assert manifest["thresholds"] == THRESHOLDS
    assert manifest["schedule"] == [run.as_dict() for run in capacity_schedule()]
    assert manifest["completed_slots"] == []


def test_versioned_capacity_config_pins_contract_and_current_frozen_inputs():
    path = ROOT / "configs/five_camera_render_capacity.json"
    config = json.loads(path.read_text(encoding="utf-8"))

    assert config["renderer_profile"] == "d3d12-nvidia"
    assert config["vehicle_count"] == 5
    assert config["scored_duration_s"] == 30.0
    assert config["wall_timeout_s"] == 120.0
    assert config["readiness_timeout_s"] == 180.0
    assert config["profile"] == "configs/vio_fault_profiles/baseline.json"
    assert config["policy"] == "docs/results/vio-stress/policy-checkpoint.npz"
    assert config["camera_model"] == "assets/gazebo/models/OakD-Lite-Fly"
    assert config["vehicle_model"] == "assets/gazebo/models/x500_depth_fly"
    assert config["schedule"] == [run.as_dict() for run in capacity_schedule()]
    actual = calculate_capacity_frozen_hashes(
        path, ROOT / "build/native-camera-phase/flydrones_camera_phase_native"
    )
    assert config["expected_hashes"] == actual


@pytest.mark.parametrize("field", ("campaign_id", "thresholds", "frozen_hashes", "schedule"))
def test_existing_campaign_rejects_any_frozen_drift(field: str):
    expected = build_capacity_campaign_manifest(
        _config(), campaign_id="capacity-a", frozen_hashes={"runner": "hash"}
    )
    existing = copy.deepcopy(expected)
    if field == "campaign_id":
        existing[field] = "capacity-b"
    elif field == "thresholds":
        existing[field]["min_rtf"] = 0.94
    elif field == "frozen_hashes":
        existing[field]["runner"] = "other"
    else:
        existing[field] = existing[field][:-1]
    with pytest.raises(RuntimeError, match="frozen campaign manifest mismatch"):
        validate_existing_campaign(existing, expected)


def test_campaign_runs_twelve_slots_serially_and_resumes_without_rerun(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    calls: list[str] = []
    resource_checks: list[int] = []

    def fake_trial(*, run, output_root, **_kwargs):
        calls.append(run.name)
        manifest, summary = _pair(run)
        trial_dir = output_root / run.name
        trial_dir.mkdir()
        (trial_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (trial_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return {"manifest": manifest, "summary": summary, "output": str(trial_dir)}

    def resources_free():
        resource_checks.append(len(calls))
        return True

    kwargs = {
        "config_path": config_path,
        "output_root": tmp_path / "results",
        "campaign_id": "capacity-a",
        "native_executable": tmp_path / "native",
        "_run_trial_fn": fake_trial,
        "_resources_free_fn": resources_free,
        "_frozen_hashes": {"runner": "hash"},
        "_px4_revision": "px4-revision",
    }
    first = execute_capacity_campaign(**kwargs)
    second = execute_capacity_campaign(**kwargs)

    assert calls == [run.name for run in capacity_schedule()]
    assert len(resource_checks) == 24
    assert len(first["scores"]) == 12
    assert second == first
    manifest = json.loads(
        (tmp_path / "results/capacity-a/campaign-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["completed_slots"] == [run.name for run in capacity_schedule()]


def test_partial_slot_is_preserved_and_never_reused(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    campaign = tmp_path / "results/capacity-a"
    campaign.mkdir(parents=True)
    expected = build_capacity_campaign_manifest(
        _config(), campaign_id="capacity-a", frozen_hashes={"runner": "hash"}
    )
    (campaign / "campaign-manifest.json").write_text(json.dumps(expected), encoding="utf-8")
    (campaign / capacity_schedule()[0].name).mkdir()
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="incomplete and will not be overwritten"):
        execute_capacity_campaign(
            config_path=config_path,
            output_root=tmp_path / "results",
            campaign_id="capacity-a",
            native_executable=tmp_path / "native",
            _run_trial_fn=lambda **kwargs: calls.append(kwargs["run"].name),
            _resources_free_fn=lambda: True,
            _frozen_hashes={"runner": "hash"},
            _px4_revision="px4-revision",
        )
    assert calls == []


def test_performance_failure_is_preserved_and_campaign_continues(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    calls: list[str] = []

    def fake_trial(*, run, output_root, **_kwargs):
        calls.append(run.name)
        manifest, summary = _pair(run, rtf=0.50 if run.sequence == 1 else 0.97)
        trial_dir = output_root / run.name
        trial_dir.mkdir()
        (trial_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (trial_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return {"manifest": manifest, "summary": summary}

    result = execute_capacity_campaign(
        config_path=config_path,
        output_root=tmp_path / "results",
        campaign_id="capacity-a",
        native_executable=tmp_path / "native",
        _run_trial_fn=fake_trial,
        _resources_free_fn=lambda: True,
        _frozen_hashes={"runner": "hash"},
        _px4_revision="px4-revision",
    )

    assert len(calls) == 12
    assert result["scores"][0]["performance_pass"] is False
    assert "rtf_below_threshold" in result["scores"][0]["failures"]


def test_campaign_records_pre_readiness_slot_as_unscored_without_performance(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    def fake_trial(*, run, output_root, **_kwargs):
        manifest, summary = _pair(run)
        if run.sequence == 2:
            manifest["scored_duration_sim_s"] = 0.0
            manifest["evidence_accepted"] = False
            manifest["px4_all_healthy"] = False
            summary["runtime"]["rtf"]["scored_window"] = 0.1
            summary["camera_phase"]["vehicles"]["0"]["frequency_hz"] = 0.0
        trial_dir = output_root / run.name
        trial_dir.mkdir()
        (trial_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (trial_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return {"manifest": manifest, "summary": summary}

    result = execute_capacity_campaign(
        config_path=config_path,
        output_root=tmp_path / "results",
        campaign_id="capacity-a",
        native_executable=tmp_path / "native",
        _run_trial_fn=fake_trial,
        _resources_free_fn=lambda: True,
        _frozen_hashes={"runner": "hash"},
        _px4_revision="px4-revision",
    )

    score = result["scores"][1]
    assert score["score_status"] == "unscored"
    assert score["evidence_valid"] is False
    assert score["performance_failures"] == []
    campaign_manifest = json.loads(
        (tmp_path / "results/capacity-a/campaign-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert campaign_manifest["scores"][1]["performance_failures"] == []


def test_occupied_resources_block_start_without_calling_trial(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="resources are still in use"):
        execute_capacity_campaign(
            config_path=config_path,
            output_root=tmp_path / "results",
            campaign_id="capacity-a",
            native_executable=tmp_path / "native",
            _run_trial_fn=lambda **kwargs: calls.append(kwargs["run"].name),
            _resources_free_fn=lambda: False,
            _frozen_hashes={"runner": "hash"},
            _px4_revision="px4-revision",
        )
    assert calls == []


def test_campaign_id_cannot_escape_output_root(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    with pytest.raises(ValueError, match="campaign_id"):
        execute_capacity_campaign(
            config_path=config_path,
            output_root=tmp_path / "results",
            campaign_id="../escape",
            native_executable=tmp_path / "native",
            _frozen_hashes={"runner": "hash"},
            _px4_revision="px4-revision",
        )
