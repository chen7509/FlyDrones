"""Run an immutable smoke or formal Gazebo renderer stability campaign."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flydrones.renderer_stability import campaign_schedule, score_campaign, score_renderer_trial

if __package__:
    from tools.run_vio_stress_trial_wsl import ROOT, _tree_sha256, git_revision, run_trial, sha256
    from tools.summarize_vio_stress_wsl import summarize_trial
else:
    from run_vio_stress_trial_wsl import ROOT, _tree_sha256, git_revision, run_trial, sha256
    from summarize_vio_stress_wsl import summarize_trial

DEFAULT_CONFIG = ROOT / "configs/vio_renderer_stability.json"
DEFAULT_OUTPUT_ROOT = ROOT / "results/vio-renderer-stability"


@dataclass(frozen=True)
class CampaignRun:
    name: str
    renderer_profile: str
    fleet_size: int
    pair_id: int | None = None
    pair_position: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def smoke_schedule() -> tuple[CampaignRun, ...]:
    return (
        CampaignRun("smoke-default-single", "default", 1),
        CampaignRun("smoke-d3d12-single", "d3d12-nvidia", 1),
        CampaignRun("smoke-d3d12-five-startup", "d3d12-nvidia", 5),
    )


def _formal_schedule(config: Mapping[str, object]) -> tuple[CampaignRun, ...]:
    expected = [item.as_dict() for item in campaign_schedule()]
    if config.get("schedule") != expected:
        raise RuntimeError("config schedule differs from the approved ten-run schedule")
    return tuple(CampaignRun(fleet_size=5, **item) for item in expected)


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
    schedule = smoke_schedule() if phase == "smoke" else _formal_schedule(config)
    return {
        "schema": "flydrones-renderer-stability-campaign-manifest-v1",
        "campaign_id": campaign_id,
        "phase": phase,
        "seed": config.get("seed"),
        "profile": str(profile.resolve()),
        "model": str(model.resolve()),
        "controller_revision": controller_revision,
        "frozen_hashes": dict(frozen_hashes),
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
            "controller_revision",
            "frozen_hashes",
            "schedule",
        )
    }


def validate_existing_campaign(existing: Mapping[str, object], expected: Mapping[str, object]) -> None:
    if _immutable_manifest_fields(existing) != _immutable_manifest_fields(expected):
        raise RuntimeError("frozen campaign manifest mismatch; start a new campaign ID")


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def resources_free() -> bool:
    output = subprocess.check_output(["ps", "-eo", "args="], text=True)
    markers = (
        "/build/px4_sitl_default/bin/px4 -i ",
        "gz sim -r -s ",
        "tools/relay_gazebo_vio.py",
        "tools/px4_distributed_agent.py",
        "tools/run_distributed_px4_swarm.py",
        "tools/probe_gazebo_runtime_wsl.py",
        "tools/probe_gazebo_actuator_link.py",
    )
    return not any(any(marker in line for marker in markers) for line in output.splitlines())


def _smoke_score(run: CampaignRun, manifest: Mapping[str, object], summary: Mapping[str, object]) -> dict:
    failures = []
    renderer = manifest.get("renderer") if isinstance(manifest.get("renderer"), Mapping) else {}
    attestation = renderer.get("attestation") if isinstance(renderer.get("attestation"), Mapping) else {}
    if manifest.get("launch_exit_code") != 0:
        failures.append("launch_failed")
    if manifest.get("stop_exit_code") != 0 or manifest.get("shared_px4_files_restored") is not True:
        failures.append("cleanup_failed")
    if manifest.get("evidence_accepted") is not True:
        failures.append("evidence_rejected")
    if attestation.get("accepted") is not True:
        failures.append("renderer_attestation_rejected")
    if attestation.get("expected_depth_topics") != run.fleet_size:
        failures.append("depth_topic_count_mismatch")
    if run.renderer_profile == "d3d12-nvidia":
        renderer_name = str(attestation.get("egl_renderer", ""))
        libraries = {Path(str(item)).name for item in attestation.get("mapped_libraries", [])}
        if "D3D12" not in renderer_name or "RTX 3070 Ti" not in renderer_name:
            failures.append("rtx_3070_ti_d3d12_not_attested")
        if not {"libd3d12.so", "libdxcore.so"}.issubset(libraries):
            failures.append("d3d12_libraries_not_attested")
    workers = summary.get("workers") if isinstance(summary.get("workers"), list) else []
    if run.fleet_size == 1 and (
        len(workers) != 1
        or workers[0].get("mission_accepted") is not True
        or workers[0].get("landed") is not True
    ):
        failures.append("single_vehicle_mission_or_landing_failed")
    return {"name": run.name, "passed": not failures, "failures": failures}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
    formal_trial_score_fn: Callable[[Mapping[str, object], Mapping[str, object]], dict] = score_renderer_trial,
    campaign_score_fn: Callable[[Any], dict] = score_campaign,
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

    schedule = smoke_schedule() if phase == "smoke" else _formal_schedule(config)
    collected: list[tuple[dict, dict]] = []
    smoke_results = []
    stopped = False
    for run in schedule:
        trial_dir = campaign_dir / run.name
        trial_manifest_path = trial_dir / "trial-manifest.json"
        trial_summary_path = trial_dir / "stress-summary.json"
        if trial_dir.exists():
            if not trial_manifest_path.is_file() or not trial_summary_path.is_file():
                raise RuntimeError(f"existing trial is incomplete and will not be overwritten: {run.name}")
            trial_manifest = _load_json(trial_manifest_path)
            trial_summary = _load_json(trial_summary_path)
        else:
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources are still in use before {run.name}")
            trial_manifest = run_trial_fn(
                name=run.name,
                profile=profile,
                fleet_size=run.fleet_size,
                model=model,
                renderer_profile=run.renderer_profile,
                pair_id=run.pair_id,
                pair_position=run.pair_position,
                campaign_id=campaign_id,
                output_root=campaign_dir,
            )
            if not trial_manifest_path.is_file():
                raise RuntimeError(f"trial did not preserve its manifest: {run.name}")
            trial_summary = summarize_trial_fn(trial_dir)
            if not trial_summary_path.is_file():
                _atomic_json(trial_summary_path, trial_summary)
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources were not released after {run.name}")

        collected.append((trial_manifest, trial_summary))
        if run.name not in campaign_manifest["completed_trials"]:
            campaign_manifest["completed_trials"].append(run.name)
        score = (
            _smoke_score(run, trial_manifest, trial_summary)
            if phase == "smoke" else formal_trial_score_fn(trial_manifest, trial_summary)
        )
        if phase == "smoke":
            smoke_results.append(score)
        if not score.get("passed") and (phase == "smoke" or run.renderer_profile == "d3d12-nvidia"):
            campaign_manifest["stopped_after"] = run.name
            campaign_manifest["stop_reasons"] = list(score.get("failures", []))
            stopped = True
        _atomic_json(manifest_path, campaign_manifest)
        if stopped:
            break

    if phase == "formal" and len(collected) == len(schedule) and not stopped:
        result: dict[str, object] = campaign_score_fn(collected)
    else:
        result = {
            "schema": "flydrones-renderer-stability-smoke-v1" if phase == "smoke"
            else "flydrones-renderer-stability-partial-v1",
            "campaign_id": campaign_id,
            "phase": phase,
            "completed_trials": list(campaign_manifest["completed_trials"]),
            "stopped_after": campaign_manifest["stopped_after"],
            "stop_reasons": list(campaign_manifest["stop_reasons"]),
            "trials": smoke_results,
            "passed": bool(phase == "smoke" and len(smoke_results) == len(schedule)
                           and all(item["passed"] for item in smoke_results)),
        }
    _atomic_json(campaign_dir / "campaign-summary.json", result)
    return result


def calculate_frozen_hashes(config_path: Path, profile: Path, model: Path) -> dict[str, str]:
    return {
        "config": sha256(config_path),
        "profile": sha256(profile),
        "policy": sha256(model),
        "controller": sha256(ROOT / "src/flydrones/distributed_px4.py"),
        "coordinator": sha256(ROOT / "tools/run_distributed_px4_swarm.py"),
        "relay": sha256(ROOT / "tools/relay_gazebo_vio.py"),
        "runner": sha256(ROOT / "tools/run_vio_stress_trial_wsl.py"),
        "launcher": sha256(ROOT / "tools/launch_px4_depth_swarm_wsl.sh"),
        "renderer_attestation": sha256(ROOT / "tools/attest_gazebo_renderer_wsl.py"),
        "renderer_profile": sha256(ROOT / "src/flydrones/gazebo_renderer.py"),
        "runtime_probe": sha256(ROOT / "tools/probe_gazebo_runtime_wsl.py"),
        "actuator_probe": sha256(ROOT / "tools/probe_gazebo_actuator_link.py"),
        "takeoff_readiness": sha256(ROOT / "src/flydrones/takeoff_readiness.py"),
        "mavlink_drone": sha256(ROOT / "src/flydrones/drones/mavlink.py"),
        "camera_phase": sha256(ROOT / "src/flydrones/camera_phase.py"),
        "camera_model_configurator": sha256(ROOT / "tools/configure_gazebo_camera_phase.py"),
        "camera_phase_scheduler": sha256(ROOT / "tools/run_camera_phase_scheduler_wsl.py"),
        "camera_phase_probe": sha256(ROOT / "tools/probe_camera_phase_wsl.py"),
        "takeoff_stability_runner": sha256(ROOT / "tools/run_takeoff_stability_campaign_wsl.py"),
        "summary": sha256(ROOT / "tools/summarize_vio_stress_wsl.py"),
        "evidence": sha256(ROOT / "src/flydrones/vio_stress_evidence.py"),
        "world_generator": sha256(ROOT / "tools/generate_px4_forest_world.py"),
        "camera_model": _tree_sha256(ROOT / "assets/gazebo/models/OakD-Lite-Fly"),
        "vehicle_model": _tree_sha256(ROOT / "assets/gazebo/models/x500_depth_fly"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    config = _load_json(args.config)
    frozen_hashes = calculate_frozen_hashes(args.config, args.profile, args.model)
    expected_hashes = config.get("expected_hashes")
    if expected_hashes and any(frozen_hashes.get(key) != value for key, value in expected_hashes.items()):
        raise RuntimeError("current inputs do not match config expected_hashes")
    revision = git_revision(ROOT)
    result = execute_campaign(
        campaign_id=args.campaign_id,
        phase=args.phase,
        profile=args.profile,
        model=args.model,
        campaign_dir=args.output_root / args.campaign_id,
        config=config,
        controller_revision=revision,
        frozen_hashes=frozen_hashes,
    )
    if args.phase == "smoke":
        return 0 if result.get("passed") else 1
    return 0 if result.get("d3d12_stability_gate_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
