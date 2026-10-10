#!/usr/bin/env python3
"""Replay a retained causal source stream without starting an estimator or simulator."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.benchmark.openvins_online_shadow import ShadowInput  # noqa: E402


def _digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class _RecordingSink:
    def __init__(self, causal_to_source):
        self.causal_to_source = causal_to_source
        self.actions = []

    def send(self, action, pixels=None):
        record = copy.deepcopy(action)
        if record["kind"] == "imu":
            record["source_sequence"] = self.causal_to_source[record["source_sequence"]]
        else:
            record["rgb_source_sequence"] = self.causal_to_source[record.pop("rgb_sequence")]
            record["info_source_sequence"] = self.causal_to_source[record.pop("info_sequence")]
            record["imu_boundary_source_sequence"] = self.causal_to_source[record.pop("imu_boundary_sequence")]
            record["rgb_sha256"] = hashlib.sha256(pixels).hexdigest()
        self.actions.append(record)
        return {"recorded_action": len(self.actions) - 1}


def _payload(source, row):
    if row["kind"] == "rgb":
        data = (source / f"rgb-frames/{row['sample_ns']}.ppm").read_bytes()
        prefix = b"P6\n160 120\n255\n"
        if not data.startswith(prefix) or len(data) != len(prefix) + 57_600:
            raise ValueError("invalid retained RGB frame")
        return data[len(prefix) :]
    if row["kind"] == "info":
        relative = Path(row["payload_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("camera info payload escaped source")
        data = (source / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["payload_sha256"]:
            raise ValueError("camera info payload hash changed")
        return data
    return None


def replay(source, output):
    source, output = Path(source).resolve(), Path(output)
    if output.exists():
        raise FileExistsError(output)
    if json.loads((source / "result.json").read_text())["status"] != "capture_failed":
        raise ValueError("source is not the retained failed capture")
    raw_events = (source / "events.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw_events.splitlines() if line]
    if [row.get("source_sequence") for row in rows] != list(range(len(rows))):
        raise ValueError("source sequence changed")

    output.mkdir(parents=True)
    causal_to_source = {}
    sink = _RecordingSink(causal_to_source)
    clock = max(row["arrival_monotonic_ns"] for row in rows) + 1
    shadow = ShadowInput(sink, output, session_id="study-v9-fixed-replay", now=lambda: clock)
    identities = []
    for row in rows:
        payload = _payload(source, row)
        if row["kind"] in {"imu", "rgb", "info"}:
            causal_to_source[shadow.sequence] = row["source_sequence"]
        shadow.on_record(row, payload)
        identities.append(
            {
                "source_sequence": row["source_sequence"],
                "kind": row["kind"],
                "sample_ns": row.get("sample_ns"),
                "source_sha256": _digest_json(row),
                "payload_sha256": hashlib.sha256(payload).hexdigest() if payload is not None else None,
            }
        )
    shadow_result = shadow.finish()
    info = next(row for row in rows if row["kind"] == "info")
    rgb = next(row for row in rows if row["kind"] == "rgb" and row["sample_ns"] == info["sample_ns"])
    result = {
        "schema": "causal-pair-stage-fixed-replay-v1",
        "source": source.as_posix(),
        "source_events_sha256": hashlib.sha256(raw_events).hexdigest(),
        "source_row_count": len(rows),
        "source_rows": identities,
        "same_stamp_pair_gap_ns": rgb["arrival_monotonic_ns"] - info["arrival_monotonic_ns"],
        "wall_wait_ns": 250_000_000,
        "actions": sink.actions,
        "shadow_failure": shadow_result["failure"],
        "shadow_pending": shadow_result["pending"],
        "physical_execution_qualified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.source, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
