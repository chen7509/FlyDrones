#!/usr/bin/env python3
"""Authorize, then invoke the frozen camera-capacity campaign runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from flydrones.camera_rerun_gate import validate_camera_rerun_gate  # noqa: E402

DEFAULT_CAMERA_CONFIG = ROOT / "configs" / "five_camera_render_capacity.json"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_hash(path: Path, expected: str) -> str:
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError(f"invalid frozen SHA-256 for {path}")
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"frozen SHA-256 mismatch for {path}")
    return actual


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def validate_readiness_build_binding(
    *,
    summary_path: Path,
    summary: Mapping[str, object],
    readiness_config: Mapping[str, object],
    camera_config: Mapping[str, object],
    summary_sha256: str,
    readiness_config_sha256: str,
) -> dict[str, object]:
    gate_inputs = camera_config.get("readiness_gate_inputs")
    identity = camera_config.get("px4_build_identity")
    if not isinstance(gate_inputs, Mapping) or not isinstance(identity, Mapping):
        raise ValueError("camera config does not freeze readiness gate inputs and PX4 identity")
    if gate_inputs.get("summary_sha256") != summary_sha256:
        raise ValueError("camera config readiness summary hash mismatch")
    if gate_inputs.get("config_sha256") != readiness_config_sha256:
        raise ValueError("camera config readiness config hash mismatch")
    if not (
        identity.get("px4_revision") == readiness_config.get("px4_revision")
        and identity.get("px4_patch_sha256") == readiness_config.get("px4_patch_sha256")
        and identity.get("vehicle_imu_sha256")
        == readiness_config.get("px4_vehicle_imu_sha256")
    ):
        raise ValueError("camera PX4 identity differs from the readiness config")
    expected_evidence = {key: value for key, value in identity.items() if key != "px4_patch"}
    manifest_hashes: dict[str, str] = {}
    scores = summary.get("scores")
    if not isinstance(scores, list) or len(scores) != 10:
        raise ValueError("readiness build binding requires ten scored runs")
    for score in scores:
        if not isinstance(score, Mapping) or not isinstance(score.get("name"), str):
            raise ValueError("readiness score identity is invalid")
        manifest_path = summary_path.parent / str(score["name"]) / "manifest.json"
        manifest = _load_json(manifest_path)
        if manifest.get("px4_build_evidence") != expected_evidence:
            raise ValueError(f"readiness PX4 build identity mismatch: {score['name']}")
        manifest_hashes[str(score["name"])] = _sha256(manifest_path)
    return {
        "px4_build_identity": dict(identity),
        "readiness_manifest_sha256": manifest_hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness-summary", type=Path, required=True)
    parser.add_argument("--readiness-summary-sha256", required=True)
    parser.add_argument("--readiness-config", type=Path, required=True)
    parser.add_argument("--readiness-config-sha256", required=True)
    parser.add_argument("--gate-evidence", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CAMERA_CONFIG)
    args, legacy_args = parser.parse_known_args()
    summary_hash = _require_hash(
        args.readiness_summary, args.readiness_summary_sha256
    )
    config_hash = _require_hash(args.readiness_config, args.readiness_config_sha256)
    summary = _load_json(args.readiness_summary)
    config = _load_json(args.readiness_config)
    camera_config = _load_json(args.config)
    gate = validate_camera_rerun_gate(summary, config)
    gate.update(
        validate_readiness_build_binding(
            summary_path=args.readiness_summary,
            summary=summary,
            readiness_config=config,
            camera_config=camera_config,
            summary_sha256=summary_hash,
            readiness_config_sha256=config_hash,
        )
    )
    gate.update({
        "readiness_summary": str(args.readiness_summary),
        "readiness_summary_sha256": summary_hash,
        "readiness_config": str(args.readiness_config),
        "readiness_config_sha256": config_hash,
    })
    _atomic_json(args.gate_evidence, gate)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_camera_render_capacity_campaign_wsl.py"),
            "--config",
            str(args.config),
            *legacy_args,
        ],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
