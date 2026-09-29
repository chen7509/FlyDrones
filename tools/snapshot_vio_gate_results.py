"""Version compact VIO gate evidence and checksums for preserved raw trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/vio-stress"
TARGET = ROOT / "docs/results/vio-safety-gate"
TRIALS = (
    "single-vio-gate-frozen-baseline",
    "single-vio-gate-frozen-delay-120ms",
    "single-vio-gate-frozen-dropout-400ms",
    "fleet-vio-gate-frozen-baseline",
    "fleet-vio-gate-frozen-baseline-v2",
    "fleet-vio-gate-frozen-dropout-400ms",
    "fleet-vio-gate-baseline-pause-probe-1",
    "fleet-vio-gate-baseline-pause-probe-2",
    "fleet-vio-gate-depth-quarter-pixels-probe",
    "fleet-vio-gate-process-probe-1",
    "fleet-vio-gate-thread-probe-1",
    "fleet-vio-gate-perf-probe-1",
    "fleet-vio-gate-perf-mono-probe-1",
)
COMPACT = ("trial-manifest.json", "stress-summary.json", "fault-profile.json")
RAW = ("vio-relay.jsonl", "trajectory-replay.html", "flydrones_forest.sdf",
       "runtime-probe.csv", "clock-probe.csv", "process-probe.csv", "thread-probe.csv",
       "diagnostic-depth-model.sdf", "gazebo-perf.data", "gazebo-perf-report.txt",
       "gazebo-perf-flat.txt", "perf-window-analysis.txt", "analyze_perf_mono.py",
       "perf-mono-waiter.sh", "renderer-eglinfo.txt")
RENDERER_COMPACT = (
    "trial-manifest.json",
    "stress-summary.json",
    "renderer-attestation.json",
    "cleanup-evidence.json",
)
TAKEOFF_COMPACT = (
    *RENDERER_COMPACT,
    "summary.json",
    "takeoff-readiness-summary.json",
)
CAMERA_PHASE_COMPACT = (
    *RENDERER_COMPACT,
    "camera-model-evidence.json",
    "camera-phase-summary.json",
)
CAPACITY_REQUIRED_COMPACT = (
    "trial-config.json",
    "manifest.json",
    "summary.json",
    "cleanup-evidence.json",
    "restoration-evidence.json",
    "px4-build-evidence.json",
    "camera-model-evidence.json",
)
MAX_COMPACT_SEQUENCE = 8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compact_json(value: object) -> object:
    if isinstance(value, dict):
        return {key: _compact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) <= MAX_COMPACT_SEQUENCE:
            return [_compact_json(item) for item in value]
        edge = MAX_COMPACT_SEQUENCE // 2
        return {
            "_compact_sequence": True,
            "length": len(value),
            "sha256": _json_sha256(value),
            "head": [_compact_json(item) for item in value[:edge]],
            "tail": [_compact_json(item) for item in value[-edge:]],
        }
    return value


def _copy_compact(path: Path, target: Path) -> None:
    if path.name != "stress-summary.json":
        shutil.copy2(path, target)
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    target.write_text(
        json.dumps(_compact_json(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _snapshot_campaign(
    source: Path,
    target: Path,
    *,
    compact_files: tuple[str, ...],
    index_schema: str,
) -> dict:
    manifest = json.loads((source / "campaign-manifest.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in manifest["schedule"]]
    target.mkdir(parents=True, exist_ok=True)
    for name in ("campaign-manifest.json", "campaign-summary.json"):
        path = source / name
        if path.is_file():
            shutil.copy2(path, target / name)
    trials = {}
    for name in names:
        trial_source = source / name
        trial_target = target / name
        trial_target.mkdir(parents=True, exist_ok=True)
        for filename in compact_files:
            path = trial_source / filename
            if path.is_file():
                _copy_compact(path, trial_target / filename)
        raw_paths = set(trial_source.rglob("*.csv"))
        raw_paths.update(trial_source.rglob("*.ulg"))
        raw_paths.update(trial_source.rglob("*.html"))
        raw_paths.update(trial_source.rglob("*.log"))
        raw_paths.update(path for path in trial_source.rglob("*") if path.name in {
            "vio-relay.jsonl", "camera-scheduler.jsonl", "camera-phase.jsonl",
            "flydrones_forest.sdf", "camera-model-configured.sdf",
        })
        raw_paths.update(
            trial_source / filename for filename in compact_files
            if (trial_source / filename).is_file()
        )
        trials[name] = {
            path.relative_to(trial_source).as_posix(): {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(raw_paths) if path.is_file()
        }
    index = {
        "schema": index_schema,
        "campaign_id": manifest.get("campaign_id"),
        "trials": trials,
    }
    (target / "raw-artifact-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return index


def snapshot_renderer_campaign(source: Path, target: Path) -> dict:
    return _snapshot_campaign(
        source,
        target,
        compact_files=RENDERER_COMPACT,
        index_schema="flydrones-renderer-stability-artifacts-v1",
    )


def snapshot_takeoff_campaign(source: Path, target: Path) -> dict:
    return _snapshot_campaign(
        source,
        target,
        compact_files=TAKEOFF_COMPACT,
        index_schema="flydrones-px4-takeoff-stability-artifacts-v1",
    )


def snapshot_camera_phase_campaign(source: Path, target: Path) -> dict:
    return _snapshot_campaign(
        source,
        target,
        compact_files=CAMERA_PHASE_COMPACT,
        index_schema="flydrones-camera-phase-stability-artifacts-v1",
    )


def _capacity_slot_names(source: Path) -> list[str]:
    manifest = json.loads(
        (source / "campaign-manifest.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (source / "campaign-summary.json").read_text(encoding="utf-8")
    )
    schedule = manifest.get("schedule")
    if not isinstance(schedule, list) or len(schedule) != 12:
        raise ValueError("capacity snapshot requires exactly twelve scheduled slots")
    names = [item.get("name") for item in schedule if isinstance(item, dict)]
    if len(names) != 12 or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("capacity slot identities are missing or invalid")
    if len(set(names)) != 12:
        raise ValueError("capacity slot identities must be unique")
    if summary.get("completed_slots") != names or summary.get("raw_trial_paths") != names:
        raise ValueError("capacity summary slot identities differ from the frozen schedule")
    actual_dirs = {path.name for path in source.iterdir() if path.is_dir()}
    if actual_dirs != set(names):
        raise ValueError("capacity source slot identities contain missing or extra directories")
    return names


def _capacity_compact_paths(trial: Path) -> set[Path]:
    required = {trial / name for name in CAPACITY_REQUIRED_COMPACT}
    missing = sorted(path.name for path in required if not path.is_file())
    if missing:
        raise ValueError(f"capacity compact evidence is missing: {missing}")
    manifest = json.loads((trial / "manifest.json").read_text(encoding="utf-8"))
    renderer = trial / "renderer-attestation.json"
    if manifest.get("evidence_accepted") is True and not renderer.is_file():
        raise ValueError("accepted capacity slot lacks renderer attestation")
    return {path for path in trial.glob("*.json") if path.is_file()}


def _capacity_raw_index(source: Path, names: list[str]) -> dict[str, dict[str, dict[str, object]]]:
    trials: dict[str, dict[str, dict[str, object]]] = {}
    for name in names:
        trial = source / name
        compact = _capacity_compact_paths(trial)
        raw = [path for path in trial.rglob("*") if path.is_file() and path not in compact]
        trials[name] = {
            path.relative_to(trial).as_posix(): {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(raw)
        }
    return trials


def verify_camera_render_capacity_snapshot(source: Path, target: Path) -> None:
    names = _capacity_slot_names(source)
    index_path = target / "raw-artifact-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema") != "flydrones-camera-render-capacity-artifacts-v1":
        raise ValueError("capacity raw artifact index schema is invalid")
    if list(index.get("trials", {})) != names:
        raise ValueError("capacity snapshot slot identities differ from the frozen schedule")
    target_dirs = {path.name for path in target.iterdir() if path.is_dir()}
    if target_dirs != set(names):
        raise ValueError("capacity target slot identities contain missing or extra directories")
    if {path.name for path in target.iterdir() if path.is_file()} != {
        "campaign-manifest.json", "campaign-summary.json", "raw-artifact-index.json"
    }:
        raise ValueError("capacity snapshot root contains missing or extra files")
    for filename in ("campaign-manifest.json", "campaign-summary.json"):
        if sha256(source / filename) != sha256(target / filename):
            raise ValueError(f"capacity compact copy differs from source: {filename}")
    expected_raw = _capacity_raw_index(source, names)
    if index.get("trials") != expected_raw:
        raise ValueError("capacity raw artifact index differs from source evidence")
    for name in names:
        trial_source = source / name
        trial_target = target / name
        compact = _capacity_compact_paths(trial_source)
        target_files = {path.name for path in trial_target.iterdir() if path.is_file()}
        if target_files != {path.name for path in compact}:
            raise ValueError(f"capacity compact files differ for {name}")
        if any(path.is_dir() for path in trial_target.iterdir()):
            raise ValueError(f"capacity compact target contains raw directories for {name}")
        for path in compact:
            if sha256(path) != sha256(trial_target / path.name):
                raise ValueError(f"capacity compact copy differs from source: {name}/{path.name}")


def snapshot_camera_render_capacity_campaign(source: Path, target: Path) -> dict:
    names = _capacity_slot_names(source)
    if target.exists() and any(target.iterdir()):
        raise ValueError("capacity snapshot target must be empty")
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("campaign-manifest.json", "campaign-summary.json"):
        shutil.copy2(source / filename, target / filename)
    for name in names:
        trial_source = source / name
        trial_target = target / name
        trial_target.mkdir()
        for path in sorted(_capacity_compact_paths(trial_source)):
            shutil.copy2(path, trial_target / path.name)
    manifest = json.loads(
        (source / "campaign-manifest.json").read_text(encoding="utf-8")
    )
    index = {
        "schema": "flydrones-camera-render-capacity-artifacts-v1",
        "campaign_id": manifest.get("campaign_id"),
        "trials": _capacity_raw_index(source, names),
    }
    (target / "raw-artifact-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify_camera_render_capacity_snapshot(source, target)
    return index


def snapshot_legacy_vio_gate() -> None:
    index = {}
    for name in TRIALS:
        source = SOURCE / name
        target = TARGET / name
        target.mkdir(parents=True, exist_ok=True)
        for filename in COMPACT:
            shutil.copy2(source / filename, target / filename)
        paths = [source / filename for filename in (*COMPACT, *RAW)]
        paths.extend(source.glob("agent-*.csv"))
        paths.extend(source.glob("agent-*.json"))
        paths.extend(source.glob("px4-ulogs/*.ulg"))
        index[name] = {
            path.relative_to(source).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(set(paths)) if path.is_file()
        }
    (TARGET / "raw-artifact-index.json").write_text(
        json.dumps({"schema": "flydrones-vio-safety-gate-artifacts-v1", "trials": index}, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    if args.campaign_dir is None:
        snapshot_legacy_vio_gate()
        return 0
    target = args.target
    manifest = json.loads(
        (args.campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema") == "flydrones-camera-render-capacity-campaign-v1":
        target = target or ROOT / "docs/results/camera-render-capacity" / args.campaign_dir.name
        snapshot_camera_render_capacity_campaign(args.campaign_dir, target)
    elif manifest.get("schema") == "flydrones-px4-takeoff-stability-campaign-manifest-v1":
        target = target or ROOT / "docs/results/vio-renderer-stability" / args.campaign_dir.name
        snapshot_takeoff_campaign(args.campaign_dir, target)
    elif manifest.get("schema") == "flydrones-camera-phase-stability-campaign-manifest-v1":
        target = target or ROOT / "docs/results/vio-renderer-stability" / args.campaign_dir.name
        snapshot_camera_phase_campaign(args.campaign_dir, target)
    else:
        target = target or ROOT / "docs/results/vio-renderer-stability" / args.campaign_dir.name
        snapshot_renderer_campaign(args.campaign_dir, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
