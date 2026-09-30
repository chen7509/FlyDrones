#!/usr/bin/env python3
"""Verify that native camera facts receive identical Python phase scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from flydrones.camera_phase import (  # noqa: E402
    CameraPhaseThresholds,
    CameraScheduleMode,
    camera_phase_offsets_ns,
    canonical_phase_score_fields,
    summarize_camera_phase,
)

DEFAULT_VECTOR_FIXTURE = ROOT / "tests" / "fixtures" / "camera_phase_vectors.json"
DEFAULT_NATIVE_JSONL_NAME = "camera-phase-native-parity.jsonl"
WORLD = "flydrones_forest"
PERIOD_NS = 100_000_000


class ParityError(RuntimeError):
    pass


def depth_topic(vehicle_id: int, *, world: str = WORLD) -> str:
    return (
        f"/world/{world}/model/x500_depth_fly_{vehicle_id}"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
    )


def _load_vector_identity(path: Path) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(f"shared vector fixture cannot be read: {exc}") from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "flydrones-camera-phase-vectors-v1"
        or payload.get("vehicle_count") != 5
        or not isinstance(payload.get("epoch_ns"), int)
        or isinstance(payload.get("epoch_ns"), bool)
        or payload.get("dispatch_delay_ns") != 4_000_000
    ):
        raise ParityError("shared vector fixture identity mismatch")
    return int(payload["epoch_ns"]), int(payload["vehicle_count"])


def build_reference_events(vector_fixture: Path) -> list[dict[str, object]]:
    epoch_ns, vehicle_count = _load_vector_identity(vector_fixture)
    events: list[dict[str, object]] = [
        {"event": "start", "epoch_ns": epoch_ns},
        {
            "event": "topology",
            "depth_topics": [depth_topic(vehicle_id) for vehicle_id in range(vehicle_count)],
        },
        {"event": "ready", "epoch_ns": epoch_ns},
    ]
    for cycle in range(11):
        for vehicle_id, offset_ns in enumerate(camera_phase_offsets_ns(vehicle_count)):
            planned_ns = epoch_ns + cycle * PERIOD_NS + offset_ns
            events.extend(
                (
                    {
                        "event": "trigger",
                        "vehicle_id": vehicle_id,
                        "cycle": cycle,
                        "topic": f"{depth_topic(vehicle_id)}/trigger",
                        "planned_sim_ns": planned_ns,
                        "published_sim_ns": planned_ns + 4_000_000,
                    },
                    {
                        "event": "image",
                        "vehicle_id": vehicle_id,
                        "topic": depth_topic(vehicle_id),
                        "sim_ns": planned_ns,
                        "sequence": cycle,
                        "width": 160,
                        "height": 120,
                        "format": "R_FLOAT32",
                    },
                )
            )
    events.append({"event": "stop"})
    return events


def _read_native_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ParityError(f"native JSONL cannot be read: {exc}") from exc
    events: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParityError(f"malformed JSONL at line {line_number}: {exc.msg}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("event"), str):
            raise ParityError(f"malformed JSONL record at line {line_number}")
        events.append(value)
    return events


def _verify_native_identity(
    events: Sequence[Mapping[str, object]], native_executable: Path
) -> None:
    identities = [event for event in events if event.get("event") == "native-build"]
    if len(identities) != 1:
        raise ParityError("native build identity must appear exactly once")
    try:
        actual_hash = hashlib.sha256(native_executable.read_bytes()).hexdigest()
    except OSError as exc:
        raise ParityError(f"native executable cannot be read: {exc}") from exc
    if identities[0].get("executable_sha256") != actual_hash:
        raise ParityError("native executable hash mismatch")


def verify_native_parity(
    *,
    native_executable: Path,
    native_jsonl: Path,
    vector_fixture: Path = DEFAULT_VECTOR_FIXTURE,
) -> dict[str, object]:
    native_events = _read_native_jsonl(native_jsonl)
    _verify_native_identity(native_events, native_executable)
    reference_events = build_reference_events(vector_fixture)
    thresholds = CameraPhaseThresholds()
    native_summary = summarize_camera_phase(
        native_events,
        mode=CameraScheduleMode.PHASED,
        vehicle_count=5,
        thresholds=thresholds,
    )
    reference_summary = summarize_camera_phase(
        reference_events,
        mode=CameraScheduleMode.PHASED,
        vehicle_count=5,
        thresholds=thresholds,
    )
    native_canonical = canonical_phase_score_fields(native_summary)
    reference_canonical = canonical_phase_score_fields(reference_summary)
    if native_canonical != reference_canonical:
        differing = [
            key
            for key in reference_canonical
            if native_canonical.get(key) != reference_canonical.get(key)
        ]
        raise ParityError(f"canonical mismatch: {', '.join(differing)}")
    return {
        "schema": "flydrones-camera-phase-native-parity-v1",
        "matched": True,
        "native_executable_sha256": hashlib.sha256(native_executable.read_bytes()).hexdigest(),
        "native_jsonl": str(native_jsonl),
        "vector_fixture": str(vector_fixture),
        "canonical": reference_canonical,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-executable", type=Path, required=True)
    parser.add_argument("--native-jsonl", type=Path)
    parser.add_argument("--vector-fixture", type=Path, default=DEFAULT_VECTOR_FIXTURE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    native_jsonl = args.native_jsonl or (
        args.native_executable.parent / DEFAULT_NATIVE_JSONL_NAME
    )
    try:
        result = verify_native_parity(
            native_executable=args.native_executable,
            native_jsonl=native_jsonl,
            vector_fixture=args.vector_fixture,
        )
    except ParityError as exc:
        print(f"camera phase native parity failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
