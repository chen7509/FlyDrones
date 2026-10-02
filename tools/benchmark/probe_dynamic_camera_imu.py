#!/usr/bin/env python3
"""Capture a separate zero-gravity Gazebo yaw fixture; never launches PX4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.gateway import sim_duration_ns  # noqa: E402


def _stamp_ns(message) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)


def yaw_rate(sim_s: float) -> float:
    """Asymmetric excitation makes image/IMU lag detectable in principle."""
    if sim_s < 0.3:
        return 0.0
    if sim_s < 1.2:
        return 0.7
    if sim_s < 2.1:
        return -0.7
    if sim_s < 2.7:
        return 0.5
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("refusing to overwrite dynamic probe evidence")

    import gz.math7  # noqa: F401 - registers math types in the sim bindings
    from gz.math7 import Vector3d
    from gz.msgs10.image_pb2 import Image
    from gz.msgs10.imu_pb2 import IMU
    from gz.sim8 import K_NULL_ENTITY, Link, Model, Sensor, TestFixture, World, world_entity
    from gz.transport13 import Node

    source = args.source_fixture.resolve()
    tree = ET.parse(source)
    gravity = tree.getroot().find("world/gravity")
    if gravity is None:
        raise ValueError("source world has no gravity field")
    gravity.text = "0 0 0"
    args.output_dir.mkdir(parents=True)
    world_path = args.output_dir / "world.sdf"
    tree.write(world_path, encoding="utf-8", xml_declaration=True)
    frame_dir = args.output_dir / "rgb-frames"
    frame_dir.mkdir()

    px4_models = Path.home() / "PX4-Autopilot/Tools/simulation/gz/models"
    os.environ["GZ_SIM_RESOURCE_PATH"] = ":".join((
        str(ROOT / "assets/gazebo/models"), str(px4_models),
        os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
    ))
    os.environ["GZ_PARTITION"] = f"fly_dynamic_probe_{os.getpid()}"

    node = Node()
    lock = threading.Lock()
    frames: list[dict] = []
    imu: list[dict] = []
    camera_pose: list[dict] = []
    topics: dict[str, str] = {}
    base_link: Link | None = None

    def on_image(message):
        stamp = _stamp_ns(message)
        width, height = int(message.width), int(message.height)
        payload = bytes(message.data)
        if len(payload) != width * height * 3:
            raise ValueError("unexpected RGB image size")
        ppm = f"P6\n{width} {height}\n255\n".encode("ascii") + payload
        path = frame_dir / f"{stamp}.ppm"
        with path.open("xb") as stream:
            stream.write(ppm)
        with lock:
            frames.append({"frame_ns": stamp, "path": str(path.relative_to(args.output_dir)).replace("\\", "/"),
                           "sha256": hashlib.sha256(ppm).hexdigest(), "width": width, "height": height})

    def on_imu(message):
        with lock:
            imu.append({
                "stamp_ns": _stamp_ns(message),
                "angular_velocity_xyz_rad_s": [message.angular_velocity.x,
                                               message.angular_velocity.y,
                                               message.angular_velocity.z],
            })

    node.subscribe(Image, "/benchmark/rgbd/image", on_image)

    def pre_update(info, ecm):
        nonlocal base_link
        if base_link is None:
            model_id = World(world_entity(ecm)).model_by_name(ecm, "x500_benchmark_8")
            if model_id == K_NULL_ENTITY:
                return
            link_id = Model(model_id).link_by_name(ecm, "base_link")
            if link_id == K_NULL_ENTITY:
                return
            base_link = Link(link_id)
        base_link.set_angular_velocity(ecm, Vector3d(0, 0, yaw_rate(sim_duration_ns(info.sim_time) / 1e9)))

    def post_update(info, ecm):
        model_id = World(world_entity(ecm)).model_by_name(ecm, "x500_benchmark_8")
        if model_id == K_NULL_ENTITY:
            return
        model = Model(model_id)
        camera_id = model.link_by_name(ecm, "camera_link")
        base_id = model.link_by_name(ecm, "base_link")
        if camera_id == K_NULL_ENTITY or base_id == K_NULL_ENTITY:
            return
        camera = Link(camera_id)
        pose = camera.world_pose(ecm)
        if pose is not None:
            rotation, position = pose.rot(), pose.pos()
            camera_pose.append({"sim_ns": sim_duration_ns(info.sim_time),
                                "position_xyz_m": [position.x(), position.y(), position.z()],
                                "quaternion_xyzw": [rotation.x(), rotation.y(), rotation.z(), rotation.w()]})
        if "imu" not in topics:
            sensor_id = Link(base_id).sensor_by_name(ecm, "imu_sensor")
            if sensor_id != K_NULL_ENTITY:
                topic = Sensor(sensor_id).topic(ecm)
                if topic:
                    node.subscribe(IMU, topic, on_imu)
                    topics["imu"] = topic

    fixture = TestFixture(str(world_path.resolve()))
    fixture.on_pre_update(pre_update)
    fixture.on_post_update(post_update)
    fixture.finalize()
    server = fixture.server()
    for _ in range(60):
        if not server.run(True, 50, False):
            raise RuntimeError("Gazebo stopped during dynamic probe")
        threading.Event().wait(.02)
    # Transport callbacks may still be delivering the final sensor tick after
    # the synchronous step loop has stopped. Freeze copies once, under lock.
    time.sleep(.5)
    with lock:
        captured_frames = sorted(frames, key=lambda item: item["frame_ns"])
        captured_imu = sorted(imu, key=lambda item: item["stamp_ns"])
    if len(captured_frames) < 20 or len(captured_imu) < 100 or not camera_pose:
        raise RuntimeError(f"insufficient dynamic capture: frames={len(captured_frames)} imu={len(captured_imu)}")
    if (len({item["frame_ns"] for item in captured_frames}) != len(captured_frames)
            or len({item["stamp_ns"] for item in captured_imu}) != len(captured_imu)):
        raise ValueError("duplicate sensor timestamps in dynamic capture")
    result = {
        "schema": "flydrones-gazebo-dynamic-camera-imu-v1",
        "source_fixture_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "world_sha256": hashlib.sha256(world_path.read_bytes()).hexdigest(),
        "gravity_xyz_m_s2": [0, 0, 0],
        "stimulus": "base_link z angular velocity 0/.7/-.7/.5/0 rad/s at .3/1.2/2.1/2.7 s",
        "topics": {"image": "/benchmark/rgbd/image", **topics},
        "frames": captured_frames,
        "imu": captured_imu,
        "camera_link_pose": camera_pose,
    }
    (args.output_dir / "capture.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frames": len(captured_frames), "imu": len(captured_imu),
                      "camera_pose": len(camera_pose), "topics": topics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
