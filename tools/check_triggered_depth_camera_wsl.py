"""Verify that the installed Gazebo stack supports triggered depth cameras."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

IMAGE_TOPIC = "/trigger_probe/depth"
TRIGGER_TOPIC = "/trigger_probe/depth/trigger"
BOOLEAN_TYPE = "gz.msgs.Boolean"
EXPECTED_TRIGGER_COUNT = 3


def _one(events: Sequence[Mapping[str, object]], name: str) -> Mapping[str, object] | None:
    matches = [event for event in events if event.get("event") == name]
    return matches[0] if len(matches) == 1 else None


def classify_probe(events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Classify an installed-stack probe without importing Gazebo bindings."""
    reasons: list[str] = []
    warnings: list[str] = []
    start = _one(events, "start")
    if start is None:
        reasons.append("start_missing_or_duplicate")
        image_topic = None
        trigger_topic = None
        renderer_profile = None
    else:
        image_topic = start.get("image_topic")
        trigger_topic = start.get("trigger_topic")
        renderer_profile = start.get("renderer_profile")

    renderer = _one(events, "renderer")
    if (
        renderer is None
        or renderer.get("accepted") is not True
        or renderer.get("requested_profile") != renderer_profile
    ):
        reasons.append("renderer_not_attested")

    pretrigger_markers = [event for event in events if event.get("event") == "pretrigger_window_complete"]
    if len(pretrigger_markers) != 1:
        reasons.append("pretrigger_window_incomplete")
        marker_index = len(events)
    else:
        marker_index = events.index(pretrigger_markers[0])
    pretrigger_images = [
        event
        for index, event in enumerate(events)
        if event.get("event") == "image" and index < marker_index
    ]
    if pretrigger_images:
        reasons.append("pretrigger_image_observed")

    triggers = [event for event in events if event.get("event") == "trigger"]
    if len(triggers) != EXPECTED_TRIGGER_COUNT:
        reasons.append("trigger_count_mismatch")
    expected_indices = list(range(EXPECTED_TRIGGER_COUNT))
    if [event.get("trigger_index") for event in triggers] != expected_indices:
        reasons.append("trigger_sequence_invalid")
    if any(event.get("topic") != trigger_topic for event in triggers):
        reasons.append("trigger_topic_mismatch")
    if any(event.get("message_type") != BOOLEAN_TYPE for event in triggers):
        reasons.append("trigger_message_type_mismatch")
    if any(event.get("published") is not True for event in triggers):
        reasons.append("trigger_publish_failed")

    images = [event for event in events if event.get("event") == "image"]
    if any(event.get("topic") != image_topic for event in images):
        reasons.append("image_topic_mismatch")
    images_per_trigger = {
        str(index): sum(event.get("trigger_index") == index for event in images)
        for index in expected_indices
    }
    if any(count != 1 for count in images_per_trigger.values()):
        reasons.append("image_count_mismatch")
    unmatched_images = [
        event for event in images[0:] if event.get("trigger_index") not in expected_indices
    ]
    if unmatched_images and not all(event in pretrigger_images for event in unmatched_images):
        reasons.append("unmatched_image")

    image_timestamps = [event.get("sim_ns") for event in images if event not in pretrigger_images]
    if len(image_timestamps) != EXPECTED_TRIGGER_COUNT or any(
        not isinstance(timestamp, int) or isinstance(timestamp, bool)
        for timestamp in image_timestamps
    ):
        reasons.append("image_timestamp_missing")
    elif any(
        current <= previous
        for previous, current in zip(image_timestamps, image_timestamps[1:])
    ):
        reasons.append("image_timestamp_not_monotonic")

    cleanup = _one(events, "cleanup")
    if cleanup is None or cleanup.get("owned_process_released") is not True:
        reasons.append("cleanup_not_verified")
    elif cleanup.get("returncode") not in (0, -2, -9, -15):
        warnings.append("owned_process_abnormal_exit")
    if _one(events, "stop") is None:
        reasons.append("stop_missing_or_duplicate")
    if any(event.get("event") == "error" for event in events):
        reasons.append("probe_error")

    return {
        "schema": "flydrones-triggered-depth-classification-v1",
        "accepted": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "warnings": warnings,
        "pretrigger_image_count": len(pretrigger_images),
        "trigger_count": len(triggers),
        "image_count": len(images),
        "images_per_trigger": images_per_trigger,
        "image_sim_ns": image_timestamps,
    }


