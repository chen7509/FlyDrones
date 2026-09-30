"""Publish compact trial summaries and checksums without copying large ULogs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/vio-stress"
TARGET = ROOT / "docs/results/vio-stress"
POLICY = ROOT / "results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / "all-trials.json", TARGET / "all-trials.json")
    shutil.copy2(POLICY, TARGET / "policy-checkpoint.npz")
    selected = ("trial-manifest.json", "fault-profile.json", "flydrones_forest.sdf",
                "vio-relay.jsonl", "stress-summary.json")
    index = {}
    for trial in sorted(SOURCE.iterdir()):
        if not (trial / "trial-manifest.json").exists():
            continue
        paths = [trial / name for name in selected]
        paths.extend(trial.glob("agent-*.csv"))
        paths.extend(trial.glob("agent-*.json"))
        paths.extend(trial.glob("px4-ulogs/*.ulg"))
        index[trial.name] = {
            path.relative_to(SOURCE).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(set(paths)) if path.is_file()
        }
    (TARGET / "raw-artifact-index.json").write_text(
        json.dumps({"schema": "flydrones-vio-artifact-index-v1", "trials": index}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
