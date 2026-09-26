"""Record Gazebo motor-command delivery and raw odometry without publishing."""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from pathlib import Path

from flydrones.takeoff_readiness import actuator_model_names


def actuator_motor_topics(fleet_size: int) -> dict[str, str]:
    return {model: f"/{model}/command/motor_speed" for model in actuator_model_names(fleet_size)}


def _frame_id(message) -> str:
    values = [entry.value[0] for entry in message.header.data if entry.key == "frame_id" and entry.value]
    if len(values) != 1:
        raise ValueError("odometry must have exactly one frame_id")
    return str(values[0])


def _route_model(frame_id: str, models: tuple[str, ...]) -> str | None:
    matches = [model for model in models if model in frame_id]
    return matches[0] if len(matches) == 1 else None


def run_probe(
    *,
    output_path: Path,
    ready_marker: Path,
    completion_marker: Path | None,
    fleet_size: int,
    duration_s: float,
) -> None:
    from gz.msgs10.actuators_pb2 import Actuators
    from gz.msgs10.odometry_with_covariance_pb2 import OdometryWithCovariance
    from gz.transport13 import Node

    models = actuator_model_names(fleet_size)
    topics = actuator_motor_topics(fleet_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ready_marker.parent.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    lock = threading.RLock()
    node = Node()
    counts = {"motor-command": 0, "odometry": 0, "error": 0}

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    with output_path.open("w", encoding="utf-8", buffering=1) as handle:
        def record(event: dict[str, object]) -> None:
            with lock:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

        record({
            "event": "start",
            "monotonic_s": time.monotonic(),
            "models": list(models),
            "motor_topics": topics,
            "odometry_topic": "/flydrones/odometry_raw",
        })

        def motor_callback(model: str, topic: str):
            def receive(message) -> None:
                try:
                    velocities = [float(value) for value in message.velocity]
                    record({
                        "event": "motor-command",
                        "monotonic_s": time.monotonic(),
                        "model": model,
                        "topic": topic,
                        "velocities": velocities,
                    })
                    counts["motor-command"] += 1
                except Exception as exc:
                    counts["error"] += 1
                    record({"event": "error", "monotonic_s": time.monotonic(), "error": str(exc)})

            return receive

        def receive_odometry(message) -> None:
            try:
                frame_id = _frame_id(message)
                model = _route_model(frame_id, models)
                if model is None:
                    raise ValueError(f"unroutable odometry frame: {frame_id}")
                position = message.pose_with_covariance.pose.position
                record({
                    "event": "odometry",
                    "monotonic_s": time.monotonic(),
                    "model": model,
                    "frame_id": frame_id,
                    "position_m": [float(position.x), float(position.y), float(position.z)],
                })
                counts["odometry"] += 1
            except Exception as exc:
                counts["error"] += 1
                record({"event": "error", "monotonic_s": time.monotonic(), "error": str(exc)})

        subscriptions: list[str] = []
        try:
            for model, topic in topics.items():
                subscribed = node.subscribe(Actuators, topic, motor_callback(model, topic))
                record({
                    "event": "topology",
                    "monotonic_s": time.monotonic(),
                    "model": model,
                    "topic": topic,
                    "subscription_ok": subscribed is not False,
                })
                if subscribed is False:
                    raise RuntimeError(f"failed to subscribe to Gazebo motor topic: {topic}")
                subscriptions.append(topic)
            if node.subscribe(OdometryWithCovariance, "/flydrones/odometry_raw", receive_odometry) is False:
                raise RuntimeError("failed to subscribe to raw Gazebo odometry")
            subscriptions.append("/flydrones/odometry_raw")
            ready_marker.write_text(
                json.dumps({"ready": True, "models": list(models)}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline and not stop.is_set():
                if completion_marker is not None and completion_marker.exists():
                    break
                time.sleep(0.02)
        except Exception as exc:
            counts["error"] += 1
            record({"event": "error", "monotonic_s": time.monotonic(), "error": str(exc)})
            raise
        finally:
            stop.set()
            for topic in subscriptions:
                try:
                    if node.unsubscribe(topic) is False:
                        counts["error"] += 1
                        record({
                            "event": "error",
                            "monotonic_s": time.monotonic(),
                            "error": f"failed to unsubscribe: {topic}",
                        })
                except Exception as exc:
                    counts["error"] += 1
                    record({"event": "error", "monotonic_s": time.monotonic(), "error": str(exc)})
            record({"event": "stop", "monotonic_s": time.monotonic(), "counts": counts})


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the read-only PX4-to-Gazebo actuator evidence chain.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready-marker", type=Path, required=True)
    parser.add_argument("--completion-marker", type=Path)
    parser.add_argument("--vehicle-count", type=int, choices=(1, 5), default=5)
    parser.add_argument("--duration-s", type=float, default=300.0)
    args = parser.parse_args()
    run_probe(
        output_path=args.output,
        ready_marker=args.ready_marker,
        completion_marker=args.completion_marker,
        fleet_size=args.vehicle_count,
        duration_s=args.duration_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
