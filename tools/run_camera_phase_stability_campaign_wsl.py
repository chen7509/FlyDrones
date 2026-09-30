"""Run immutable smoke and paired camera-phase campaigns under WSL."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from flydrones.camera_phase_stability import (
    CameraPhaseRun,
    formal_schedule,
    score_phase_campaign,
    score_phase_trial,
    smoke_schedule,
)

if __package__:
    from tools.run_vio_stress_trial_wsl import (
        ROOT,
        _tree_sha256,
        git_revision,
        run_trial,
        sha256,
    )
    from tools.summarize_vio_stress_wsl import summarize_trial
else:
    from run_vio_stress_trial_wsl import ROOT, _tree_sha256, git_revision, run_trial, sha256
    from summarize_vio_stress_wsl import summarize_trial
DEFAULT_CONFIG = ROOT / "configs/vio_camera_phase_stability.json"
DEFAULT_OUTPUT_ROOT = ROOT / "results/camera-phase-stability"


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schedule(phase: str, config: Mapping[str, object]) -> tuple[CameraPhaseRun, ...]:
    return smoke_schedule() if phase == "smoke" else formal_schedule(config)


def build_campaign_manifest(
    *,
    campaign_id: str,
    phase: str,
    config: Mapping[str, object],
    profile: Path,
    model: Path,
    controller_revision: str,
    frozen_hashes: Mapping[str, str],
) -> dict[str, object]:
    schedule = _schedule(phase, config)
    return {
        "schema": "flydrones-camera-phase-stability-campaign-manifest-v1",
        "campaign_id": campaign_id,
        "phase": phase,
        "seed": config.get("seed"),
        "profile": str(profile.resolve()),
        "model": str(model.resolve()),
        "renderer_profile": "d3d12-nvidia",
        "controller_revision": controller_revision,
        "frozen_hashes": dict(frozen_hashes),
        "thresholds": copy.deepcopy(config.get("thresholds")),
        "schedule": [item.as_dict() for item in schedule],
        "completed_trials": [],
        "stopped_after": None,
        "stop_reasons": [],
    }


def _immutable_manifest_fields(manifest: Mapping[str, object]) -> dict[str, object]:
    return {
        key: manifest.get(key)
        for key in (
            "schema",
            "campaign_id",
            "phase",
            "seed",
            "profile",
            "model",
            "renderer_profile",
            "controller_revision",
            "frozen_hashes",
            "thresholds",
            "schedule",
        )
    }


def validate_existing_campaign(existing: Mapping[str, object], expected: Mapping[str, object]) -> None:
    if _immutable_manifest_fields(existing) != _immutable_manifest_fields(expected):
        raise RuntimeError("frozen campaign manifest mismatch; start a new campaign ID")


def resources_free() -> bool:
    output = subprocess.check_output(["ps", "-eo", "args="], text=True)
    markers = (
        "/build/px4_sitl_default/bin/px4 -i ",
        "gz sim ",
        "tools/relay_gazebo_vio.py",
        "tools/px4_distributed_agent.py",
        "tools/run_distributed_px4_swarm.py",
        "tools/probe_gazebo_runtime_wsl.py",
        "tools/probe_gazebo_actuator_link.py",
        "tools/probe_camera_phase_wsl.py",
        "tools/run_camera_phase_scheduler_wsl.py",
    )
    return not any(any(marker in line for marker in markers) for line in output.splitlines())


def _validate_resumed_trial(
    run: CameraPhaseRun,
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    *,
    campaign_id: str,
    frozen_hashes: Mapping[str, str],
) -> None:
    pair = manifest.get("pair") if isinstance(manifest.get("pair"), Mapping) else {}
    renderer = (
        manifest.get("renderer") if isinstance(manifest.get("renderer"), Mapping) else {}
    )
    if (
        manifest.get("name") != run.name
        or summary.get("name") != run.name
        or manifest.get("campaign_id") != campaign_id
        or manifest.get("camera_schedule_mode") != run.camera_schedule_mode
        or manifest.get("fleet_size") != run.fleet_size
        or renderer.get("requested_profile") != "d3d12-nvidia"
        or pair.get("id") != run.pair_id
        or pair.get("position") != run.pair_position
    ):
        raise RuntimeError(f"existing trial does not match frozen schedule: {run.name}")
    trial_hashes = (
        manifest.get("frozen_hashes")
        if isinstance(manifest.get("frozen_hashes"), Mapping)
        else {}
    )
    hash_names = {
        "profile": "profile",
        "policy": "policy",
        "controller": "controller",
        "runner": "trial_runner",
        "launcher": "launcher",
        "camera_phase": "camera_phase",
        "camera_model_configurator": "camera_model_configurator",
        "camera_phase_scheduler": "camera_phase_scheduler",
        "camera_phase_probe": "camera_phase_probe",
        "summary": "summary",
        "world_generator": "world_generator",
        "camera_model": "camera_model",
        "vehicle_model": "vehicle_model",
    }
    if any(
        trial_hashes.get(trial_key) != frozen_hashes.get(campaign_key)
        for trial_key, campaign_key in hash_names.items()
    ):
        raise RuntimeError(f"existing trial frozen hashes do not match campaign: {run.name}")


def _smoke_score(
    run: CameraPhaseRun,
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    config: Mapping[str, object],
) -> dict[str, object]:
    if run.fleet_size == 5:
        return score_phase_trial(manifest, summary, config)
    failures: list[str] = []
    renderer = manifest.get("renderer") if isinstance(manifest.get("renderer"), Mapping) else {}
    attestation = renderer.get("attestation") if isinstance(renderer.get("attestation"), Mapping) else {}
    phase = summary.get("camera_phase") if isinstance(summary.get("camera_phase"), Mapping) else {}
    workers = summary.get("workers") if isinstance(summary.get("workers"), list) else []
    if manifest.get("evidence_accepted") is not True:
        failures.append("manifest_evidence_rejected")
    if manifest.get("camera_schedule_mode") != run.camera_schedule_mode:
        failures.append("camera_schedule_mode_mismatch")
    if attestation.get("accepted") is not True:
        failures.append("renderer_attestation_rejected")
    if phase.get("accepted") is not True or phase.get("mode") != run.camera_schedule_mode:
        failures.append("camera_phase_summary_rejected")
    if manifest.get("camera_phase_probe_closed_cleanly") is not True:
        failures.append("camera_phase_probe_not_clean")
    if manifest.get("camera_scheduler_closed_cleanly") is not True:
        failures.append("camera_scheduler_not_clean")
    if summary.get("all_takeoff_chains_proven") is not True:
        failures.append("takeoff_chain_rejected")
    if len(workers) != 1 or workers[0].get("mission_accepted") is not True:
        failures.append("single_vehicle_mission_failed")
    if len(workers) != 1 or workers[0].get("landed") is not True:
        failures.append("single_vehicle_landing_failed")
    if summary.get("trial_cleanup_verified") is not True:
        failures.append("cleanup_not_verified")
    return {"name": run.name, "passed": not failures, "failures": failures}


def execute_campaign(
    *,
    campaign_id: str,
    phase: str,
    profile: Path,
    model: Path,
    campaign_dir: Path,
    config: Mapping[str, object],
    controller_revision: str,
    frozen_hashes: Mapping[str, str],
    run_trial_fn: Callable[..., dict] = run_trial,
    summarize_trial_fn: Callable[[Path], dict] = summarize_trial,
    resources_free_fn: Callable[[], bool] = resources_free,
    trial_score_fn: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object]], dict] = score_phase_trial,
    campaign_score_fn: Callable[[Any, Mapping[str, object]], dict] = score_phase_campaign,
) -> dict[str, object]:
    if phase not in {"smoke", "formal"}:
        raise ValueError("phase must be smoke or formal")
    expected = build_campaign_manifest(
        campaign_id=campaign_id,
        phase=phase,
        config=config,
        profile=profile,
        model=model,
        controller_revision=controller_revision,
        frozen_hashes=frozen_hashes,
    )
    manifest_path = campaign_dir / "campaign-manifest.json"
    if manifest_path.exists():
        campaign_manifest = _load_json(manifest_path)
        validate_existing_campaign(campaign_manifest, expected)
    else:
        if campaign_dir.exists() and any(campaign_dir.iterdir()):
            raise RuntimeError("campaign directory is nonempty but has no campaign manifest")
        campaign_manifest = copy.deepcopy(expected)
        _atomic_json(manifest_path, campaign_manifest)

    schedule = _schedule(phase, config)
    collected: list[tuple[dict, dict]] = []
    scores: list[dict] = []
    stopped = False
    for run in schedule:
        trial_dir = campaign_dir / run.name
        trial_manifest_path = trial_dir / "trial-manifest.json"
        trial_summary_path = trial_dir / "stress-summary.json"
        if trial_dir.exists():
            if not trial_manifest_path.is_file() or not trial_summary_path.is_file():
                raise RuntimeError(
                    f"existing trial is incomplete and will not be overwritten: {run.name}"
                )
            trial_manifest = _load_json(trial_manifest_path)
            trial_summary = _load_json(trial_summary_path)
            _validate_resumed_trial(
                run,
                trial_manifest,
                trial_summary,
                campaign_id=campaign_id,
                frozen_hashes=frozen_hashes,
            )
        else:
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources are still in use before {run.name}")
            trial_manifest = run_trial_fn(
                name=run.name,
                profile=profile,
                fleet_size=run.fleet_size,
                model=model,
                renderer_profile="d3d12-nvidia",
                pair_id=run.pair_id,
                pair_position=run.pair_position,
                campaign_id=campaign_id,
                output_root=campaign_dir,
                camera_schedule_mode=run.camera_schedule_mode,
            )
            if not trial_manifest_path.is_file():
                raise RuntimeError(f"trial did not preserve its manifest: {run.name}")
            trial_summary = summarize_trial_fn(trial_dir)
            if not trial_summary_path.is_file():
                _atomic_json(trial_summary_path, trial_summary)
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources were not released after {run.name}")

        collected.append((trial_manifest, trial_summary))
        score = (
            _smoke_score(run, trial_manifest, trial_summary, config)
            if phase == "smoke"
            else trial_score_fn(trial_manifest, trial_summary, config)
        )
        scores.append(score)
        if run.name not in campaign_manifest["completed_trials"]:
            campaign_manifest["completed_trials"].append(run.name)
        if score.get("passed") is not True:
            campaign_manifest["stopped_after"] = run.name
            campaign_manifest["stop_reasons"] = list(score.get("failures", []))
            stopped = True
        _atomic_json(manifest_path, campaign_manifest)
        if stopped:
            break

    if phase == "formal" and len(collected) == len(schedule) and not stopped:
        result: dict[str, object] = campaign_score_fn(collected, config)
        result["campaign_id"] = campaign_id
    else:
        result = {
            "schema": (
                "flydrones-camera-phase-stability-smoke-v1"
                if phase == "smoke"
                else "flydrones-camera-phase-stability-partial-v1"
            ),
            "campaign_id": campaign_id,
            "phase": phase,
            "completed_trials": list(campaign_manifest["completed_trials"]),
            "stopped_after": campaign_manifest["stopped_after"],
            "stop_reasons": list(campaign_manifest["stop_reasons"]),
            "trials": scores,
            "passed": bool(
                phase == "smoke"
                and len(scores) == len(schedule)
                and all(score.get("passed") is True for score in scores)
            ),
        }
    _atomic_json(campaign_dir / "campaign-summary.json", result)
    return result


def calculate_frozen_hashes(config_path: Path, profile: Path, model: Path) -> dict[str, str]:
    files = {
        "profile": profile,
        "policy": model,
        "controller": ROOT / "src/flydrones/distributed_px4.py",
        "coordinator": ROOT / "tools/run_distributed_px4_swarm.py",
        "agent": ROOT / "tools/px4_distributed_agent.py",
        "relay": ROOT / "tools/relay_gazebo_vio.py",
        "trial_runner": ROOT / "tools/run_vio_stress_trial_wsl.py",
        "campaign_runner": Path(__file__),
        "camera_phase_stability": ROOT / "src/flydrones/camera_phase_stability.py",
        "launcher": ROOT / "tools/launch_px4_depth_swarm_wsl.sh",
        "stopper": ROOT / "tools/stop_px4_swarm_wsl.sh",
        "renderer_attestation": ROOT / "tools/attest_gazebo_renderer_wsl.py",
        "renderer_profile": ROOT / "src/flydrones/gazebo_renderer.py",
        "runtime_probe": ROOT / "tools/probe_gazebo_runtime_wsl.py",
        "actuator_probe": ROOT / "tools/probe_gazebo_actuator_link.py",
        "takeoff_readiness": ROOT / "src/flydrones/takeoff_readiness.py",
        "mavlink_drone": ROOT / "src/flydrones/drones/mavlink.py",
        "camera_phase": ROOT / "src/flydrones/camera_phase.py",
        "camera_model_configurator": ROOT / "tools/configure_gazebo_camera_phase.py",
        "camera_phase_scheduler": ROOT / "tools/run_camera_phase_scheduler_wsl.py",
        "camera_phase_probe": ROOT / "tools/probe_camera_phase_wsl.py",
        "summary": ROOT / "tools/summarize_vio_stress_wsl.py",
        "snapshot": ROOT / "tools/snapshot_vio_gate_results.py",
        "world_generator": ROOT / "tools/generate_px4_forest_world.py",
    }
    hashes = {key: sha256(path) for key, path in files.items()}
    hashes["config"] = sha256(config_path)
    hashes["camera_model"] = _tree_sha256(ROOT / "assets/gazebo/models/OakD-Lite-Fly")
    hashes["vehicle_model"] = _tree_sha256(ROOT / "assets/gazebo/models/x500_depth_fly")
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    config = _load_json(args.config)
    profile = ROOT / str(config["profile"])
    model = ROOT / str(config["policy"])
    frozen_hashes = calculate_frozen_hashes(args.config, profile, model)
    expected_hashes = config.get("expected_hashes")
    if expected_hashes and any(
        frozen_hashes.get(key) != value for key, value in expected_hashes.items()
    ):
        raise RuntimeError("current inputs do not match config expected_hashes")
    result = execute_campaign(
        campaign_id=args.campaign_id,
        phase=args.phase,
        profile=profile,
        model=model,
        campaign_dir=args.output_root / args.campaign_id,
        config=config,
        controller_revision=git_revision(ROOT),
        frozen_hashes=frozen_hashes,
    )
    if args.phase == "smoke":
        return 0 if result.get("passed") else 1
    return 0 if result.get("verdict") == "supported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
