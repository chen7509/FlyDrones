"""Run the frozen ten-cycle PX4/Gazebo takeoff stability campaign."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__:
    from tools.run_vio_stress_trial_wsl import ROOT, _tree_sha256, git_revision, run_trial, sha256
    from tools.summarize_vio_stress_wsl import summarize_trial
else:
    from run_vio_stress_trial_wsl import ROOT, _tree_sha256, git_revision, run_trial, sha256
    from summarize_vio_stress_wsl import summarize_trial

DEFAULT_CONFIG = ROOT / "configs/px4_takeoff_stability.json"
DEFAULT_OUTPUT_ROOT = ROOT / "results/px4-takeoff-stability"


@dataclass(frozen=True)
class TakeoffCampaignRun:
    name: str
    renderer_profile: str
    fleet_size: int
    takeoff_only_hold_s: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def takeoff_stability_schedule(config: Mapping[str, object]) -> tuple[TakeoffCampaignRun, ...]:
    expected_names = [f"takeoff-stability-{index:02d}" for index in range(1, 11)]
    required = {
        "schema": "flydrones-px4-takeoff-stability-config-v1",
        "seed": 240901,
        "renderer_profile": "d3d12-nvidia",
        "fleet_size": 5,
        "takeoff_only_hold_s": 2.0,
        "run_count": 10,
        "schedule": expected_names,
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise RuntimeError("config differs from the approved PX4 takeoff stability schedule")
    return tuple(
        TakeoffCampaignRun(
            name=name,
            renderer_profile="d3d12-nvidia",
            fleet_size=5,
            takeoff_only_hold_s=2.0,
        )
        for name in expected_names
    )


def build_takeoff_campaign_manifest(
    *,
    campaign_id: str,
    config: Mapping[str, object],
    profile: Path,
    model: Path,
    controller_revision: str,
    frozen_hashes: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema": "flydrones-px4-takeoff-stability-campaign-manifest-v1",
        "campaign_id": campaign_id,
        "seed": config.get("seed"),
        "profile": str(profile.resolve()),
        "model": str(model.resolve()),
        "controller_revision": controller_revision,
        "frozen_hashes": dict(frozen_hashes),
        "schedule": [item.as_dict() for item in takeoff_stability_schedule(config)],
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
            "seed",
            "profile",
            "model",
            "controller_revision",
            "frozen_hashes",
            "schedule",
        )
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _score_takeoff_trial(
    run: TakeoffCampaignRun,
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
) -> dict[str, object]:
    failures: list[str] = []
    if manifest.get("schema") != "flydrones-vio-stress-trial-v3":
        failures.append("trial-schema-mismatch")
    if manifest.get("evidence_accepted") is not True:
        failures.append("trial-evidence-rejected")
    chains = summary.get("takeoff_chain_by_vehicle")
    if not isinstance(chains, Mapping) or len(chains) != run.fleet_size:
        failures.append("takeoff-chain-count-mismatch")
        chains = {}
    mission_ready = 0
    landed = 0
    for vehicle_id in range(run.fleet_size):
        chain = chains.get(str(vehicle_id)) if isinstance(chains, Mapping) else None
        if not isinstance(chain, Mapping):
            failures.append(f"vehicle-{vehicle_id}-takeoff-chain-missing")
            continue
        if chain.get("accepted") is True:
            mission_ready += 1
        else:
            failures.append(
                f"vehicle-{vehicle_id}-{chain.get('reason') or 'takeoff-chain-rejected'}"
            )
        if chain.get("landed") is True:
            landed += 1
        else:
            failures.append(f"vehicle-{vehicle_id}-landing-not-confirmed")
    if summary.get("all_takeoff_chains_proven") is not True:
        failures.append("all-takeoff-chains-not-proven")
    clean = summary.get("trial_cleanup_verified") is True
    if not clean:
        failures.append("trial-cleanup-not-verified")
    return {
        "name": run.name,
        "passed": not failures,
        "failures": failures,
        "mission_ready": mission_ready,
        "landed": landed,
        "clean": clean,
    }


def execute_takeoff_campaign(
    *,
    campaign_id: str,
    profile: Path,
    model: Path,
    campaign_dir: Path,
    config: Mapping[str, object],
    controller_revision: str,
    frozen_hashes: Mapping[str, str],
    run_trial_fn: Callable[..., dict] = run_trial,
    summarize_trial_fn: Callable[[Path], dict] = summarize_trial,
    resources_free_fn: Callable[[], bool] = resources_free,
) -> dict[str, object]:
    schedule = takeoff_stability_schedule(config)
    expected = build_takeoff_campaign_manifest(
        campaign_id=campaign_id,
        config=config,
        profile=profile,
        model=model,
        controller_revision=controller_revision,
        frozen_hashes=frozen_hashes,
    )
    manifest_path = campaign_dir / "campaign-manifest.json"
    if manifest_path.exists():
        campaign_manifest = _load_json(manifest_path)
        if _immutable_manifest_fields(campaign_manifest) != _immutable_manifest_fields(expected):
            raise RuntimeError("frozen campaign manifest mismatch; start a new campaign ID")
    else:
        if campaign_dir.exists() and any(campaign_dir.iterdir()):
            raise RuntimeError("campaign directory is nonempty but has no campaign manifest")
        campaign_manifest = copy.deepcopy(expected)
        _atomic_json(manifest_path, campaign_manifest)

    trial_results: list[dict[str, object]] = []
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
        else:
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources are still in use before {run.name}")
            trial_manifest = run_trial_fn(
                name=run.name,
                profile=profile,
                fleet_size=run.fleet_size,
                model=model,
                renderer_profile=run.renderer_profile,
                campaign_id=campaign_id,
                output_root=campaign_dir,
                takeoff_only_hold_s=run.takeoff_only_hold_s,
            )
            if not trial_manifest_path.is_file():
                raise RuntimeError(f"trial did not preserve its manifest: {run.name}")
            trial_summary = summarize_trial_fn(trial_dir)
            if not trial_summary_path.is_file():
                _atomic_json(trial_summary_path, trial_summary)
            if not resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources were not released after {run.name}")

        score = _score_takeoff_trial(run, trial_manifest, trial_summary)
        trial_results.append(score)
        completed = campaign_manifest["completed_trials"]
        if run.name not in completed:
            completed.append(run.name)
        if not score["passed"]:
            campaign_manifest["stopped_after"] = run.name
            campaign_manifest["stop_reasons"] = list(score["failures"])
        _atomic_json(manifest_path, campaign_manifest)
        if not score["passed"]:
            break

    mission_ready = sum(int(item["mission_ready"]) for item in trial_results)
    landed = sum(int(item["landed"]) for item in trial_results)
    clean_trials = sum(bool(item["clean"]) for item in trial_results)
    accepted = bool(
        len(trial_results) == len(schedule)
        and all(item["passed"] for item in trial_results)
        and mission_ready == 50
        and landed == 50
        and clean_trials == 10
        and campaign_manifest["stopped_after"] is None
    )
    result = {
        "schema": "flydrones-px4-takeoff-stability-summary-v1",
        "campaign_id": campaign_id,
        "accepted": accepted,
        "completed_trials": list(campaign_manifest["completed_trials"]),
        "stopped_after": campaign_manifest["stopped_after"],
        "stop_reasons": list(campaign_manifest["stop_reasons"]),
        "metrics": {
            "mission_ready": mission_ready,
            "landed": landed,
            "clean_trials": clean_trials,
            "expected_vehicles": 50,
            "expected_trials": 10,
        },
        "trials": trial_results,
    }
    _atomic_json(campaign_dir / "campaign-summary.json", result)
    return result


def calculate_takeoff_frozen_hashes(
    config_path: Path,
    profile: Path,
    model: Path,
) -> dict[str, str]:
    return {
        "config": sha256(config_path),
        "profile": sha256(profile),
        "policy": sha256(model),
        "controller": sha256(ROOT / "src/flydrones/distributed_px4.py"),
        "coordinator": sha256(ROOT / "tools/run_distributed_px4_swarm.py"),
        "agent": sha256(ROOT / "tools/px4_distributed_agent.py"),
        "relay": sha256(ROOT / "tools/relay_gazebo_vio.py"),
        "trial_runner": sha256(ROOT / "tools/run_vio_stress_trial_wsl.py"),
        "takeoff_stability_runner": sha256(Path(__file__)),
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
        "summary": sha256(ROOT / "tools/summarize_vio_stress_wsl.py"),
        "world_generator": sha256(ROOT / "tools/generate_px4_forest_world.py"),
        "camera_model": _tree_sha256(ROOT / "assets/gazebo/models/OakD-Lite-Fly"),
        "vehicle_model": _tree_sha256(ROOT / "assets/gazebo/models/x500_depth_fly"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    config = _load_json(args.config)
    profile = ROOT / str(config["profile"])
    model = ROOT / str(config["policy"])
    frozen_hashes = calculate_takeoff_frozen_hashes(args.config, profile, model)
    expected_hashes = config.get("expected_hashes")
    if expected_hashes and any(
        frozen_hashes.get(key) != value for key, value in expected_hashes.items()
    ):
        raise RuntimeError("current inputs do not match config expected_hashes")
    result = execute_takeoff_campaign(
        campaign_id=args.campaign_id,
        profile=profile,
        model=model,
        campaign_dir=args.output_root / args.campaign_id,
        config=config,
        controller_revision=git_revision(ROOT),
        frozen_hashes=frozen_hashes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
