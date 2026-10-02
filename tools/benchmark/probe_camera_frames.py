#!/usr/bin/env python3
"""Inspect runtime Gazebo link geometry without launching PX4 or a mission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.gateway import sim_duration_ns  # noqa: E402


def _pose(pose) -> dict:
    pos, rot = pose.pos(), pose.rot()
    return {
        "position_xyz_m": [pos.x(), pos.y(), pos.z()],
        "quaternion_xyzw": [rot.x(), rot.y(), rot.z(), rot.w()],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-output", type=Path,
                        help="save the first raw RGB frame from this separate fixture")
    parser.add_argument("--min-image-ns", type=int, default=0,
                        help="skip startup image frames before this simulation time")
    parser.add_argument("--vehicle-name", default="x500_benchmark_8")
    args = parser.parse_args()
    if args.output.exists() or (args.image_output and args.image_output.exists()):
        raise FileExistsError("refusing to overwrite frame-probe evidence")
    import gz.math7  # noqa: F401 - registers Pose3d with gz.sim8's Python bindings
    from gz.sim8 import K_NULL_ENTITY, Link, Model, Sensor, TestFixture, World, world_entity

    px4_models = Path.home() / "PX4-Autopilot/Tools/simulation/gz/models"
    os.environ["GZ_SIM_RESOURCE_PATH"] = ":".join((
        str(ROOT / "assets/gazebo/models"), str(px4_models),
        os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
    ))
    os.environ["GZ_PARTITION"] = f"fly_frame_probe_{os.getpid()}"
    world_path = args.world.resolve()
    record: dict = {}
    link_samples: list[tuple[int, dict]] = []
    first_image: dict = {}
    image_received = threading.Event()
    if args.image_output:
        from gz.msgs10.image_pb2 import Image
        from gz.transport13 import Node

        node = Node()

        def on_image(message):
            if first_image:
                return
            frame_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
            if frame_ns < args.min_image_ns:
                return
            first_image.update({
                "frame_ns": frame_ns,
                "width": int(message.width),
                "height": int(message.height),
                "rgb_bytes": bytes(message.data),
            })
            image_received.set()

        node.subscribe(Image, "/benchmark/rgbd/image", on_image)

    def post_update(info, ecm):
        if record and not args.image_output:
            return
        world = World(world_entity(ecm))
        model_id = world.model_by_name(ecm, args.vehicle_name)
        if model_id == K_NULL_ENTITY:
            raise RuntimeError(f"model {args.vehicle_name} not found")
        model = Model(model_id)
        base_id = model.link_by_name(ecm, "base_link")
        camera_id = model.link_by_name(ecm, "camera_link")
        if base_id == K_NULL_ENTITY or camera_id == K_NULL_ENTITY:
            raise RuntimeError("base_link or camera_link not found")
        base, camera = Link(base_id), Link(camera_id)
        base_pose, camera_pose = base.world_pose(ecm), camera.world_pose(ecm)
        if base_pose is None or camera_pose is None:
            raise RuntimeError("link world pose missing")
        sim_ns = sim_duration_ns(info.sim_time)
        if args.image_output:
            link_samples.append((sim_ns, _pose(camera_pose)))
        if record:
            return
        sensor_id = camera.sensor_by_name(ecm, "rgbd")
        if sensor_id == K_NULL_ENTITY:
            raise RuntimeError("rgbd sensor not found")
        sensor = Sensor(sensor_id)
        record.update({
            "schema": "flydrones-gazebo-link-frame-probe-v1",
            "sim_ns": sim_ns,
            "vehicle_name": args.vehicle_name,
            "base_link_world": _pose(base_pose),
            "camera_link_world": _pose(camera_pose),
            "camera_link_in_base_link": _pose(base_pose.inverse() * camera_pose),
            "rgbd_sensor_pose_in_camera_link": _pose(sensor.pose(ecm)),
            "rgbd_sensor_topic": sensor.topic(ecm),
            "world_sha256": hashlib.sha256(world_path.read_bytes()).hexdigest(),
            "camera_model_sdf_sha256": hashlib.sha256(
                (ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf").read_bytes()).hexdigest(),
            "vehicle_model_sdf_sha256": hashlib.sha256(
                (ROOT / "assets/gazebo/models/x500_benchmark/model.sdf").read_bytes()).hexdigest(),
            "px4_base_sdf_sha256": hashlib.sha256(
                (px4_models / "x500_base/model.sdf").read_bytes()).hexdigest(),
        })

    fixture = TestFixture(str(world_path))
    fixture.on_post_update(post_update)
    fixture.finalize()
    server = fixture.server()
    if not server.run(True, 1, False) or not record:
        raise RuntimeError("Gazebo frame probe did not produce a sample")
    if args.image_output:
        for _ in range(30):
            if not server.run(True, 10, False):
                raise RuntimeError("Gazebo stopped during optical image probe")
            if image_received.wait(.1):
                break
        if not first_image:
            raise RuntimeError("optical image probe received no RGB frame")
        expected = first_image["width"] * first_image["height"] * 3
        if len(first_image["rgb_bytes"]) != expected:
            raise ValueError("optical image size mismatch")
        payload = (f"P6\n{first_image['width']} {first_image['height']}\n255\n".encode("ascii")
                   + first_image["rgb_bytes"])
        args.image_output.parent.mkdir(parents=True, exist_ok=True)
        with args.image_output.open("xb") as stream:
            stream.write(payload)
        record["first_image"] = {
            "frame_ns": first_image["frame_ns"],
            "width": first_image["width"],
            "height": first_image["height"],
            "ppm_sha256": hashlib.sha256(payload).hexdigest(),
        }
        pose_ns, pose = min(link_samples, key=lambda item: abs(item[0] - first_image["frame_ns"]))
        record["camera_link_world_at_image"] = {"sim_ns": pose_ns, **pose}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
