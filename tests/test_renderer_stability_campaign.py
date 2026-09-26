import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from flydrones.renderer_stability import campaign_schedule
from tools.run_renderer_stability_campaign_wsl import (
    build_campaign_manifest,
    calculate_frozen_hashes,
    execute_campaign,
    smoke_schedule,
    validate_existing_campaign,
)
from tools.snapshot_vio_gate_results import snapshot_renderer_campaign

ROOT = Path(__file__).resolve().parents[1]


def _config():
    return {
        "schema": "flydrones-renderer-stability-config-v1",
        "seed": 240901,
        "schedule": [item.as_dict() for item in campaign_schedule()],
        "thresholds": {"tail_p99_ms_max": 100.0, "tail_max_ms_exclusive": 250.0,
                       "rtf_min": 0.95},
        "sensor": {"depth_width": 160, "depth_height": 120, "depth_frequency_hz": 10.0},
        "expected_hashes": {"launcher": "launcher-sha", "controller": "controller-sha"},
    }


def test_smoke_schedule_has_two_single_vehicle_runs_and_one_d3d12_five_vehicle_run():
    schedule = smoke_schedule()

    assert [(item.renderer_profile, item.fleet_size) for item in schedule] == [
        ("default", 1),
        ("d3d12-nvidia", 1),
        ("d3d12-nvidia", 5),
    ]


def test_versioned_config_hashes_match_current_frozen_inputs():
    config_path = ROOT / "configs/vio_renderer_stability.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    actual = calculate_frozen_hashes(
        config_path,
        ROOT / config["profile"],
        ROOT / config["policy"],
    )

    assert {key: actual[key] for key in config["expected_hashes"]} == config["expected_hashes"]


