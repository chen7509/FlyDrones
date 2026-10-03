#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Make one non-overwriting 29 s delayed VIO input from saved development data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.camera_info_capture import verify_camera_info_capture
from flydrones.benchmark.rgb_capture import verify_rgb_manifest
from flydrones.benchmark.ulog_capture import verify_episode_ulog_evidence

START_NS = 29_000_000_000
FROZEN_REFERENCE_SHA256 = (
    "e5154775d583dadb4e2805b4829178eef4e17f967e93ace08d852c3e362ace37",
    "4fe7bd9b62a5f021e0816d9fd22cfb4448562ec8483bd6b8602137c6ef42c380",
    "20200cd589e4bf9c6b88cc1c9b9ba0a8673466405d0509a8ef305226b1a88d30",
)
IMU_FIELDS = ("timestamp_us", "gx", "gy", "gz", "ax", "ay", "az")
FRAME_FIELDS = ("timestamp_ns", "relative_ppm_path")


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_source_hashes(manifest: dict, expected: dict[str, Path]) -> None:
    if any(manifest.get(key) != _sha(path) for key, path in expected.items()):
        raise ValueError("source manifest hash mismatch")


def verify_frozen_reference(
    source_manifest: Path, episode_result: Path, prior_archive: Path,
    *, expected: tuple[str, str, str] = FROZEN_REFERENCE_SHA256,
) -> None:
    actual = tuple(_sha(path) for path in (source_manifest, episode_result, prior_archive))
    if actual != expected:
        raise ValueError("frozen reference SHA-256 mismatch")


def trim_streams(imu_rows: list[dict], frame_rows: list[dict], start_ns: int,
                 *, min_imu: int = 100, min_frames: int = 20) -> tuple[list[dict], list[dict]]:
    """Keep byte-equivalent source values at/after a fixed clock boundary."""
    if type(start_ns) is not int or start_ns <= 0:
        raise ValueError("invalid trim start")
    imu_stamps = []
    for row in imu_rows:
        try:
            stamp = int(row["timestamp_us"])
            values = [float(row[key]) for key in IMU_FIELDS[1:]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("IMU row incomplete or not finite") from exc
        if any(not math.isfinite(v) for v in values):
            raise ValueError("IMU row not finite")
        imu_stamps.append(stamp)
    if not imu_stamps or imu_stamps[0] <= 0 or any(
            b <= a for a, b in zip(imu_stamps, imu_stamps[1:])):
        raise ValueError("IMU timestamps not strictly increasing")
    frame_stamps = []
    for row in frame_rows:
        try:
            stamp = int(row["timestamp_ns"])
            path = PurePosixPath(row["relative_ppm_path"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("image row incomplete") from exc
        if (path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "rgb-frames"
                or path.suffix != ".ppm" or path.stem != str(stamp)):
            raise ValueError("unsafe frame path")
        frame_stamps.append(stamp)
    if not frame_stamps or frame_stamps[0] <= 0 or any(
            b <= a for a, b in zip(frame_stamps, frame_stamps[1:])):
        raise ValueError("image timestamps not strictly increasing")
    kept_imu = [row for row, stamp in zip(imu_rows, imu_stamps, strict=True)
                if stamp * 1000 >= start_ns]
    if len(kept_imu) < min_imu:
        raise ValueError("trimmed streams too short")
    first_imu_ns = int(kept_imu[0]["timestamp_us"]) * 1000
    last_imu_ns = int(kept_imu[-1]["timestamp_us"]) * 1000
    if any(stamp >= start_ns and stamp > last_imu_ns for stamp in frame_stamps):
        raise ValueError("image lies after last IMU sample")
    kept_frames = [row for row, stamp in zip(frame_rows, frame_stamps, strict=True)
                   if stamp >= start_ns and stamp >= first_imu_ns]
    if len(kept_frames) < min_frames:
        raise ValueError("trimmed streams too short")
    return kept_imu, kept_frames


def _rows(path: Path, fields: tuple[str, ...]) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f"unexpected CSV columns: {path}")
        return list(reader)


def _write_rows(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-input", type=Path, required=True)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, episode, output = (path.resolve() for path in
                               (args.source_input, args.episode, args.output_dir))
    if output.exists():
        raise FileExistsError("refusing to overwrite delayed VIO input")
    verify_frozen_reference(source / "manifest.json", episode / "result.json",
                            ROOT / "evidence/openvins-stationary-prelude-dev-1701-reviewed.zip")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((episode / "result.json").read_text(encoding="utf-8"))
    verify_episode_ulog_evidence(episode, result)
    rgb = verify_rgb_manifest(episode)
    verify_camera_info_capture(episode)
    if len(result["px4_ulogs"]) != 1:
        raise ValueError("expected one PX4 ULog")
    expected = {"episode_result_sha256": episode / "result.json",
                "rgb_manifest_sha256": episode / "rgb-capture-manifest.json",
                "camera_info_sha256": episode / "camera-info.json",
                "px4_ulog_sha256": episode / result["px4_ulogs"][0]["path"],
                "imu_csv_sha256": source / "imu.csv",
                "frames_csv_sha256": source / "frames.csv"}
    verify_source_hashes(manifest, expected)
    imu = _rows(source / "imu.csv", IMU_FIELDS)
    frames = _rows(source / "frames.csv", FRAME_FIELDS)
    indexed = {(str(item["frame_ns"]), item["path"]) for item in rgb["frames"]}
    if (len(imu) != manifest.get("imu_count") or
            len(frames) != manifest.get("usable_frame_count") or
            any((row["timestamp_ns"], row["relative_ppm_path"]) not in indexed
                for row in frames)):
        raise ValueError("source stream differs from verified capture")
    kept_imu, kept_frames = trim_streams(imu, frames, START_NS)
    output.mkdir(parents=True)
    _write_rows(output / "imu.csv", IMU_FIELDS, kept_imu)
    _write_rows(output / "frames.csv", FRAME_FIELDS, kept_frames)
    summary = {
        "schema": "flydrones-openvins-delayed-feed-v1",
        "scope": "one offline development replay; not a PX4 VIO fusion result",
        "start_ns": START_NS,
        "source_manifest_sha256": _sha(source / "manifest.json"),
        "source_imu_sha256": _sha(source / "imu.csv"),
        "source_frames_sha256": _sha(source / "frames.csv"),
        "episode_result_sha256": _sha(episode / "result.json"),
        "trimmed_imu_sha256": _sha(output / "imu.csv"),
        "trimmed_frames_sha256": _sha(output / "frames.csv"),
        "source_imu_count": len(imu), "source_frame_count": len(frames),
        "trimmed_imu_count": len(kept_imu), "trimmed_frame_count": len(kept_frames),
        "first_imu_ns": int(kept_imu[0]["timestamp_us"]) * 1000,
        "last_imu_ns": int(kept_imu[-1]["timestamp_us"]) * 1000,
        "first_frame_ns": int(kept_frames[0]["timestamp_ns"]),
        "last_frame_ns": int(kept_frames[-1]["timestamp_ns"]),
    }
    (output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
