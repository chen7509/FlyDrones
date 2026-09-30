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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness-summary", type=Path, required=True)
    parser.add_argument("--readiness-summary-sha256", required=True)
    parser.add_argument("--readiness-config", type=Path, required=True)
    parser.add_argument("--readiness-config-sha256", required=True)
    parser.add_argument("--gate-evidence", type=Path, required=True)
    args, legacy_args = parser.parse_known_args()
    summary_hash = _require_hash(
        args.readiness_summary, args.readiness_summary_sha256
    )
    config_hash = _require_hash(args.readiness_config, args.readiness_config_sha256)
    summary = _load_json(args.readiness_summary)
    config = _load_json(args.readiness_config)
    gate = validate_camera_rerun_gate(summary, config)
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
            *legacy_args,
        ],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