def test_campaign_cli_can_run_as_a_script_file():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/run_renderer_stability_campaign_wsl.py"), "--help"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_formal_execution_uses_exact_schedule_and_campaign_output_root(tmp_path):
    calls = []
    campaign_dir = tmp_path / "formal-a"

    def fake_run_trial(**kwargs):
        calls.append(kwargs)
        trial_dir = kwargs["output_root"] / kwargs["name"]
        trial_dir.mkdir(parents=True)
        manifest = {
            "name": kwargs["name"],
            "renderer": {"requested_profile": kwargs["renderer_profile"],
                         "attestation": {"accepted": True,
                                         "requested_profile": kwargs["renderer_profile"]}},
            "evidence_accepted": True,
        }
        (trial_dir / "trial-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def fake_summary(trial_dir):
        summary = {"name": trial_dir.name, "operational_continuity_pass": True}
        (trial_dir / "stress-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    execute_campaign(
        campaign_id="formal-a",
        phase="formal",
        profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz",
        campaign_dir=campaign_dir,
        config=_config(),
        controller_revision="revision-a",
        frozen_hashes={"profile": "p", "model": "m", "config": "c"},
        run_trial_fn=fake_run_trial,
        summarize_trial_fn=fake_summary,
        resources_free_fn=lambda: True,
        formal_trial_score_fn=lambda _manifest, _summary: {"passed": True, "failures": []},
        campaign_score_fn=lambda _trials: {"d3d12_stability_gate_pass": True},
    )

    assert [call["name"] for call in calls] == [item.name for item in campaign_schedule()]
    assert [call["renderer_profile"] for call in calls] == [
        item.renderer_profile for item in campaign_schedule()
    ]
    assert all(call["output_root"] == campaign_dir for call in calls)
    assert all(call["fleet_size"] == 5 for call in calls)


@pytest.mark.parametrize(
    "mutation",
    ["controller_revision", "frozen_hashes", "seed", "schedule", "requested_profile"],
)
def test_existing_campaign_refuses_any_frozen_input_drift(tmp_path, mutation):
    expected = build_campaign_manifest(
        campaign_id="formal-a",
        phase="formal",
        config=_config(),
        profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz",
        controller_revision="revision-a",
        frozen_hashes={"profile": "p", "model": "m", "config": "c"},
    )
    existing = copy.deepcopy(expected)
    if mutation == "controller_revision":
        existing["controller_revision"] = "other"
    elif mutation == "frozen_hashes":
        existing["frozen_hashes"]["profile"] = "other"
    elif mutation == "seed":
        existing["seed"] = 7
    elif mutation == "schedule":
        existing["schedule"] = existing["schedule"][:-1]
    else:
        existing["schedule"][0]["renderer_profile"] = "d3d12-nvidia"

    with pytest.raises(RuntimeError, match="frozen campaign manifest mismatch"):
        validate_existing_campaign(existing, expected)


def test_resume_skips_complete_trial_and_never_overwrites_existing_directory(tmp_path):
    campaign_dir = tmp_path / "formal-a"
    first = campaign_schedule()[0]
    trial_dir = campaign_dir / first.name
    trial_dir.mkdir(parents=True)
    existing_campaign = build_campaign_manifest(
        campaign_id="formal-a",
        phase="formal",
        config=_config(),
        profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz",
        controller_revision="revision-a",
        frozen_hashes={"profile": "p", "model": "m", "config": "c"},
    )
    (campaign_dir / "campaign-manifest.json").write_text(
        json.dumps(existing_campaign), encoding="utf-8"
    )
    (trial_dir / "trial-manifest.json").write_text(json.dumps({"name": first.name}), encoding="utf-8")
    (trial_dir / "stress-summary.json").write_text(json.dumps({"name": first.name}), encoding="utf-8")
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        current = kwargs["output_root"] / kwargs["name"]
        current.mkdir(parents=True)
        manifest = {"name": kwargs["name"]}
        (current / "trial-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def fake_summary(current):
        summary = {"name": current.name}
        (current / "stress-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    execute_campaign(
        campaign_id="formal-a",
        phase="formal",
        profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz",
        campaign_dir=campaign_dir,
        config=_config(),
        controller_revision="revision-a",
        frozen_hashes={"profile": "p", "model": "m", "config": "c"},
        run_trial_fn=fake_run,
        summarize_trial_fn=fake_summary,
        resources_free_fn=lambda: True,
        formal_trial_score_fn=lambda _manifest, _summary: {"passed": True, "failures": []},
        campaign_score_fn=lambda _trials: {"d3d12_stability_gate_pass": True},
    )

    assert first.name not in [call["name"] for call in calls]


def test_campaign_snapshot_reads_manifest_names_and_indexes_raw_evidence(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    trial_name = "manifest-selected-trial"
    source.mkdir()
    (source / "campaign-manifest.json").write_text(
        json.dumps({"campaign_id": "c", "schedule": [{"name": trial_name}]}), encoding="utf-8"
    )
    (source / "campaign-summary.json").write_text("{}", encoding="utf-8")
    trial = source / trial_name
    (trial / "px4-ulogs").mkdir(parents=True)
    for name in ("trial-manifest.json", "stress-summary.json", "renderer-attestation.json",
                 "cleanup-evidence.json"):
        (trial / name).write_text("{}", encoding="utf-8")
    (trial / "agent-0.csv").write_text("x\n1\n", encoding="utf-8")
    (trial / "px4-ulogs/agent-0.ulg").write_bytes(b"ulog")
    (trial / "trajectory-replay.html").write_text("<html></html>", encoding="utf-8")
    (trial / "gazebo.stdout.log").write_text("log", encoding="utf-8")

    index = snapshot_renderer_campaign(source, target)

    assert (target / trial_name / "renderer-attestation.json").is_file()
    indexed = index["trials"][trial_name]
    assert "agent-0.csv" in indexed
    assert "px4-ulogs/agent-0.ulg" in indexed
    assert "trajectory-replay.html" in indexed
    assert "gazebo.stdout.log" in indexed
