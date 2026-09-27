"""Observe actual Gazebo depth-image phases without feeding control paths."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPTH_SUFFIX = "/link/camera_link/sensor/StereoOV7251/depth_image"


class ProbeFailure(RuntimeError):
    pass


class CallbackBuffer:
    """Bounded callback handoff; callbacks never write files or score evidence."""

    def __init__(self, *, capacity: int, monotonic: Callable[[], float]) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=capacity)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._latest_clock_ns: int | None = None
        self._clock_sequence = 0
        self._image_sequences: dict[int, int] = {}
        self._trigger_sequences: dict[int, int] = {}
        self._overflow_count = 0

    def clock_callback(self, message) -> None:
        sim_ns = int(message.sim.sec) * 1_000_000_000 + int(message.sim.nsec)
        received = self._monotonic()
        with self._lock:
            self._latest_clock_ns = sim_ns
            self._clock_sequence += 1
            self._last_clock_receipt_monotonic_s = received

    def clock_snapshot(self) -> tuple[int | None, int]:
        with self._lock:
            return self._latest_clock_ns, self._clock_sequence

    def _enqueue(self, event: dict[str, object]) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._overflow_count += 1

    def image_callback(self, vehicle_id: int, topic: str):
        def receive(message) -> None:
            sim_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
            receipt = self._monotonic()
            with self._lock:
                receipt_sim_ns = self._latest_clock_ns
                sequence = self._image_sequences.get(vehicle_id, 0)
                self._image_sequences[vehicle_id] = sequence + 1
            self._enqueue({
                "event": "image",
                "vehicle_id": vehicle_id,
                "topic": topic,
                "sim_ns": sim_ns,
                "receipt_sim_ns": receipt_sim_ns,
                "receipt_monotonic_s": receipt,
                "sequence": sequence,
                "width": int(message.width),
                "height": int(message.height),
            })

        return receive

    def trigger_callback(self, vehicle_id: int, topic: str):
        def receive(message) -> None:
            receipt = self._monotonic()
            with self._lock:
                receipt_sim_ns = self._latest_clock_ns
                sequence = self._trigger_sequences.get(vehicle_id, 0)
                self._trigger_sequences[vehicle_id] = sequence + 1
            self._enqueue({
                "event": "trigger-received",
                "vehicle_id": vehicle_id,
                "topic": topic,
                "receipt_sim_ns": receipt_sim_ns,
                "receipt_monotonic_s": receipt,
                "sequence": sequence,
                "data": bool(message.data),
            })

        return receive

    def drain(self) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return events

    def take_overflow_count(self) -> int:
        with self._lock:
            count = self._overflow_count
            self._overflow_count = 0
        return count

    def empty(self) -> bool:
        return self._queue.empty()


class JsonlWriter:
    def __init__(self, path: Path, monotonic: Callable[[], float]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", encoding="utf-8", buffering=1)
        self._monotonic = monotonic

    def write(self, event: Mapping[str, object] | str, **fields: object) -> None:
        if isinstance(event, str):
            payload = {"event": event, "wall_monotonic_s": self._monotonic(), **fields}
        else:
            payload = dict(event)
        self._handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _path(config: Mapping[str, object], name: str) -> Path:
    value = config.get(name)
    if not isinstance(value, (str, Path)):
        raise ValueError(f"{name} must be a path")
    return Path(value)


def _positive_number(config: Mapping[str, object], name: str) -> float:
    value = config.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def _load_scheduler_ready(path: Path, *, vehicle_count: int) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeFailure(f"scheduler_ready_invalid: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "flydrones-camera-scheduler-ready-v1"
        or payload.get("vehicle_count") != vehicle_count
        or not isinstance(payload.get("epoch_ns"), int)
        or not isinstance(payload.get("trigger_topics"), list)
        or len(payload["trigger_topics"]) != vehicle_count
    ):
        raise ProbeFailure("scheduler_ready_invalid")
    return payload


def summarize_probe_log(
    path: Path,
    *,
    mode,
    vehicle_count: int,
    thresholds,
) -> dict[str, object]:
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from flydrones.camera_phase import summarize_camera_phase

    events: list[Mapping[str, object]] = []
    malformed_lines: list[int] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line_number)
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            malformed_lines.append(line_number)
    result = summarize_camera_phase(
        events,
        mode=mode,
        vehicle_count=vehicle_count,
        thresholds=thresholds,
    )
    if malformed_lines:
        result["accepted"] = False
        result["reasons"] = list(dict.fromkeys([*result["reasons"], "malformed_jsonl"]))
        result["malformed_jsonl_lines"] = malformed_lines
    return result


def run_probe(
    config: Mapping[str, object],
    *,
    node_factory: Callable[[], object] | None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    output = _path(config, "output")
    ready_marker = _path(config, "ready_marker")
    summary_path = _path(config, "summary")
    completion_marker = _path(config, "completion_marker")
    mode_value = config.get("mode")
    if mode_value not in ("simultaneous", "phased"):
        raise ValueError("mode must be simultaneous or phased")
    vehicle_count = config.get("vehicle_count")
    if vehicle_count not in (1, 5):
        raise ValueError("vehicle_count must be 1 or 5")
    vehicle_count = int(vehicle_count)
    world = config.get("world", "flydrones_forest")
    if not isinstance(world, str) or not world:
        raise ValueError("world must be a non-empty string")
    topology_timeout_s = _positive_number(config, "topology_timeout_s")
    duration_s = _positive_number(config, "duration_s")
    poll_interval_s = _positive_number(config, "poll_interval_s")
    queue_capacity = config.get("queue_capacity", 2048)
    if isinstance(queue_capacity, bool) or not isinstance(queue_capacity, int) or queue_capacity < 500:
        raise ValueError("queue_capacity must hold at least 10 seconds of five 10 Hz streams")
    scheduler_ready_marker = (
        _path(config, "scheduler_ready_marker") if mode_value == "phased" else None
    )

    for path in (output, ready_marker, summary_path, completion_marker):
        path.parent.mkdir(parents=True, exist_ok=True)
    ready_marker.unlink(missing_ok=True)
    summary_path.unlink(missing_ok=True)

    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from flydrones.camera_phase import (
        CameraPhaseThresholds,
        CameraScheduleMode,
        align_epoch_ns,
        camera_phase_offsets_ns,
        depth_topic_vehicle_id,
    )

    if node_factory is None:
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.clock_pb2 import Clock
        from gz.msgs10.image_pb2 import Image
        from gz.transport13 import Node

        node_factory = Node
        clock_type: object = Clock
        image_type: object = Image
        trigger_type: object = Boolean
    else:
        clock_type = image_type = trigger_type = object

    buffer = CallbackBuffer(capacity=queue_capacity, monotonic=monotonic)
    writer = JsonlWriter(output, monotonic)
    writer.write(
        "start",
        schema="flydrones-camera-phase-probe-v1",
        mode=mode_value,
        vehicle_count=vehicle_count,
        world=world,
        queue_capacity=queue_capacity,
    )
    node = None
    subscribed_topics: list[str] = []
    status = 3
    completed = False
    overflow_total = 0
    epoch_ns = 0
    depth_topics: dict[int, str] = {}
    trigger_topics: dict[int, str] = {}
    started = monotonic()
    try:
        node = node_factory()
        if node is None:
            raise ProbeFailure("node_factory_returned_none")
        if node.subscribe(clock_type, "/clock", buffer.clock_callback) is False:
            raise ProbeFailure("clock_subscription_failed")
        subscribed_topics.append("/clock")

        deadline = monotonic() + topology_timeout_s
        while monotonic() < deadline:
            candidates = [topic for topic in node.topic_list() if topic.endswith(DEPTH_SUFFIX)]
            if len(candidates) != len(set(candidates)):
                writer.write("topology", accepted=False, reasons=["duplicate_depth_topic"])
                raise ProbeFailure("duplicate_depth_topic")
            mapped: dict[int, str] = {}
            cross_model = False
            for topic in candidates:
                vehicle_id = depth_topic_vehicle_id(topic, world=world, vehicle_count=vehicle_count)
                if vehicle_id is None or vehicle_id in mapped:
                    cross_model = True
                else:
                    mapped[vehicle_id] = topic
            if cross_model:
                writer.write("topology", accepted=False, reasons=["cross_model_depth_topic"])
                raise ProbeFailure("cross_model_depth_topic")
            if sorted(mapped) == list(range(vehicle_count)):
                depth_topics = mapped
                trigger_topics = {vehicle_id: f"{topic}/trigger" for vehicle_id, topic in mapped.items()}
                for vehicle_id in range(vehicle_count):
                    topic = depth_topics[vehicle_id]
                    if node.subscribe(image_type, topic, buffer.image_callback(vehicle_id, topic)) is False:
                        raise ProbeFailure("image_subscription_failed")
                    subscribed_topics.append(topic)
                    if mode_value == "phased":
                        trigger_topic = trigger_topics[vehicle_id]
                        if node.subscribe(
                            trigger_type,
                            trigger_topic,
                            buffer.trigger_callback(vehicle_id, trigger_topic),
                        ) is False:
                            raise ProbeFailure("trigger_subscription_failed")
                        subscribed_topics.append(trigger_topic)
                writer.write(
                    "topology",
                    accepted=True,
                    reasons=[],
                    depth_topics=[depth_topics[index] for index in range(vehicle_count)],
                    trigger_topics=(
                        [trigger_topics[index] for index in range(vehicle_count)]
                        if mode_value == "phased"
                        else []
                    ),
                )
                break
            sleep(poll_interval_s)
        else:
            raise ProbeFailure("topology_incomplete")

        readiness_deadline = monotonic() + topology_timeout_s
        scheduler_ready = None
        while monotonic() < readiness_deadline:
            latest_clock, _ = buffer.clock_snapshot()
            if mode_value == "phased":
                assert scheduler_ready_marker is not None
                scheduler_ready = _load_scheduler_ready(
                    scheduler_ready_marker,
                    vehicle_count=vehicle_count,
                )
            if latest_clock is not None and (mode_value == "simultaneous" or scheduler_ready is not None):
                if scheduler_ready is not None:
                    if scheduler_ready["trigger_topics"] != [
                        trigger_topics[index] for index in range(vehicle_count)
                    ]:
                        raise ProbeFailure("scheduler_trigger_topics_mismatch")
                    epoch_ns = int(scheduler_ready["epoch_ns"])
                else:
                    epoch_ns = align_epoch_ns(latest_clock)
                break
            sleep(poll_interval_s)
        else:
            raise ProbeFailure("readiness_timeout")

        ready_payload = {
            "schema": "flydrones-camera-phase-ready-v1",
            "mode": mode_value,
            "vehicle_count": vehicle_count,
            "epoch_ns": epoch_ns,
            "depth_topics": [depth_topics[index] for index in range(vehicle_count)],
            "trigger_topics": (
                [trigger_topics[index] for index in range(vehicle_count)]
                if mode_value == "phased"
                else []
            ),
        }
        _atomic_json(ready_marker, ready_payload)
        writer.write("ready", **{key: value for key, value in ready_payload.items() if key != "schema"})

        offsets = camera_phase_offsets_ns(vehicle_count)
        while monotonic() - started < duration_s:
            for event in buffer.drain():
                if event["event"] == "trigger-received":
                    vehicle_id = int(event["vehicle_id"])
                    receipt_sim_ns = event.get("receipt_sim_ns")
                    if not isinstance(receipt_sim_ns, int):
                        writer.write({**event, "event": "malformed"})
                        continue
                    cycle = round((receipt_sim_ns - epoch_ns - offsets[vehicle_id]) / 100_000_000)
                    writer.write({
                        "event": "trigger",
                        "vehicle_id": vehicle_id,
                        "cycle": cycle,
                        "topic": event["topic"],
                        "planned_sim_ns": epoch_ns + cycle * 100_000_000 + offsets[vehicle_id],
                        "published_sim_ns": receipt_sim_ns,
                        "receipt_monotonic_s": event["receipt_monotonic_s"],
                        "sequence": event["sequence"],
                    })
                else:
                    writer.write(event)
            dropped = buffer.take_overflow_count()
            if dropped:
                overflow_total += dropped
                writer.write("queue-overflow", dropped_count=dropped)
            if completion_marker.exists() and buffer.empty():
                completed = True
                status = 2 if overflow_total else 0
                break
            sleep(poll_interval_s)
        else:
            raise ProbeFailure("duration_timeout")
    except ProbeFailure as exc:
        writer.write("error", reason=str(exc), message=str(exc))
        status = 3
    except Exception as exc:
        writer.write("error", reason="runtime_error", message=f"{type(exc).__name__}: {exc}")
        status = 3
    finally:
        if node is not None:
            for topic in reversed(subscribed_topics):
                try:
                    node.unsubscribe(topic)
                except Exception as exc:
                    writer.write("error", reason="unsubscribe_failed", topic=topic, message=str(exc))
                    status = 3
        writer.write("stop", exit_code=status, completed=completed, overflow_count=overflow_total)
        writer.close()

    if completed:
        summary = summarize_probe_log(
            output,
            mode=CameraScheduleMode(mode_value),
            vehicle_count=vehicle_count,
            thresholds=CameraPhaseThresholds(),
        )
        _atomic_json(summary_path, summary)
        if summary["accepted"] is not True:
            status = 2
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe actual Gazebo depth-image camera phases.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready-marker", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--completion-marker", type=Path, required=True)
    parser.add_argument("--mode", choices=("simultaneous", "phased"), required=True)
    parser.add_argument("--vehicle-count", type=int, choices=(1, 5), required=True)
    parser.add_argument("--world", default="flydrones_forest")
    parser.add_argument("--scheduler-ready-marker", type=Path)
    parser.add_argument("--topology-timeout-s", type=float, default=30.0)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.01)
    parser.add_argument("--queue-capacity", type=int, default=2048)
    args = parser.parse_args()
    if args.mode == "phased" and args.scheduler_ready_marker is None:
        parser.error("--scheduler-ready-marker is required in phased mode")
    return run_probe(
        {
            "output": args.output,
            "ready_marker": args.ready_marker,
            "summary": args.summary,
            "completion_marker": args.completion_marker,
            "mode": args.mode,
            "vehicle_count": args.vehicle_count,
            "world": args.world,
            "scheduler_ready_marker": args.scheduler_ready_marker,
            "topology_timeout_s": args.topology_timeout_s,
            "duration_s": args.duration_s,
            "poll_interval_s": args.poll_interval_s,
            "queue_capacity": args.queue_capacity,
        },
        node_factory=None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
