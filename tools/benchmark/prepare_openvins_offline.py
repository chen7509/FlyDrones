#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Export verified development RGB/PX4 ULog streams for offline VIO research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.rgb_capture import verify_rgb_manifest
from flydrones.benchmark.ulog_capture import verify_episode_ulog_evidence


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("refusing to overwrite offline VIO input")
    from pyulog import ULog

    episode = args.episode.resolve()
    result_path = episode / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    verify_episode_ulog_evidence(episode, result)
    rgb = verify_rgb_manifest(episode)
    if len(result["px4_ulogs"]) != 1:
        raise ValueError("offline input requires exactly one PX4 ULog")
    if result.get("camera_info_capture_accepted") is not True:
        raise ValueError("offline input requires captured camera intrinsics")
    camera_info_path = episode / "camera-info.json"
    camera_info = json.loads(camera_info_path.read_text(encoding="utf-8"))
    if (camera_info["camera_info"]["width"] != 160
            or camera_info["camera_info"]["height"] != 120
            or camera_info["changed_stable_fields"] != 0):
        raise ValueError("camera intrinsics or dimensions changed")
    log = episode / result["px4_ulogs"][0]["path"]
    imu = ULog(str(log)).get_dataset("sensor_combined").data
    stamp_us = np.asarray(imu["timestamp"], dtype=np.int64)
    if len(stamp_us) < 100 or np.any(stamp_us <= 0) or np.any(np.diff(stamp_us) <= 0):
        raise ValueError("IMU timestamps missing or not strictly increasing")
    axes = []
    for kind in ("gyro_rad", "accelerometer_m_s2"):
        for index in range(3):
            axis = np.asarray(imu[f"{kind}[{index}]"], dtype=float)
            if len(axis) != len(stamp_us) or not np.all(np.isfinite(axis)):
                raise ValueError("non-finite or incomplete IMU vectors")
            axes.append(axis)
    relative = np.asarray(imu["accelerometer_timestamp_relative"], dtype=np.int64)
    if len(relative) != len(stamp_us) or np.any(relative != 0):
        raise ValueError("nonzero accelerometer/gyro timestamp offset needs explicit handling")
    first_ns, last_ns = int(stamp_us[0] * 1_000), int(stamp_us[-1] * 1_000)
    usable = [item for item in rgb["frames"] if first_ns <= item["frame_ns"] <= last_ns]
    excluded = [item["frame_ns"] for item in rgb["frames"] if item not in usable]
    if len(usable) < 20 or len(usable) + len(excluded) != len(rgb["frames"]):
        raise ValueError("insufficient or inconsistent image/IMU overlap")
    args.output_dir.mkdir(parents=True)
    imu_csv = args.output_dir / "imu.csv"
    with imu_csv.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp_us", "gx", "gy", "gz", "ax", "ay", "az"))
        writer.writerows((int(stamp_us[i]), *(float(axis[i]) for axis in axes))
                         for i in range(len(stamp_us)))
    frame_csv = args.output_dir / "frames.csv"
    with frame_csv.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp_ns", "relative_ppm_path"))
        writer.writerows((item["frame_ns"], item["path"]) for item in usable)
    manifest = {
        "schema": "flydrones-openvins-offline-input-v1",
        "episode_result_sha256": _digest(result_path),
        "rgb_manifest_sha256": _digest(episode / "rgb-capture-manifest.json"),
        "camera_info_sha256": _digest(camera_info_path),
        "px4_ulog_sha256": _digest(log),
        "imu_csv_sha256": _digest(imu_csv),
        "frames_csv_sha256": _digest(frame_csv),
        "imu_count": len(stamp_us),
        "raw_frame_count": len(rgb["frames"]),
        "usable_frame_count": len(usable),
        "excluded_frame_ns": excluded,
        "first_imu_ns": first_ns,
        "last_imu_ns": last_ns,
        "first_usable_frame_ns": usable[0]["frame_ns"],
        "last_usable_frame_ns": usable[-1]["frame_ns"],
        "imu_frame": "PX4 sensor_combined FRD, not Gazebo FLU",
        "camera_frame": "Gazebo RGB optical frame checked by static target probe",
        "timeshift_cam_imu_s": None,
        "pyulog_version": version("pyulog"),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items()
                      if key != "excluded_frame_ns"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
