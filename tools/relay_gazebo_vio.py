"""Fault-trial Gazebo transport relay for PX4 external visual odometry."""

from __future__ import annotations

import argparse
import copy
import json
import signal
import socket
import threading
import time
from pathlib import Path

from flydrones.vio_faults import FaultProfile, FaultStream, read_activation, route_model_from_frame
from flydrones.vio_stream_monitor import SCHEMA as VIO_STREAM_SCHEMA


def frame_id_and_stamp(message) -> tuple[str, int]:
    frame_ids = [entry.value[0] for entry in message.header.data if entry.key == "frame_id" and entry.value]
    if len(frame_ids) != 1:
        raise ValueError("odometry must have exactly one frame_id")
    stamp = message.header.stamp
    return frame_ids[0], int(stamp.sec) * 1_000_000_000 + int(stamp.nsec)


def apply_position_offset(message, offset_m: tuple[float, float, float]):
    result = copy.deepcopy(message)
    position = result.pose_with_covariance.pose.position
    position.x += offset_m[0]
    position.y += offset_m[1]
    position.z += offset_m[2]
    return result


def encode_vio_stream_frame(*, vehicle_id: int, sequence: int, source_stamp_ns: int,
                            received_at: float, published_at: float) -> bytes:
    """Describe one successfully delivered frame to the local safety gate."""
    return json.dumps({
        "schema": VIO_STREAM_SCHEMA,
        "vehicle_id": vehicle_id,
        "sequence": sequence,
        "source_stamp_ns": source_stamp_ns,
        "received_at": received_at,
        "published_at": published_at,
    }, separators=(",", ":")).encode("utf-8")


def run_relay(*, profile_path: Path, marker_path: Path, output_path: Path,
              vehicle_count: int, health_base_port: int | None = None) -> None:
    from gz.msgs10.odometry_with_covariance_pb2 import OdometryWithCovariance
    from gz.transport13 import Node

    if vehicle_count not in (1, 5):
        raise ValueError("vehicle_count must be one or five")
    profile = FaultProfile.from_json(profile_path)
    if profile.vehicle_id >= vehicle_count:
        raise ValueError("fault vehicle is outside the running fleet")
    model_names = {f"x500_depth_fly_{index}" for index in range(vehicle_count)}
    stream = FaultStream(profile)
    health_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if health_base_port is not None else None
    sequences = {index: 0 for index in range(vehicle_count)}
    node = Node()
    publishers = {
        model: node.advertise(f"/model/{model}/odometry_with_covariance", OdometryWithCovariance)
        for model in model_names
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    lock = threading.RLock()
    counts = {"received": 0, "published": 0, "scheduled-dropout": 0, "random-dropout": 0,
              "queue-full": 0, "bad-frame": 0}

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    with output_path.open("w", encoding="utf-8", buffering=1) as log:
        def record(event: dict) -> None:
            log.write(json.dumps(event, sort_keys=True) + "\n")

        record({"event": "start", "profile": json.loads(profile_path.read_text(encoding="utf-8")),
                "marker_path": str(marker_path), "models": sorted(model_names), "monotonic_s": time.monotonic()})

        def callback(message) -> None:
            now = time.monotonic()
            with lock:
                counts["received"] += 1
                try:
                    frame_id, source_stamp_ns = frame_id_and_stamp(message)
                except (AttributeError, ValueError, IndexError) as exc:
                    counts["bad-frame"] += 1
                    record({"event": "drop", "reason": "bad-frame", "error": str(exc), "received_at": now})
                    return
                model = route_model_from_frame(frame_id, model_names)
                if model is None:
                    counts["bad-frame"] += 1
                    record({"event": "drop", "reason": "bad-frame", "frame_id": frame_id, "received_at": now})
                    return
                activation = read_activation(marker_path, vehicle_id=profile.vehicle_id, now=now)
                decision = stream.enqueue(
                    model, message.SerializeToString(), source_stamp_ns, now=now, activation_at=activation
                )
                raw_position = message.pose_with_covariance.pose.position
                if decision.reason != "queued":
                    counts[decision.reason] += 1
                record({"event": "ingress", "model": model, "source_stamp_ns": source_stamp_ns,
                        "received_at": now, "active": decision.active, "reason": decision.reason,
                        "due_at": decision.due_at, "offset_m": decision.offset_m,
                        "raw_position_m": [raw_position.x, raw_position.y, raw_position.z]})

        if not node.subscribe(OdometryWithCovariance, "/flydrones/odometry_raw", callback):
            raise RuntimeError("failed to subscribe to raw Gazebo odometry")
        try:
            while not stop.is_set():
                now = time.monotonic()
                with lock:
                    for item in stream.pop_ready(now):
                        message = OdometryWithCovariance()
                        message.ParseFromString(item.payload)
                        transformed = apply_position_offset(message, item.offset_m)
                        if not publishers[item.model_name].publish(transformed):
                            record({"event": "publish-failed", "model": item.model_name,
                                    "source_stamp_ns": item.source_stamp_ns, "monotonic_s": now})
                            continue
                        counts["published"] += 1
                        published_at = time.monotonic()
                        vehicle_id = int(item.model_name.rsplit("_", 1)[1])
                        if health_socket is not None:
                            sequences[vehicle_id] += 1
                            health_socket.sendto(
                                encode_vio_stream_frame(
                                    vehicle_id=vehicle_id,
                                    sequence=sequences[vehicle_id],
                                    source_stamp_ns=item.source_stamp_ns,
                                    received_at=item.received_at,
                                    published_at=published_at,
                                ),
                                ("127.0.0.1", health_base_port + vehicle_id),
                            )
                        record({"event": "publish", "model": item.model_name,
                                "source_stamp_ns": item.source_stamp_ns, "received_at": item.received_at,
                                "published_at": published_at,
                                "actual_delay_ms": round((published_at - item.received_at) * 1000, 4),
                                "offset_m": item.offset_m, "active": item.active,
                                "published_position_m": [transformed.pose_with_covariance.pose.position.x,
                                                         transformed.pose_with_covariance.pose.position.y,
                                                         transformed.pose_with_covariance.pose.position.z]})
                time.sleep(0.002)
        finally:
            if health_socket is not None:
                health_socket.close()
            record({"event": "stop", "monotonic_s": time.monotonic(), "counts": counts,
                    "queued_at_stop": stream.queue_size})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vehicle-count", type=int, choices=(1, 5), default=5)
    parser.add_argument("--health-base-port", type=int)
    args = parser.parse_args()
    run_relay(profile_path=args.profile, marker_path=args.marker, output_path=args.output,
              vehicle_count=args.vehicle_count, health_base_port=args.health_base_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
