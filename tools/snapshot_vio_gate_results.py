"""Version compact VIO gate evidence and checksums for preserved raw trials."""

from __future__ import annotations

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
)
COMPACT = ("trial-manifest.json", "stress-summary.json", "fault-profile.json")
RAW = ("vio-relay.jsonl", "trajectory-replay.html", "flydrones_forest.sdf",
       "runtime-probe.csv", "clock-probe.csv", "process-probe.csv",
       "diagnostic-depth-model.sdf")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
