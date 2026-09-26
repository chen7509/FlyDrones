import json
import signal

from tools.run_vio_stress_trial_wsl import (
    apply_renderer_attestation,
    create_trial_manifest,
    relay_closed_cleanly,
    shared_px4_files_restored,
    terminate_worker_process_group,
)


def test_shared_px4_restoration_requires_all_files_to_match(tmp_path):
    run_dir = tmp_path / "run"
    root = tmp_path / "px4"
    backup = run_dir / "backups"
    paths = (
        (backup / "world.sdf", root / "Tools/simulation/gz/worlds/flydrones_forest.sdf"),
        (backup / "OakD-Lite-Fly/model.sdf", root / "Tools/simulation/gz/models/OakD-Lite-Fly/model.sdf"),
        (backup / "x500_depth_fly/model.sdf", root / "Tools/simulation/gz/models/x500_depth_fly/model.sdf"),
    )
    for before, after in paths:
        before.parent.mkdir(parents=True, exist_ok=True)
        after.parent.mkdir(parents=True, exist_ok=True)
        before.write_text("original", encoding="utf-8")
        after.write_text("original", encoding="utf-8")
    assert shared_px4_files_restored(run_dir, root)
    paths[-1][1].write_text("fault routing left behind", encoding="utf-8")
    assert not shared_px4_files_restored(run_dir, root)


def test_truncated_relay_tail_does_not_abort_failure_preservation(tmp_path):
    path = tmp_path / "vio-relay.jsonl"
    path.write_text('{"event": "publish"}\n{"event": "stop"', encoding="utf-8")
    assert not relay_closed_cleanly(path)
    path.write_text('{"event": "publish"}\n{"event": "stop"}\n', encoding="utf-8")
    assert relay_closed_cleanly(path)


def test_v2_manifest_freezes_renderer_pair_versions_and_hashes(tmp_path):
    manifest = create_trial_manifest(
        name="renderer-pair-1-1-default",
        fleet_size=5,
        profile=tmp_path / "baseline.json",
        model=tmp_path / "policy.npz",
        renderer_profile="default",
        pair_id=1,
        pair_position=1,
        campaign_id="campaign-a",
        output_root=tmp_path / "campaign-a",
        repository_revision="repo123",
        px4_revision="px4123",
        frozen_hashes={
            "world": "world-sha",
            "camera_model": "camera-sha",
            "vehicle_model": "vehicle-sha",
            "policy": "policy-sha",
            "profile": "profile-sha",
            "controller": "controller-sha",
            "launcher": "launcher-sha",
        },
        software_versions={"gazebo": "8.15.0", "mesa": "25.2.8"},
    )

    assert manifest["schema"] == "flydrones-vio-stress-trial-v2"
    assert manifest["seed"] == 240901
    assert manifest["repository_revision"] == "repo123"
    assert manifest["px4_revision"] == "px4123"
    assert manifest["renderer"]["requested_profile"] == "default"
    assert manifest["pair"] == {"id": 1, "position": 1}
    assert manifest["campaign_id"] == "campaign-a"
    assert manifest["frozen_hashes"]["camera_model"] == "camera-sha"
    assert manifest["software_versions"]["mesa"] == "25.2.8"
    assert manifest["output_root"] == str(tmp_path / "campaign-a")


def test_rejected_or_missing_renderer_attestation_invalidates_evidence(tmp_path):
    manifest = {"evidence_accepted": True, "errors": [], "renderer": {"requested_profile": "d3d12-nvidia"}}

    apply_renderer_attestation(manifest, tmp_path / "missing.json")

    assert not manifest["evidence_accepted"]
    assert "renderer attestation missing" in manifest["errors"]

    rejected = tmp_path / "rejected.json"
    rejected.write_text(json.dumps({"accepted": False, "reasons": ["required_adapter_missing"]}), encoding="utf-8")
    manifest = {"evidence_accepted": True, "errors": [], "renderer": {"requested_profile": "d3d12-nvidia"}}
    apply_renderer_attestation(manifest, rejected)
    assert not manifest["evidence_accepted"]
    assert manifest["renderer"]["attestation"]["reasons"] == ["required_adapter_missing"]


def test_worker_timeout_signals_only_the_recorded_process_group():
    signals = []

    terminate_worker_process_group(7331, send_signal=lambda process_group, signum: signals.append((process_group, signum)))

    assert signals == [(7331, signal.SIGTERM), (7331, 9)]
