#!/usr/bin/env python3
"""Bind raw readiness artifacts into current manifests without mutating a campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from flydrones.px4_sensor_readiness import (  # noqa: E402
    ReadinessThresholds,
    classify_readiness_campaign,
    readiness_schedule,
    score_readiness_run,
)

EVIDENCE_FIELDS = {
    "px4_build_evidence": "px4-build-evidence.json",
    "sensor_source_evidence": "px4-sensor-source-warmup.json",
    "sensor_topology_evidence": "px4-sensor-topic-connections.json",
    "cleanup_evidence": "cleanup-evidence.json",
    "restoration_evidence": "restoration-evidence.json",
}


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def reclassify_campaign(
    source: Path, output: Path, config_path: Path
) -> dict[str, object]:
    source_resolved = source.resolve()
    output_resolved = output.resolve()
    if output_resolved == source_resolved or output_resolved.is_relative_to(
        source_resolved
    ):
        raise ValueError("amendment output must be outside source campaign")
    if output.exists():
        raise FileExistsError(f"amendment output already exists: {output}")
    config = _load_json(config_path)
    thresholds = ReadinessThresholds.from_mapping(config.get("thresholds", {}))
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    provenance: list[dict[str, object]] = []
    for run in readiness_schedule("formal"):
        source_trial = source / run.name
        manifest_path = source_trial / "manifest.json"
        summary_path = source_trial / "summary.json"
        manifest = copy.deepcopy(_load_json(manifest_path))
        summary = _load_json(summary_path)
        hashes = {
            "manifest.json": _sha256(manifest_path),
            "summary.json": _sha256(summary_path),
        }
        for field, name in EVIDENCE_FIELDS.items():
            path = source_trial / name
            if not path.is_file():
                manifest.setdefault("errors", []).append(f"missing amendment artifact: {name}")
                manifest[field] = {}
            else:
                manifest[field] = _load_json(path)
                hashes[name] = _sha256(path)
        score = score_readiness_run(manifest, summary, thresholds)
        target = output / run.name
        _atomic_json(target / "manifest.json", manifest)
        _atomic_json(target / "summary.json", summary)
        _atomic_json(target / "score.json", score)
        pairs.append((manifest, summary))
        provenance.append({"name": run.name, "source_hashes": hashes})
    result = classify_readiness_campaign(pairs, config, phase="formal")
    amendment = {
        "schema": "flydrones-px4-sensor-readiness-amendment-v1",
        "source_campaign": str(source),
        "source_campaign_summary_sha256": _sha256(source / "campaign-summary.json"),
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "scorer_sha256": _sha256(ROOT / "src/flydrones/px4_sensor_readiness.py"),
        "source_artifacts_unchanged": True,
        "provenance": provenance,
        "classification": result,
    }
    _atomic_json(output / "amendment.json", amendment)
    _atomic_json(output / "campaign-summary.json", result)
    return amendment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    amendment = reclassify_campaign(args.source, args.output, args.config)
    print(json.dumps(amendment["classification"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
