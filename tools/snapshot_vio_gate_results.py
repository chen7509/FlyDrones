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
            "vio-relay.jsonl", "flydrones_forest.sdf",
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
    target = args.target or ROOT / "docs/results/vio-renderer-stability" / args.campaign_dir.name
    manifest = json.loads(
        (args.campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema") == "flydrones-px4-takeoff-stability-campaign-manifest-v1":
        snapshot_takeoff_campaign(args.campaign_dir, target)
    else:
        snapshot_renderer_campaign(args.campaign_dir, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
