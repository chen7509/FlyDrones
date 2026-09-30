#!/usr/bin/env python3
"""Run the frozen twelve-slot no-worker camera capacity campaign under WSL."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from flydrones.camera_render_capacity import (  # noqa: E402
    CapacityRun,
    CapacityThresholds,
    capacity_schedule,
    classify_capacity_campaign,
    score_capacity_run,
)
from tools.run_camera_render_capacity_trial_wsl import (  # noqa: E402
    SubprocessCapacityBackend,
    run_capacity_trial,
)

DEFAULT_CONFIG = ROOT / "configs" / "five_camera_render_capacity.json"
DEFAULT_OUTPUT_ROOT = ROOT / "results" / "camera-render-capacity"
DEFAULT_NATIVE_EXECUTABLE = (
    ROOT / "build" / "native-camera-phase" / "flydrones_camera_phase_native"
)

_TRIAL_HASH_MAP = {
    "trial_runner": "runner",
    "launcher": "launcher",
    "runtime_probe": "runtime_probe",
    "stopper": "stopper",
    "camera_scheduler": "camera_scheduler",
    "python_observer": "python_observer",
    "camera_phase": "camera_phase",
    "capacity_contract": "capacity_contract",
    "process_ownership": "process_ownership",
    "native_executable": "native_executable",
}


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _config_contract_sha256(config: Mapping[str, object]) -> str:
    value = copy.deepcopy(dict(config))
    value["expected_hashes"] = {}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_capacity_frozen_hashes(
    config_path: Path, native_executable: Path
) -> dict[str, str]:
    config = _load_json(config_path)
    paths = {
        "profile": ROOT / str(config["profile"]),
        "policy": ROOT / str(config["policy"]),
        "capacity_contract": ROOT / "src/flydrones/camera_render_capacity.py",
        "process_ownership": ROOT / "src/flydrones/process_ownership.py",
        "camera_phase": ROOT / "src/flydrones/camera_phase.py",
        "trial_runner": ROOT / "tools/run_camera_render_capacity_trial_wsl.py",
        "campaign_runner": Path(__file__),
        "launcher": ROOT / "tools/launch_px4_depth_swarm_wsl.sh",
        "runtime_probe": ROOT / "tools/probe_gazebo_runtime_wsl.py",
        "stopper": ROOT / "tools/stop_px4_swarm_wsl.sh",
        "renderer_attestation": ROOT / "tools/attest_gazebo_renderer_wsl.py",
        "renderer_profile": ROOT / "src/flydrones/gazebo_renderer.py",
        "camera_model_configurator": ROOT / "tools/configure_gazebo_camera_phase.py",
        "camera_scheduler": ROOT / "tools/run_camera_phase_scheduler_wsl.py",
        "python_observer": ROOT / "tools/probe_camera_phase_wsl.py",
        "world_generator": ROOT / "tools/generate_px4_forest_world.py",
        "world_contract": ROOT / "src/flydrones/sitl_swarm.py",
        "native_build": ROOT / "tools/build_camera_phase_native_wsl.sh",
        "native_cmake": ROOT / "native/camera_phase/CMakeLists.txt",
        "native_executable": native_executable,
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"frozen capacity inputs are missing: {', '.join(missing)}")
    hashes = {name: _sha256(path) for name, path in paths.items()}
    hashes.update({
        "config_contract": _config_contract_sha256(config),
        "camera_model": _tree_sha256(ROOT / str(config["camera_model"])),
        "vehicle_model": _tree_sha256(ROOT / str(config["vehicle_model"])),
        "native_source": _tree_sha256(ROOT / "native/camera_phase"),
    })
    return hashes


def px4_revision() -> str:
    return subprocess.check_output(
        ["git", "-C", str(Path.home() / "PX4-Autopilot"), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _validate_config(config: Mapping[str, object]) -> None:
    if config.get("schema") != "flydrones-camera-render-capacity-config-v1":
        raise ValueError("capacity config schema mismatch")
    if config.get("renderer_profile") != "d3d12-nvidia":
        raise ValueError("capacity renderer profile must be d3d12-nvidia")
    if config.get("vehicle_count") != 5:
        raise ValueError("capacity config requires five vehicles")
    if config.get("world") != "flydrones_forest":
        raise ValueError("capacity world must be flydrones_forest")
    if config.get("camera_model") != "assets/gazebo/models/OakD-Lite-Fly":
        raise ValueError("capacity camera model path differs from frozen path")
    if config.get("vehicle_model") != "assets/gazebo/models/x500_depth_fly":
        raise ValueError("capacity vehicle model path differs from frozen path")
    if config.get("scored_duration_s") != 30.0 or config.get("wall_timeout_s") != 120.0:
        raise ValueError("capacity config requires frozen 30/120 second durations")
    CapacityThresholds.from_mapping(config.get("thresholds", {}))
    schedule = config.get("schedule")
    if schedule != [run.as_dict() for run in capacity_schedule()]:
        raise ValueError("configured capacity schedule differs from frozen schedule")
    versions = config.get("software_versions")
    if not isinstance(versions, Mapping) or set(versions) != {"gz_transport", "gz_msgs"}:
        raise ValueError("capacity software versions are incomplete")
    if not isinstance(config.get("expected_hashes"), Mapping):
        raise ValueError("capacity expected_hashes are missing")


def build_capacity_campaign_manifest(
    config: Mapping[str, object],
    *,
    campaign_id: str,
    frozen_hashes: Mapping[str, str],
) -> dict[str, object]:
    _validate_config(config)
    return {
        "schema": "flydrones-camera-render-capacity-campaign-v1",
        "campaign_id": campaign_id,
        "config_schema": config["schema"],
        "profile": config["profile"],
        "policy": config["policy"],
        "world": config["world"],
        "camera_model": config["camera_model"],
        "vehicle_model": config["vehicle_model"],
        "renderer_profile": config["renderer_profile"],
        "vehicle_count": config["vehicle_count"],
        "px4_revision": config["px4_revision"],
        "software_versions": copy.deepcopy(config["software_versions"]),
        "frozen_hashes": dict(frozen_hashes),
        "thresholds": copy.deepcopy(config["thresholds"]),
        "schedule": copy.deepcopy(config["schedule"]),
        "completed_slots": [],
        "scores": [],
    }


def _immutable_manifest_fields(manifest: Mapping[str, object]) -> dict[str, object]:
    mutable = {"completed_slots", "scores"}
    return {key: copy.deepcopy(value) for key, value in manifest.items() if key not in mutable}


def validate_existing_campaign(
    existing: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    if _immutable_manifest_fields(existing) != _immutable_manifest_fields(expected):
        raise RuntimeError("frozen campaign manifest mismatch; start a new campaign ID")
    completed = existing.get("completed_slots")
    scores = existing.get("scores")
    if not isinstance(completed, list) or not isinstance(scores, list):
        raise RuntimeError("existing campaign progress is malformed")
    expected_names = [run.name for run in capacity_schedule()]
    if completed != expected_names[: len(completed)]:
        raise RuntimeError("existing campaign completed slots are not a frozen prefix")
    if [score.get("name") for score in scores if isinstance(score, Mapping)] != completed:
        raise RuntimeError("existing campaign scores do not match completed slots")


def resources_free() -> bool:
    return not SubprocessCapacityBackend().occupied_resources()


def _trial_expected_hashes(frozen_hashes: Mapping[str, str]) -> dict[str, str]:
    return {
        trial_name: str(frozen_hashes[campaign_name])
        for campaign_name, trial_name in _TRIAL_HASH_MAP.items()
        if campaign_name in frozen_hashes
    }


def _validate_trial_identity(
    run: CapacityRun,
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    *,
    trial_hashes: Mapping[str, str],
) -> None:
    if (
        manifest.get("schema") != "flydrones-camera-render-capacity-manifest-v1"
        or summary.get("schema") != "flydrones-camera-render-capacity-summary-v1"
        or manifest.get("name") != run.name
        or manifest.get("cell") != run.cell.name
        or manifest.get("sequence") != run.sequence
        or manifest.get("repetition") != run.repetition
        or manifest.get("subscriber_count") != run.cell.subscriber_count
        or manifest.get("observer_implementation") != run.cell.implementation
    ):
        raise RuntimeError(f"existing trial does not match frozen slot: {run.name}")
    actual_hashes = manifest.get("frozen_hashes")
    if isinstance(actual_hashes, Mapping) and any(
        actual_hashes.get(name) != value for name, value in trial_hashes.items()
    ):
        raise RuntimeError(f"existing trial hashes do not match frozen slot: {run.name}")


def execute_capacity_campaign(
    *,
    config_path: Path,
    output_root: Path,
    campaign_id: str,
    native_executable: Path,
    _run_trial_fn: Callable[..., dict[str, object]] = run_capacity_trial,
    _resources_free_fn: Callable[[], bool] = resources_free,
    _frozen_hashes: Mapping[str, str] | None = None,
    _px4_revision: str | None = None,
) -> dict[str, object]:
    if (
        not campaign_id
        or not campaign_id.replace("-", "").replace("_", "").isalnum()
        or "/" in campaign_id
        or "\\" in campaign_id
    ):
        raise ValueError("campaign_id must contain only letters, numbers, hyphens, or underscores")
    config = _load_json(config_path)
    _validate_config(config)
    current_revision = _px4_revision or px4_revision()
    if config.get("px4_revision") != current_revision:
        raise RuntimeError("current PX4 revision does not match frozen config")
    frozen_hashes = dict(
        _frozen_hashes
        if _frozen_hashes is not None
        else calculate_capacity_frozen_hashes(config_path, native_executable)
    )
    expected_hashes = dict(config["expected_hashes"])
    if frozen_hashes != expected_hashes:
        raise RuntimeError("current inputs do not match capacity expected_hashes")
    expected = build_capacity_campaign_manifest(
        config, campaign_id=campaign_id, frozen_hashes=frozen_hashes
    )
    campaign_dir = output_root / campaign_id
    manifest_path = campaign_dir / "campaign-manifest.json"
    if manifest_path.is_file():
        campaign_manifest = _load_json(manifest_path)
        validate_existing_campaign(campaign_manifest, expected)
    else:
        if campaign_dir.exists() and any(campaign_dir.iterdir()):
            raise RuntimeError("campaign directory is nonempty but has no campaign manifest")
        campaign_manifest = copy.deepcopy(expected)
        _atomic_json(manifest_path, campaign_manifest)

    for completed_name in campaign_manifest["completed_slots"]:
        completed_dir = campaign_dir / completed_name
        if not (completed_dir / "manifest.json").is_file() or not (
            completed_dir / "summary.json"
        ).is_file():
            raise RuntimeError(
                f"completed slot evidence is missing and will not be rerun: {completed_name}"
            )

    thresholds = CapacityThresholds.from_mapping(config["thresholds"])
    trial_hashes = _trial_expected_hashes(frozen_hashes)
    trial_config = copy.deepcopy(config)
    trial_config["expected_hashes"] = trial_hashes
    collected: list[tuple[dict[str, object], dict[str, object]]] = []
    scores: list[dict[str, object]] = []
    for run in capacity_schedule():
        trial_dir = campaign_dir / run.name
        trial_manifest_path = trial_dir / "manifest.json"
        trial_summary_path = trial_dir / "summary.json"
        if trial_dir.exists():
            if not trial_manifest_path.is_file() or not trial_summary_path.is_file():
                raise RuntimeError(
                    f"existing trial is incomplete and will not be overwritten: {run.name}"
                )
            trial_manifest = _load_json(trial_manifest_path)
            trial_summary = _load_json(trial_summary_path)
        else:
            if not _resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources are still in use before {run.name}")
            result = _run_trial_fn(
                run=run,
                config=trial_config,
                output_root=campaign_dir,
                native_executable=native_executable,
            )
            if not trial_manifest_path.is_file() or not trial_summary_path.is_file():
                raise RuntimeError(f"trial did not preserve complete evidence: {run.name}")
            trial_manifest = _load_json(trial_manifest_path)
            trial_summary = _load_json(trial_summary_path)
            if not isinstance(result, Mapping):
                raise RuntimeError(f"trial returned malformed result: {run.name}")
            if not _resources_free_fn():
                raise RuntimeError(f"PX4/Gazebo resources were not released after {run.name}")
        _validate_trial_identity(
            run, trial_manifest, trial_summary, trial_hashes=trial_hashes
        )
        score = score_capacity_run(trial_manifest, trial_summary, thresholds)
        collected.append((trial_manifest, trial_summary))
        scores.append(score)
        completed = campaign_manifest["completed_slots"]
        if run.name not in completed:
            completed.append(run.name)
            campaign_manifest["scores"].append(score)
            _atomic_json(manifest_path, campaign_manifest)

    result = classify_capacity_campaign(collected, config)
    result["campaign_id"] = campaign_id
    result["completed_slots"] = list(campaign_manifest["completed_slots"])
    result["raw_trial_paths"] = [run.name for run in capacity_schedule()]
    _atomic_json(campaign_dir / "campaign-summary.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--native-executable", type=Path, default=DEFAULT_NATIVE_EXECUTABLE)
    parser.add_argument("--print-frozen-hashes", action="store_true")
    args = parser.parse_args(argv)
    if args.print_frozen_hashes:
        print(json.dumps(
            calculate_capacity_frozen_hashes(args.config, args.native_executable),
            indent=2,
            sort_keys=True,
        ))
        return 0
    if not args.campaign_id:
        parser.error("--campaign-id is required unless --print-frozen-hashes is used")
    result = execute_capacity_campaign(
        config_path=args.config,
        output_root=args.output_root,
        campaign_id=args.campaign_id,
        native_executable=args.native_executable,
    )
    return 0 if len(result.get("scores", [])) == 12 else 2


if __name__ == "__main__":
    raise SystemExit(main())
