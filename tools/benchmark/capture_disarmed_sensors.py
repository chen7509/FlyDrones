#!/usr/bin/env python3
"""One sensor-only Gazebo/PX4 development capture. Never arms or publishes controls/VIO."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from flydrones.benchmark.camera_info_capture import camera_info_fields  # noqa: E402
from flydrones.benchmark.gateway import sim_duration_ns  # noqa: E402
from flydrones.benchmark.ulog_capture import collect_ulogs  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal, CaptureWriter, supervise_worker  # noqa: E402


def active_resources():
    matches = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit() or int(path.name) in {os.getpid(), os.getppid()}:
            continue
        try:
            name = (path / "comm").read_text().strip()
            argv = (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if name in {"px4", "gz", "gzserver", "gzclient", "state_probe", "fast_probe", "online_probe"} or (
            name.startswith("python")
            and any(s in argv for s in ["pytest", "run_episode.py", "train_", "capture_disarmed_sensors.py"])
        ):
            matches.append({"pid": int(path.name), "name": name, "command": argv})
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--shadow-binary", type=Path)
    parser.add_argument("--shadow-config", type=Path)
    args = parser.parse_args()
    if bool(args.shadow_binary) != bool(args.shadow_config):
        parser.error("shadow binary and frozen config must be specified together")
    shadow_args = (
        ["--shadow-binary", str(args.shadow_binary.resolve()), "--shadow-config", str(args.shadow_config.resolve())]
        if args.shadow_binary
        else []
    )
    if not args.worker:
        summary = supervise_worker(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(args.output.resolve())] + shadow_args,
            args.output.resolve(),
        )
        if summary["status"] == "supervisor_timeout" and (args.output / "launch.json").is_file():
            launch = json.loads((args.output / "launch.json").read_text())
            try:
                retained = {"px4_ulogs": collect_ulogs(Path(launch["runtime"]), args.output)}
            except Exception as exc:
                retained = {"errors": [repr(exc)], "runtime_retained": launch["runtime"]}
            with (args.output / "watchdog-retained-ulogs.json").open("x") as stream:
                json.dump(retained, stream, indent=2)
        return (
            0
            if summary["status"] == "worker_exited"
            and summary["worker_exit"] == 0
            and summary["capture_status"] == "capture_completed"
            else 2
        )
    resources = active_resources()
    if resources:
        raise RuntimeError("existing competing resources: " + json.dumps(resources))
    px4 = Path.home() / "PX4-Autopilot"
    build = px4 / "build/px4_sitl_default"
    binary = build / "bin/px4"
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    if binary_sha != "e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb":
        raise ValueError("PX4 binary differs from pinned development evidence")
    archive = ROOT / "evidence/openvins-board-pattern-dev-1701-reviewed.zip"
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive_sha != "669f3646e74c4e95826f12e79b456aba861a5b4003087541ce7dc1dc8cd1f4f3":
        raise ValueError("development scene seal changed")
    # Reserve the intended local receiver before simulation; no remote endpoint is used.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 14548))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    input_hashes = {}
    with zipfile.ZipFile(archive) as z:
        for name in ["world.sdf", "world.json", "ground_albedo.png", "obstacle_albedo.png", "board_albedo.png"]:
            data = z.read("results/openvins-board-pattern-dev-1701/episode-v2/" + name)
            with (output / name).open("xb") as f:
                f.write(data)
            input_hashes[name] = hashlib.sha256(data).hexdigest()
    partition = "fly_disarmed_" + str(os.getpid())
    os.environ["GZ_PARTITION"] = partition
    os.environ["GZ_SIM_RESOURCE_PATH"] = ":".join(
        [str(ROOT / "assets/gazebo/models"), str(px4 / "Tools/simulation/gz/models"), os.environ.get("GZ_SIM_RESOURCE_PATH", "")]
    )
    runtime = Path(tempfile.mkdtemp(prefix="fly-disarmed-", dir=str(Path.home() / "fly-ego-benchmark/runtime")))
    (runtime / "gz_env.sh").write_bytes((build / "rootfs/gz_env.sh").read_bytes())
    env = os.environ.copy()
    env.update(
        HEADLESS="1",
        PX4_GZ_STANDALONE="1",
        PX4_SYS_AUTOSTART="4001",
        PX4_GZ_WORLD="fly_ego_benchmark",
        PX4_SIM_MODEL="gz_x500_benchmark",
        PX4_GZ_MODEL_NAME="x500_benchmark_8",
        PX4_UXRCE_DDS_PORT="18888",
    )
    with (output / "launch.json").open("x") as f:
        json.dump(
            {
                "partition": partition,
                "runtime": str(runtime),
                "instance": 8,
                "binary_sha256": binary_sha,
                "source_archive_sha256": archive_sha,
                "scene_hashes": input_hashes,
                "simulation_duration_ns": 25_000_000_000,
                "physics_step_ns": 1_000_000,
                "imu_hz": 250,
                "rgbd_hz": 10,
                "command_policy": "read-only heartbeat; no arm/offboard/setpoint/ODOMETRY",
                "uxrce_port": 18888,
                "uxrce_agent_launched": False,
            },
            f,
            indent=2,
        )

    errors = []
    result = {
        "status": "incomplete",
        "errors": errors,
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "estimator_run": bool(args.shadow_binary),
        "capture_schema": "disarmed-sensors-v2",
    }
    clock = {"sim_ns": 0}
    started = time.monotonic()
    with CaptureJournal(output, result) as journal:
        journal.cleanup("ULog collection", lambda: result.update(px4_ulogs=collect_ulogs(runtime, output)), priority=100)
        journal.cleanup(
            "end clocks",
            lambda: result.update(end_sim_ns=clock["sim_ns"], capture_wall_s=time.monotonic() - started),
            priority=110,
        )
        import gz.math7  # noqa: F401 - register math types for sim bindings
        from gz.msgs10.camera_info_pb2 import CameraInfo
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.imu_pb2 import IMU
        from gz.sim8 import TestFixture
        from gz.transport13 import Node
        from pymavlink import mavutil

        shadow = None
        source_guard = None
        if args.shadow_binary:
            from tools.benchmark.openvins_online_shadow import NativeClient, ShadowInput, SourceWatchdog

            frozen = json.loads((args.shadow_config.parent / "freeze.json").read_text())
            for name, digest in frozen["sha256"].items():
                if hashlib.sha256((args.shadow_config.parent / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("frozen shadow configuration changed")
            shadow_dir = output / "shadow"
            shadow_dir.mkdir()
            client = NativeClient(
                [
                    str(args.shadow_binary.resolve()),
                    str(args.shadow_config.resolve()),
                    str(shadow_dir / "states.jsonl"),
                    str(shadow_dir / "fast.jsonl"),
                ],
                shadow_dir,
            )

            def finish_native():
                result["native"] = client.finish()
                if result["native"]["failure"] or result["native"]["exit"] != 0:
                    errors.append("native consumer failed: " + str(result["native"]))

            journal.cleanup("native consumer", finish_native, priority=95)
            shadow = ShadowInput(client, shadow_dir, session_id="online-native-" + str(client.process.pid))

            def finish_shadow():
                result["shadow"] = shadow.finish()
                if result["shadow"]["failure"]:
                    errors.append("shadow input failed: " + result["shadow"]["failure"])

            journal.cleanup("shadow input", finish_shadow, priority=90)
            # Cold renderer setup is a separate bounded phase; operational silence remains2s.
            source_guard = SourceWatchdog(startup_timeout_ns=10_000_000_000)
            journal.cleanup("source health", lambda: result.update(source_health=source_guard.snapshot()), priority=85)
        writer = CaptureWriter(output, on_record=shadow.on_record if shadow else None)
        journal.cleanup("writer", lambda: result.update(writer=writer.finish()), priority=80)
        stop = threading.Event()
        node = Node()
        receiver = mavutil.mavlink_connection("udpin:127.0.0.1:14548", source_system=254)
        journal.cleanup("receiver", receiver.close, priority=50)

        def submit(kind, message):
            arrival = time.monotonic_ns()
            try:
                if source_guard:
                    source_guard.observe(kind, arrival)
                event = {"kind": kind, "arrival_monotonic_ns": arrival, "observed_sim_ns": clock["sim_ns"]}
                payload = None
                if kind == "info":
                    event["sample_ns"] = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
                    event["camera_info"] = camera_info_fields(message)
                    payload = message.SerializeToString()
                else:
                    event["sample_ns"] = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
                    if kind == "imu":
                        event["gyro_flu"] = [message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z]
                        event["accel_flu"] = [
                            message.linear_acceleration.x,
                            message.linear_acceleration.y,
                            message.linear_acceleration.z,
                        ]
                    else:
                        event.update(width=int(message.width), height=int(message.height))
                        if kind == "rgb":
                            payload = bytes(message.data)
                writer.submit(event, payload)
            except Exception as exc:
                errors.append(repr(exc))

        def read_heartbeats():
            while not stop.is_set():
                try:
                    heartbeat = receiver.recv_match(type="HEARTBEAT", blocking=True, timeout=0.1)
                    if heartbeat is not None and heartbeat.get_srcSystem() == 9 and heartbeat.autopilot == 12:
                        writer.submit(
                            {
                                "kind": "heartbeat",
                                "arrival_monotonic_ns": time.monotonic_ns(),
                                "observed_sim_ns": clock["sim_ns"],
                                "system_id": 9,
                                "base_mode": int(heartbeat.base_mode),
                                "custom_mode": int(heartbeat.custom_mode),
                            }
                        )
                except Exception as exc:
                    errors.append(repr(exc))
                    return

        topics = [
            (Image, "/benchmark/rgbd/image", "rgb"),
            (Image, "/benchmark/rgbd/depth_image", "depth"),
            (CameraInfo, "/benchmark/rgbd/camera_info", "info"),
            (IMU, "/world/fly_ego_benchmark/model/x500_benchmark_8/link/base_link/sensor/imu_sensor/imu", "imu"),
        ]
        callbacks = []
        for cls, topic, kind in topics:

            def callback(msg, kind=kind):
                submit(kind, msg)

            callbacks.append(callback)
            if not node.subscribe(cls, topic, callback):
                raise RuntimeError("subscription failed: " + topic)
            journal.cleanup("unsubscribe " + topic, lambda topic=topic: node.unsubscribe(topic), priority=60)
        fixture = TestFixture(str(output / "world.sdf"))

        def post_update(info, _ecm):
            clock["sim_ns"] = sim_duration_ns(info.sim_time)

        fixture.on_post_update(post_update)
        fixture.finalize()
        server = fixture.server()
        if source_guard:
            watchdog_stop = threading.Event()

            def watch_sources():
                while not watchdog_stop.wait(0.05):
                    try:
                        source_guard.check(time.monotonic_ns())
                    except Exception as exc:
                        result["source_watchdog_failure"] = dict(
                            source_guard.snapshot(), checked_ns=time.monotonic_ns(), reason=repr(exc)
                        )
                        errors.append("source watchdog: " + repr(exc))
                        return

            watchdog_thread = threading.Thread(target=watch_sources, daemon=True)
            watchdog_thread.start()
            journal.cleanup("source watchdog", lambda: (watchdog_stop.set(), watchdog_thread.join(timeout=1)), priority=10)
        heartbeat_thread = threading.Thread(target=read_heartbeats, daemon=True)
        heartbeat_thread.start()
        journal.cleanup("heartbeat", lambda: (stop.set(), heartbeat_thread.join(timeout=3)), priority=40)
        log = (output / "px4.log").open("x")
        journal.cleanup("log close", log.close, priority=70)
        process = subprocess.Popen(
            [str(binary), "-i", "8", "-d", str(build / "etc")],
            cwd=runtime,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )

        def stop_px4():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    errors.append("owned PX4 required SIGKILL")
            result["px4_exit_code"] = process.returncode

        journal.cleanup("owned PX4", stop_px4, priority=20)
        with (output / "process.json").open("x") as f:
            json.dump({"pid": process.pid, "args": process.args, "started_wall_ns": time.time_ns()}, f, indent=2)
        if source_guard:
            source_guard.start(time.monotonic_ns())
        while clock["sim_ns"] < 25_000_000_000:
            if errors or writer.error:
                raise RuntimeError("capture callback/writer failure: " + str(errors or writer.error))
            if shadow and shadow.failure:
                raise RuntimeError("shadow failure: " + shadow.failure)
            if process.poll() is not None:
                raise RuntimeError("PX4 exited during capture")
            if time.monotonic() - started > 300:
                raise TimeoutError("capture exceeded300s wall budget")
            if not server.run(True, 1000, False):
                raise RuntimeError("Gazebo rejected simulation run")
        result["status"] = "capture_completed"
    print(json.dumps({k: v for k, v in result.items() if k != "writer"}, indent=2))
    return 0 if result["status"] == "capture_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
