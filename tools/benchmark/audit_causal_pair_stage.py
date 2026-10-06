#!/usr/bin/env python3
"""Independently audit one fixed causal pair-stage replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _payload_matches(source, row):
    payload_path = row.get("payload_path")
    payload_sha256 = row.get("payload_sha256")
    if not isinstance(payload_path, str) or not isinstance(payload_sha256, str):
        return False
    candidate = (source / payload_path).resolve()
    try:
        candidate.relative_to(source)
    except ValueError:
        return False
    return candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == payload_sha256


def audit(source, replay):
    source, replay = Path(source).resolve(), Path(replay).resolve()
    failures = []

    def require(condition, label):
        if not condition:
            failures.append(label)

    raw_events = (source / "events.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw_events.splitlines() if line]
    result = json.loads((replay / "result.json").read_text())
    shadow = json.loads((replay / "shadow-input-result.json").read_text())
    expected_kinds = ["imu", "info", "depth", "rgb", "imu", "imu"]
    expected_samples = [1_000_000, 2_000_000, 2_000_000, 2_000_000, 4_000_000, 8_000_000]
    require([row.get("source_sequence") for row in rows] == list(range(6)), "source sequence")
    require([row.get("kind") for row in rows] == expected_kinds, "source kinds")
    require([row.get("sample_ns") for row in rows] == expected_samples, "source samples")
    require(result.get("source_events_sha256") == hashlib.sha256(raw_events).hexdigest(), "source events hash")
    require(result.get("source_row_count") == 6, "source row count")
    identities = result.get("source_rows", [])
    require(len(identities) == 6, "source identities count")
    if len(identities) == 6:
        require(
            all(item.get("source_sha256") == _digest_json(row) for item, row in zip(identities, rows)),
            "source identities",
        )
    info, rgb = rows[1], rows[3]
    require(_payload_matches(source, info), "camera info payload")
    if len(identities) == 6:
        require(identities[1].get("payload_sha256") == info.get("payload_sha256"), "camera info replay identity")
    gap = rgb["arrival_monotonic_ns"] - info["arrival_monotonic_ns"]
    require(gap == 258_765_752, "fixed pair gap")
    require(result.get("same_stamp_pair_gap_ns") == gap, "reported pair gap")
    require(result.get("wall_wait_ns") == 250_000_000, "wall wait limit")

    ppm = (source / "rgb-frames/2000000.ppm").read_bytes()
    prefix = b"P6\n160 120\n255\n"
    require(ppm.startswith(prefix) and len(ppm) == len(prefix) + 57_600, "source RGB frame")
    rgb_hash = hashlib.sha256(ppm[len(prefix) :]).hexdigest() if ppm.startswith(prefix) else None
    actions = result.get("actions", [])
    require([action.get("kind") for action in actions] == ["imu", "imu", "camera", "imu"], "action order")
    if len(actions) == 4:
        require(
            [actions[0].get("sample_ns"), actions[1].get("sample_ns"), actions[3].get("sample_ns")]
            == [1_000_000, 4_000_000, 8_000_000],
            "IMU action samples",
        )
        camera = actions[2]
        require(camera.get("sample_ns") == 2_000_000, "camera sample")
        require(camera.get("rgb_source_sequence") == 3, "camera RGB source")
        require(camera.get("info_source_sequence") == 1, "camera info source")
        require(camera.get("imu_boundary_ns") == 4_000_000, "camera IMU boundary")
        require(camera.get("imu_boundary_source_sequence") == 4, "camera IMU source")
        require(camera.get("rgb_sha256") == rgb_hash, "camera RGB hash")
    require(result.get("shadow_failure") is None and shadow.get("failure") is None, "shadow failure")
    require(result.get("shadow_pending") == [] and shadow.get("pending") == [], "shadow pending")
    require(shadow.get("delivered") == 4, "shadow delivered count")
    require(
        all(
            result.get(key) is False
            for key in [
                "physical_execution_qualified",
                "runtime_closure_qualified",
                "vio_accuracy_qualified",
                "estimator_health_qualified",
                "fusion_eligible",
                "flight_ready",
            ]
        ),
        "downstream claims false",
    )
    require(
        not any(
            (replay / name).exists()
            for name in ["process.json", "physics-substeps.jsonl", "px4-ulog-manifest.json", "runtime-owner-openvins.json"]
        ),
        "no physical artifacts",
    )
    return {
        "schema": "causal-pair-stage-fixed-replay-audit-v1",
        "checks": {
            "exact_source_order": not any(label.startswith("source ") for label in failures),
            "exact_pair_gap": "fixed pair gap" not in failures and "reported pair gap" not in failures,
            "unchanged_limit": "wall wait limit" not in failures,
            "exact_actions": not any(label.startswith(("action", "IMU action", "camera ")) for label in failures),
            "closed_downstream": "downstream claims false" not in failures,
            "no_physical_artifacts": "no physical artifacts" not in failures,
        },
        "failures": failures,
        "fixed_replay_qualified": not failures,
        "physical_execution_qualified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.source, args.replay)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
