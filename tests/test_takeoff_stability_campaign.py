import inspect
import json
from pathlib import Path

import pytest

from tools.run_takeoff_stability_campaign_wsl import (
    build_takeoff_campaign_manifest,
    calculate_takeoff_frozen_hashes,
    execute_takeoff_campaign,
    takeoff_stability_schedule,
)
from tools.run_vio_stress_trial_wsl import run_trial

ROOT = Path(__file__).resolve().parents[1]


def _config():
    return {
        "schema": "flydrones-px4-takeoff-stability-config-v1",
        "seed": 240901,
        "renderer_profile": "d3d12-nvidia",
        "fleet_size": 5,
        "takeoff_only_hold_s": 2.0,
        "run_count": 10,
        "schedule": [f"takeoff-stability-{index:02d}" for index in range(1, 11)],
    }


def _trial_summary(name, *, accepted=True):
    chains = {
        str(vehicle_id): {
            "accepted": accepted,
            "reason": None if accepted else "actuator-response-timeout",
            "landed": accepted,
        }
        for vehicle_id in range(5)
    }
    return {
        "name": name,
        "all_takeoff_chains_proven": accepted,
        "takeoff_chain_by_vehicle": chains,
        "trial_cleanup_verified": accepted,
    }


def _fake_run_factory(calls):
    def run(**kwargs):
        calls.append(kwargs)
        trial_dir = kwargs["output_root"] / kwargs["name"]
        trial_dir.mkdir(parents=True)
        manifest = {
            "schema": "flydrones-vio-stress-trial-v3",
            "name": kwargs["name"],
            "evidence_accepted": True,
        }
        (trial_dir / "trial-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    return run


def test_schedule_is_exactly_ten_unique_d3d12_five_vehicle_cold_starts():
    schedule = takeoff_stability_schedule(_config())

    assert len(schedule) == 10
    assert len({run.name for run in schedule}) == 10
    assert [run.name for run in schedule] == [f"takeoff-stability-{index:02d}" for index in range(1, 11)]
    assert all(run.renderer_profile == "d3d12-nvidia" for run in schedule)
    assert all(run.fleet_size == 5 and run.takeoff_only_hold_s == 2.0 for run in schedule)
    assert "takeoff_only_hold_s" in inspect.signature(run_trial).parameters


def test_campaign_requires_50_of_50_ready_landed_and_cleaned(tmp_path):
    calls = []

    result = execute_takeoff_campaign(
        campaign_id="takeoff-a",
        profile=tmp_path / "profile.json",
        model=tmp_path / "policy.npz",
        campaign_dir=tmp_path / "takeoff-a",
        config=_config(),
        controller_revision="revision-a",
        frozen_hashes={"controller": "sha"},
        run_trial_fn=_fake_run_factory(calls),
        summarize_trial_fn=lambda path: _trial_summary(path.name),
        resources_free_fn=lambda: True,
    )

    assert result["accepted"]
    assert result["metrics"]["mission_ready"] == 50
    assert result["metrics"]["landed"] == 50
    assert result["metrics"]["clean_trials"] == 10
    assert len(calls) == 10
    assert all(call["renderer_profile"] == "d3d12-nvidia" for call in calls)
    assert all(call["fleet_size"] == 5 and call["takeoff_only_hold_s"] == 2.0 for call in calls)


def test_campaign_stops_on_first_failed_vehicle_and_preserves_trial(tmp_path):
    calls = []

    def summarize(path):
        return _trial_summary(path.name, accepted=path.name != "takeoff-stability-03")

    result = execute_takeoff_campaign(
        campaign_id="takeoff-fail",
        profile=tmp_path / "profile.json",
        model=tmp_path / "policy.npz",
        campaign_dir=tmp_path / "takeoff-fail",
        config=_config(),
        controller_revision="revision-a",
        frozen_hashes={"controller": "sha"},
        run_trial_fn=_fake_run_factory(calls),
        summarize_trial_fn=summarize,
        resources_free_fn=lambda: True,
    )

    assert not result["accepted"]
    assert result["stopped_after"] == "takeoff-stability-03"
    assert len(calls) == 3
    assert (tmp_path / "takeoff-fail/takeoff-stability-03/trial-manifest.json").is_file()


def test_resume_skips_only_complete_trials_and_never_overwrites(tmp_path):
    campaign_dir = tmp_path / "takeoff-resume"
    config = _config()
    expected = build_takeoff_campaign_manifest(
        campaign_id="takeoff-resume",
        config=config,
        profile=tmp_path / "profile.json",
        model=tmp_path / "policy.npz",
        controller_revision="revision-a",
        frozen_hashes={"controller": "sha"},
    )
    campaign_dir.mkdir()
    (campaign_dir / "campaign-manifest.json").write_text(json.dumps(expected), encoding="utf-8")
    first = campaign_dir / "takeoff-stability-01"
    first.mkdir()
    (first / "trial-manifest.json").write_text(
        json.dumps({"schema": "flydrones-vio-stress-trial-v3", "name": first.name, "evidence_accepted": True}),
        encoding="utf-8",
    )
    (first / "stress-summary.json").write_text(json.dumps(_trial_summary(first.name)), encoding="utf-8")
    calls = []

    result = execute_takeoff_campaign(
        campaign_id="takeoff-resume",
        profile=tmp_path / "profile.json",
        model=tmp_path / "policy.npz",
        campaign_dir=campaign_dir,
        config=config,
        controller_revision="revision-a",
        frozen_hashes={"controller": "sha"},
        run_trial_fn=_fake_run_factory(calls),
        summarize_trial_fn=lambda path: _trial_summary(path.name),
        resources_free_fn=lambda: True,
    )

    assert result["accepted"]
    assert first.name not in [call["name"] for call in calls]

    incomplete_dir = tmp_path / "takeoff-incomplete"
    incomplete_manifest = build_takeoff_campaign_manifest(
        campaign_id="takeoff-incomplete",
        config=config,
        profile=tmp_path / "profile.json",
        model=tmp_path / "policy.npz",
        controller_revision="revision-a",
        frozen_hashes={"controller": "sha"},
    )
    incomplete_dir.mkdir()
    (incomplete_dir / "campaign-manifest.json").write_text(json.dumps(incomplete_manifest), encoding="utf-8")
    (incomplete_dir / "takeoff-stability-01").mkdir()
    with pytest.raises(RuntimeError, match="incomplete"):
        execute_takeoff_campaign(
            campaign_id="takeoff-incomplete",
            profile=tmp_path / "profile.json",
            model=tmp_path / "policy.npz",
            campaign_dir=incomplete_dir,
            config=config,
            controller_revision="revision-a",
            frozen_hashes={"controller": "sha"},
            run_trial_fn=_fake_run_factory([]),
            summarize_trial_fn=lambda path: _trial_summary(path.name),
            resources_free_fn=lambda: True,
        )


def test_cleanup_is_verified_between_runs(tmp_path):
    calls = []
    resource_states = iter((True, False))

    with pytest.raises(RuntimeError, match="not released"):
        execute_takeoff_campaign(
            campaign_id="takeoff-dirty",
            profile=tmp_path / "profile.json",
            model=tmp_path / "policy.npz",
            campaign_dir=tmp_path / "takeoff-dirty",
            config=_config(),
            controller_revision="revision-a",
            frozen_hashes={"controller": "sha"},
            run_trial_fn=_fake_run_factory(calls),
            summarize_trial_fn=lambda path: _trial_summary(path.name),
            resources_free_fn=lambda: next(resource_states),
        )
    assert len(calls) == 1


def test_takeoff_config_hashes_match_frozen_inputs():
    config_path = ROOT / "configs/px4_takeoff_stability.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    actual = calculate_takeoff_frozen_hashes(
        config_path,
        ROOT / config["profile"],
        ROOT / config["policy"],
    )

    assert {key: actual[key] for key in config["expected_hashes"]} == config["expected_hashes"]
    assert actual["mavlink_drone"]