def _probe_world() -> str:
    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <world name="trigger_probe">
    <physics name="4ms" type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <scene>
      <ambient>0.5 0.5 0.5 1</ambient>
      <background>0.1 0.1 0.1 1</background>
      <shadows>false</shadows>
    </scene>
    <light name="sun" type="directional">
      <direction>-1 0 -1</direction>
      <diffuse>1 1 1 1</diffuse>
    </light>
    <model name="target">
      <static>true</static>
      <pose>3 0 0 0 0 0</pose>
      <link name="link">
        <visual name="visual"><geometry><box><size>1 1 1</size></box></geometry></visual>
      </link>
    </model>
    <model name="camera_model">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="camera_link">
        <sensor name="depth" type="depth_camera">
          <camera>
            <triggered>true</triggered>
            <trigger_topic>{TRIGGER_TOPIC}</trigger_topic>
            <horizontal_fov>1.047</horizontal_fov>
            <image><width>16</width><height>12</height><format>R_FLOAT32</format></image>
            <clip><near>0.1</near><far>10</far></clip>
          </camera>
          <always_on>true</always_on>
          <update_rate>10</update_rate>
          <visualize>false</visualize>
          <topic>{IMAGE_TOPIC}</topic>
        </sensor>
      </link>
    </model>
  </world>
