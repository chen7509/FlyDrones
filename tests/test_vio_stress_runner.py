import json
import signal
import subprocess

import pytest

from tools.run_vio_stress_trial_wsl import (
    apply_actuator_probe_evidence,
    apply_renderer_attestation,
    camera_aux_closed_cleanly,
    camera_auxiliary_commands,
    campaign_run_directory,
    copy_px4_console_logs,
    create_trial_manifest,
    git_revision,
    relay_closed_cleanly,
    shared_px4_files_restored,
    terminate_worker_process_group,
    trial_frozen_hashes,
    validate_camera_schedule_options,
    wait_for_probe_readiness,
)


def test_git_revision_falls_back_to_windows_git_for_windows_managed_wsl_worktree(tmp_path):
    calls = []

    def fake_check_output(command, **_kwargs):
        calls.append(command)
        if command[0] == "git":
            raise subprocess.CalledProcessError(128, command)
        if command[0] == "wslpath":
            return "C:\\worktree\n"
        return "revision123\n"

    assert git_revision(tmp_path, check_output=fake_check_output) == "revision123"
    assert calls == [
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        ["wslpath", "-w", str(tmp_path)],
        ["git.exe", "-C", "C:\\worktree", "rev-parse", "HEAD"],
    ]


def test_campaign_run_directories_are_isolated_by_campaign_id(tmp_path):
    first = campaign_run_directory("same-trial", "campaign-a", temp_root=tmp_path)
    second = campaign_run_directory("same-trial", "campaign-b", temp_root=tmp_path)

    assert first != second
    assert first.name == "flydrones-vio-campaign-a-same-trial"


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


def test_v3_manifest_freezes_renderer_pair_versions_and_hashes(tmp_path):
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
        camera_schedule_mode="phased",
    )

    assert manifest["schema"] == "flydrones-vio-stress-trial-v3"
    assert manifest["actuator_probe_closed_cleanly"] is False
    assert manifest["seed"] == 240901
    assert manifest["repository_revision"] == "repo123"
    assert manifest["px4_revision"] == "px4123"
    assert manifest["renderer"]["requested_profile"] == "default"
    assert manifest["pair"] == {"id": 1, "position": 1}
    assert manifest["campaign_id"] == "campaign-a"
    assert manifest["frozen_hashes"]["camera_model"] == "camera-sha"
    assert manifest["software_versions"]["mesa"] == "25.2.8"
    assert manifest["output_root"] == str(tmp_path / "campaign-a")
    assert manifest["camera_schedule_mode"] == "phased"
    assert manifest["camera_scheduler_stop_after_trigger_count"] is None
    assert manifest["camera_model_evidence"] is None
    assert manifest["camera_scheduler_closed_cleanly"] is False
    assert manifest["camera_phase_probe_closed_cleanly"] is False
    assert manifest["base_camera_asset_unchanged"] is None


def test_camera_schedule_options_default_and_formal_fault_injection_gate():
    assert validate_camera_schedule_options("simultaneous", None, pair_id=None) == "simultaneous"
    assert validate_camera_schedule_options("phased", 7, pair_id=None) == "phased"
    with pytest.raises(ValueError, match="camera_schedule_mode"):
        validate_camera_schedule_options("staggered", None, pair_id=None)
    with pytest.raises(ValueError, match="positive"):
        validate_camera_schedule_options("phased", 0, pair_id=None)
    with pytest.raises(ValueError, match="formal"):
        validate_camera_schedule_options("phased", 7, pair_id=1)


def test_camera_auxiliary_commands_start_observer_in_both_modes_and_scheduler_only_phased(tmp_path):
    simultaneous = camera_auxiliary_commands(
        mode="simultaneous", output=tmp_path, completion_marker=tmp_path / "done",
        fleet_size=5,
    )
    assert len(simultaneous) == 1
    assert simultaneous[0][1].endswith("probe_camera_phase_wsl.py")
    assert "--mode" in simultaneous[0] and "simultaneous" in simultaneous[0]

    phased = camera_auxiliary_commands(
        mode="phased", output=tmp_path, completion_marker=tmp_path / "done",
        fleet_size=5,
    )
    assert len(phased) == 2
    assert phased[0][1].endswith("run_camera_phase_scheduler_wsl.py")
    assert "--formal" in phased[0]
    assert phased[1][1].endswith("probe_camera_phase_wsl.py")
    assert str(tmp_path / "camera-scheduler-ready.json") in phased[1]


