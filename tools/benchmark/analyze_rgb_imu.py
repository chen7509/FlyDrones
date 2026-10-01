#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Audit raw simulated RGB frames against PX4 ULog IMU timestamps."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.rgb_capture import verify_rgb_manifest
from flydrones.benchmark.rgb_imu_timing import analyze_timing
from flydrones.benchmark.ulog_capture import verify_episode_ulog_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from pyulog import ULog

    episode = args.episode.resolve()
    result = json.loads((episode / "result.json").read_text(encoding="utf-8"))
    if result.get("rgb_capture_requested") is not True or result.get("rgb_capture_accepted") is not True:
        raise ValueError("episode lacks accepted opt-in RGB capture")
    verify_episode_ulog_evidence(episode, result)
    rgb = verify_rgb_manifest(episode)
    if len(result["px4_ulogs"]) != 1:
        raise ValueError("preflight requires one unambiguous PX4 ULog")
    record = result["px4_ulogs"][0]
    ulog = ULog(str(episode / record["path"]))
    imu = ulog.get_dataset("sensor_combined").data
    for axis in range(3):
        if f"gyro_rad[{axis}]" not in imu or f"accelerometer_m_s2[{axis}]" not in imu:
            raise ValueError("PX4 ULog lacks complete gyro/accelerometer data")
    timing = analyze_timing([item["frame_ns"] for item in rgb["frames"]],
                            imu["timestamp"].tolist())
    timing.update({
        "rgb_manifest_sha256": hashlib.sha256((episode / "rgb-capture-manifest.json").read_bytes()).hexdigest(),
        "ulog_sha256": record["sha256"],
        "task_status": result["status"],
        "odometry_source": result["odometry_source"],
        "camera_pose_source": result["camera_pose_source"],
        "rgb_out_of_order_drops": rgb["out_of_order_drops"],
        "pyulog_version": version("pyulog"),
        "vio_estimate_produced": False,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(timing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(timing, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