</sdf>
"""


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable: {exc}"
    return result.stdout.strip()


def _renderer_event(pid: int, environment: Mapping[str, str], profile: str) -> dict[str, object]:
    errors: list[str] = []
    egl_renderer: str | None = None
    try:
        result = subprocess.run(
            ["eglinfo", "-B"],
            env=dict(environment),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "renderer" in line.lower() and ":" in line:
                candidate = line.split(":", 1)[1].strip()
                if candidate:
                    egl_renderer = candidate
        if egl_renderer is None:
            errors.append("egl_renderer_missing")
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"eglinfo: {exc}")

    try:
        maps = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8", errors="replace")
        libraries = sorted({
            line.split()[-1]
            for line in maps.splitlines()
            if line.split() and ".so" in line.split()[-1]
        })
    except OSError as exc:
        libraries = []
        errors.append(f"process_maps: {exc}")
    library_names = {Path(item).name for item in libraries}
    if profile == "d3d12-nvidia":
        rendered = (egl_renderer or "").upper()
        if "D3D12" not in rendered:
            errors.append("d3d12_not_active")
        if "NVIDIA" not in rendered:
            errors.append("required_adapter_missing")
        if not {"libd3d12.so", "libdxcore.so"}.issubset(library_names):
            errors.append("d3d12_libraries_missing")
    return {
        "event": "renderer",
        "accepted": not errors,
        "requested_profile": profile,
        "egl_renderer": egl_renderer,
        "mapped_libraries": libraries,
        "errors": errors,
    }


def _stop_owned_process(process: subprocess.Popen[str]) -> tuple[bool, int | None]:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except ProcessLookupError:
            pass
    return process.poll() is not None, process.returncode


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def run_probe(output: Path, *, renderer_profile: str = "d3d12-nvidia") -> dict[str, object]:
    """Run one owned headless Gazebo compatibility probe and write its record."""
    if renderer_profile not in {"default", "d3d12-nvidia"}:
        raise ValueError(f"unsupported renderer profile: {renderer_profile}")
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.image_pb2 import Image
    from gz.transport13 import Node

    environment = os.environ.copy()
    environment.pop("GALLIUM_DRIVER", None)
    environment.pop("MESA_D3D12_DEFAULT_ADAPTER_NAME", None)
    if renderer_profile == "d3d12-nvidia":
        environment.update({
            "GALLIUM_DRIVER": "d3d12",
            "MESA_D3D12_DEFAULT_ADAPTER_NAME": "NVIDIA",
        })

    events: list[dict[str, object]] = [{
        "event": "start",
        "image_topic": IMAGE_TOPIC,
        "trigger_topic": TRIGGER_TOPIC,
        "renderer_profile": renderer_profile,
        "wall_monotonic_s": time.monotonic(),
    }]
    lock = threading.Lock()
    active_trigger: int | None = None
    process: subprocess.Popen[str] | None = None
    node = None
    started = time.monotonic()
    stdout_tail = ""
    try:
        with tempfile.TemporaryDirectory(prefix="flydrones-triggered-depth-") as directory:
            temporary = Path(directory)
            world = temporary / "triggered-depth.sdf"
            log_path = temporary / "gazebo.log"
            world.write_text(_probe_world(), encoding="utf-8")
            with log_path.open("w+", encoding="utf-8") as gazebo_log:
                process = subprocess.Popen(
                    ["gz", "sim", "--headless-rendering", "-r", "-s", str(world)],
                    env=environment,
                    stdout=gazebo_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                node = Node()

                def on_image(message) -> None:
                    stamp = message.header.stamp
                    sim_ns = int(stamp.sec) * 1_000_000_000 + int(stamp.nsec)
                    with lock:
                        events.append({
                            "event": "image",
                            "trigger_index": active_trigger,
                            "topic": IMAGE_TOPIC,
                            "sim_ns": sim_ns,
                            "wall_monotonic_s": time.monotonic(),
                            "width": int(message.width),
                            "height": int(message.height),
                        })

                if node.subscribe(Image, IMAGE_TOPIC, on_image) is False:
                    raise RuntimeError(f"failed to subscribe to {IMAGE_TOPIC}")
                publisher = node.advertise(TRIGGER_TOPIC, Boolean)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not publisher.has_connections():
                    if process.poll() is not None:
                        raise RuntimeError(f"Gazebo exited before trigger readiness: {process.returncode}")
                    time.sleep(0.05)
                if not publisher.has_connections():
                    raise RuntimeError("trigger topic did not gain a subscriber")

                time.sleep(1.5)
                with lock:
                    events.append({"event": "pretrigger_window_complete"})
                for index in range(EXPECTED_TRIGGER_COUNT):
                    with lock:
                        active_trigger = index
                    message = Boolean()
                    message.data = True
                    publisher.publish(message)
                    with lock:
                        events.append({
                            "event": "trigger",
                            "trigger_index": index,
                            "topic": TRIGGER_TOPIC,
                            "message_type": BOOLEAN_TYPE,
                            "published": True,
                            "wall_monotonic_s": time.monotonic(),
                        })
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with lock:
                            count = sum(
                                event.get("event") == "image"
                                and event.get("trigger_index") == index
                                for event in events
                            )
                        if count >= 1:
                            break
                        if process.poll() is not None:
                            raise RuntimeError(f"Gazebo exited after trigger {index}: {process.returncode}")
                        time.sleep(0.02)
                    time.sleep(0.15)
                events.append(_renderer_event(process.pid, environment, renderer_profile))
                node.unsubscribe(IMAGE_TOPIC)
                node = None
                released, returncode = _stop_owned_process(process)
                events.append({
                    "event": "cleanup",
                    "owned_process_released": released,
                    "returncode": returncode,
                })
                process = None
                events.append({"event": "stop"})
                gazebo_log.flush()
                gazebo_log.seek(0)
                stdout_tail = gazebo_log.read()[-8000:]
    except Exception as exc:
        events.append({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        if node is not None:
            try:
                node.unsubscribe(IMAGE_TOPIC)
            except Exception:
                pass
        if process is not None:
            released, returncode = _stop_owned_process(process)
            events.append({
                "event": "cleanup",
                "owned_process_released": released,
                "returncode": returncode,
            })
            events.append({"event": "stop"})

    classification = classify_probe(events)
    record: dict[str, object] = {
        "schema": "flydrones-triggered-depth-compatibility-v1",
        "classification": classification,
        "accepted": classification["accepted"],
        "reasons": classification["reasons"],
        "warnings": classification["warnings"],
        "versions": {
            "gz_sim": _version(["gz", "sim", "--version"]),
            "gz_transport": _version(["gz", "transport", "--version"]),
        },
        "duration_wall_s": time.monotonic() - started,
        "events": events,
        "gazebo_log_tail": stdout_tail,
    }
    _atomic_json(output, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe installed Gazebo triggered depth-camera support under WSL."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--renderer-profile",
        choices=("default", "d3d12-nvidia"),
        default="d3d12-nvidia",
    )
    args = parser.parse_args()
    result = run_probe(args.output, renderer_profile=args.renderer_profile)
    print(json.dumps({
        "output": str(args.output),
        "accepted": result["accepted"],
        "reasons": result["reasons"],
    }, ensure_ascii=False))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
