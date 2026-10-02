#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Audit controlled Gazebo yaw images against raw IMU and runtime pose."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.dynamic_camera_imu import fit_image_imu_lag
from flydrones.benchmark.optical_fixture import _marker_mask


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--camera-info", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite dynamic analysis")
    capture_path = args.capture_dir / "capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    targets = json.loads(args.target_manifest.read_text(encoding="utf-8"))
    info = json.loads(args.camera_info.read_text(encoding="utf-8"))
    if _sha(args.capture_dir / "world.sdf") != capture["world_sha256"]:
        raise ValueError("dynamic world hash changed")
    if capture["schema"] != "flydrones-gazebo-dynamic-camera-imu-v1":
        raise ValueError("unexpected dynamic capture schema")
    target = next(x for x in targets["targets"] if x["name"] == "center_green")
    fx, cx = (info["camera_info"]["intrinsics_k"][index] for index in (0, 2))
    pose_at = {item["sim_ns"]: item for item in capture["camera_link_pose"]}
    used = []
    rejected = []
    for frame in capture["frames"]:
        stamp = frame["frame_ns"]
        path = args.capture_dir / frame["path"]
        if _sha(path) != frame["sha256"]:
            raise ValueError(f"frame hash changed: {path}")
        rgb = np.asarray(Image.open(path).convert("RGB"))
        rows, cols = np.nonzero(_marker_mask(rgb, target["rgb"]))
        if len(cols) < 10 or not len(rows) or min(cols) < 2 or max(cols) >= frame["width"] - 2:
            rejected.append({"frame_ns": stamp, "reason": "green target absent or clipped"})
            continue
        pose = pose_at.get(stamp)
        if pose is None:
            rejected.append({"frame_ns": stamp, "reason": "no exact-step camera pose"})
            continue
        quat = pose["quaternion_xyzw"]
        if abs(quat[0]) > .001 or abs(quat[1]) > .001:
            raise ValueError("yaw-only image angle formula invalid for camera roll/pitch")
        u = float(np.mean(cols))
        position = pose["position_xyz_m"]
        target_world = target["world_xyz_m"]
        bearing_world = np.arctan2(target_world[1] - position[1],
                                   target_world[0] - position[0])
        yaw_image = bearing_world + np.arctan((u - cx) / fx)
        yaw_pose = np.arctan2(2 * (quat[3]*quat[2] + quat[0]*quat[1]),
                              1 - 2 * (quat[1]**2 + quat[2]**2))
        used.append({"frame_ns": stamp, "green_center_u_px": u,
                     "image_yaw_rad": float(yaw_image), "pose_yaw_rad": float(yaw_pose),
                     "image_pose_yaw_residual_rad": float(yaw_image - yaw_pose)})
    imu_ns = np.array([sample["stamp_ns"] for sample in capture["imu"]], dtype=np.int64)
    if np.any(np.diff(imu_ns) <= 0):
        raise ValueError("raw IMU stamps are not strictly increasing")
    frame_ns = np.array([sample["frame_ns"] for sample in used], dtype=np.int64)
    if len(frame_ns) < 10 or np.any(np.diff(frame_ns) <= 0):
        raise ValueError("insufficient unambiguous green-target track")
    nearest = np.searchsorted(imu_ns, frame_ns)
    left = imu_ns[np.maximum(nearest - 1, 0)]
    right = imu_ns[np.minimum(nearest, len(imu_ns) - 1)]
    nearest_ms = np.minimum(np.abs(frame_ns - left), np.abs(frame_ns - right)) / 1e6
    image_yaw = np.unwrap([item["image_yaw_rad"] for item in used])
    gyro_z = np.array([item["angular_velocity_xyz_rad_s"][2] for item in capture["imu"]])
    fit = fit_image_imu_lag(frame_ns / 1e9, image_yaw, imu_ns / 1e9, gyro_z)
    pose_residual = np.array([item["image_pose_yaw_residual_rad"] for item in used])
    result = {
        "schema": "flydrones-controlled-dynamic-camera-imu-analysis-v1",
        "capture_sha256": _sha(capture_path),
        "target_manifest_sha256": _sha(args.target_manifest),
        "camera_info_sha256": _sha(args.camera_info),
        "raw_frame_count": len(capture["frames"]),
        "tracked_frame_count": len(used),
        "rejected_frames": rejected,
        "raw_imu_count": len(capture["imu"]),
        "tracked_frames_outside_imu_range": int(np.count_nonzero(
            (frame_ns < imu_ns[0]) | (frame_ns > imu_ns[-1]))),
        "nearest_imu_ms_max": float(np.max(nearest_ms)),
        "image_pose_yaw_residual_deg_rmse": float(np.rad2deg(np.sqrt(np.mean(pose_residual**2)))),
        "image_pose_yaw_residual_deg_max": float(np.rad2deg(np.max(np.abs(pose_residual)))),
        "lag_fit": fit,
        "tracked_frames": used,
        "qualification": "Gazebo-only controlled fixture; not PX4 timing or VIO calibration",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("tracked_frames", "lag_fit", "rejected_frames")}, indent=2))
    print(json.dumps({key: value for key, value in fit.items() if key != "lag_scan"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
