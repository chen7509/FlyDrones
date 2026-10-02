#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Verify a separate Gazebo optical-axis fixture from raw image and source hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.camera_info_capture import verify_camera_info_capture
from flydrones.benchmark.optical_fixture import analyze_markers


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--camera-info-episode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    frames = json.loads(args.frames.read_text(encoding="utf-8"))
    info = verify_camera_info_capture(args.camera_info_episode)
    if _sha(args.world) != fixture["fixture_world_sha256"] or frames["world_sha256"] != fixture["fixture_world_sha256"]:
        raise ValueError("optical fixture world hash mismatch")
    if frames["camera_model_sdf_sha256"] != _sha(ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf"):
        raise ValueError("camera model SDF changed since frame probe")
    if frames["vehicle_model_sdf_sha256"] != _sha(ROOT / "assets/gazebo/models/x500_benchmark/model.sdf"):
        raise ValueError("vehicle model SDF changed since frame probe")
    if _sha(args.image) != frames["first_image"]["ppm_sha256"]:
        raise ValueError("optical fixture image hash mismatch")
    if frames["camera_link_world_at_image"]["sim_ns"] != frames["first_image"]["frame_ns"]:
        raise ValueError("camera link pose does not match image timestamp")
    sensor_pose = frames["rgbd_sensor_pose_in_camera_link"]
    if (any(abs(value) > 1e-6 for value in sensor_pose["position_xyz_m"])
            or not np.allclose(sensor_pose["quaternion_xyzw"], [0, 0, 0, 1], atol=1e-6)):
        raise ValueError("RGBD sensor is not aligned with camera_link")
    width, height = frames["first_image"]["width"], frames["first_image"]["height"]
    if (width, height) != (info["camera_info"]["width"], info["camera_info"]["height"]):
        raise ValueError("camera info and fixture image dimensions disagree")
    payload = args.image.read_bytes()
    prefix = f"P6\n{width} {height}\n255\n".encode("ascii")
    if not payload.startswith(prefix) or len(payload) != len(prefix) + width * height * 3:
        raise ValueError("invalid raw optical fixture PPM")
    if any(abs(value) > 1e-12 for value in info["camera_info"]["distortion_k"]):
        raise ValueError("optical fixture projection requires zero distortion")
    image = np.frombuffer(payload[len(prefix):], dtype=np.uint8).reshape(height, width, 3)
    result = analyze_markers(image, fixture["targets"], frames["camera_link_world_at_image"],
                             info["camera_info"]["intrinsics_k"])
    result.update({
        "fixture_world_sha256": fixture["fixture_world_sha256"],
        "fixture_manifest_sha256": _sha(args.fixture),
        "frame_probe_sha256": _sha(args.frames),
        "rgb_ppm_sha256": _sha(args.image),
        "camera_info_protobuf_sha256": info["first_message_sha256"],
        "image_sim_ns": frames["first_image"]["frame_ns"],
        "camera_link_in_base_link": frames["camera_link_in_base_link"],
        "imu_frame_note": "Gazebo base_link is FLU; PX4 GZBridge rotates IMU FLU to FRD; not an OpenVINS result",
        "vio_estimate_produced": False,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