def test_camera_aux_clean_stop_requires_complete_successful_stop_record(tmp_path):
    log = tmp_path / "camera-phase.jsonl"
    log.write_text('{"event":"ready"}\n{"event":"stop","exit_code":0,"completed":true}\n', encoding="utf-8")
    assert camera_aux_closed_cleanly(log, require_completed=True)
    log.write_text('{"event":"ready"}\n{"event":"stop","exit_code":0,"completed":false}\n', encoding="utf-8")
    assert not camera_aux_closed_cleanly(log, require_completed=True)
    log.write_text('{"event":"ready"}\n{"event":"stop"', encoding="utf-8")
    assert not camera_aux_closed_cleanly(log, require_completed=False)


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


def test_worker_start_waits_until_actuator_probe_readiness_marker(tmp_path):
    marker = tmp_path / "actuator-probe-ready.json"
    events = []

    class Probe:
        def poll(self):
            events.append("poll")
            return None

    times = iter((0.0, 0.1, 0.2, 0.3))

    def sleep(_duration):
        events.append("sleep")
        marker.write_text(json.dumps({"ready": True}), encoding="utf-8")

    wait_for_probe_readiness(
        marker,
        Probe(),
        timeout_s=1.0,
        monotonic=lambda: next(times),
        sleep=sleep,
    )
    events.append("worker-start")

    assert events.index("sleep") < events.index("worker-start")
    assert marker.is_file()


def test_probe_readiness_timeout_and_truncated_log_reject_evidence(tmp_path):
    class Probe:
        def poll(self):
            return None

    times = iter((0.0, 0.2))
    with pytest.raises(TimeoutError, match="actuator probe readiness"):
        wait_for_probe_readiness(
            tmp_path / "missing-ready.json",
            Probe(),
            timeout_s=0.1,
            monotonic=lambda: next(times),
            sleep=lambda _duration: None,
        )

    path = tmp_path / "actuator-link.jsonl"
    original = '{"event":"start","monotonic_s":1.0}\n{"event":"stop"'
    path.write_text(original, encoding="utf-8")
    manifest = {"evidence_accepted": True, "errors": []}

    apply_actuator_probe_evidence(manifest, path)

    assert path.read_text(encoding="utf-8") == original
    assert not manifest["actuator_probe_closed_cleanly"]
    assert not manifest["evidence_accepted"]


def test_all_px4_instance_console_logs_are_copied(tmp_path):
    run_dir = tmp_path / "run"
    output = tmp_path / "output"
    for vehicle_id in range(5):
        instance = run_dir / f"instance_{vehicle_id}"
        instance.mkdir(parents=True)
        (instance / "out.log").write_text(f"out-{vehicle_id}", encoding="utf-8")
        (instance / "err.log").write_text(f"err-{vehicle_id}", encoding="utf-8")

    artifacts = copy_px4_console_logs(run_dir, output, fleet_size=5)

    assert len(artifacts) == 10
    assert (output / "px4-console/instance_4/out.log").read_text(encoding="utf-8") == "out-4"
    assert (output / "px4-console/instance_4/err.log").read_text(encoding="utf-8") == "err-4"
    assert all(artifact["sha256"] for artifact in artifacts)


def test_frozen_hashes_include_actuator_probe_and_readiness_module(tmp_path):
    profile = tmp_path / "profile.json"
    model = tmp_path / "policy.npz"
    profile.write_text("{}", encoding="utf-8")
    model.write_bytes(b"policy")

    hashes = trial_frozen_hashes(profile=profile, model=model)

    assert hashes["actuator_probe"]
    assert hashes["takeoff_readiness"]
    assert hashes["mavlink_drone"]
    assert hashes["camera_phase"]
    assert hashes["camera_model_configurator"]
    assert hashes["camera_phase_scheduler"]
    assert hashes["camera_phase_probe"]


def test_schema_readiness_marker_can_gate_worker_start(tmp_path):
    marker = tmp_path / "camera-phase-ready.json"

    class Probe:
        def poll(self):
            return None

    times = iter((0.0, 0.1, 0.2, 0.3))

    def sleep(_duration):
        marker.write_text(json.dumps({"schema": "flydrones-camera-phase-ready-v1"}), encoding="utf-8")

    wait_for_probe_readiness(
        marker,
        Probe(),
        timeout_s=1.0,
        required_schema="flydrones-camera-phase-ready-v1",
        label="camera phase probe",
        monotonic=lambda: next(times),
        sleep=sleep,
    )
