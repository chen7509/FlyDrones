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


def _pixel_format_name(message: object) -> str:
    value = getattr(message, "pixel_format_type", None)
    if isinstance(value, str):
        return value
    try:
        field = message.DESCRIPTOR.fields_by_name["pixel_format_type"]
        enum_value = field.enum_type.values_by_number[int(value)]
        name = enum_value.name
    except (AttributeError, KeyError, TypeError, ValueError):
        return "UNKNOWN_PIXEL_FORMAT"
    return name if isinstance(name, str) else "UNKNOWN_PIXEL_FORMAT"


def subscribe_retained(
    node: object,
    callback_references: list[Callable[..., object]],
    message_type: object,
    topic: str,
    callback: Callable[..., object],
) -> bool:
    """Subscribe while retaining callback ownership on the Python side."""
    callback_references.append(callback)
    if node.subscribe(message_type, topic, callback) is False:
        callback_references.pop()
        return False
    return True


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
                "format": _pixel_format_name(message),
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
        self._handle = path.open("w", encoding="utf-8", buffering=65_536)
        self._monotonic = monotonic

    def write(self, event: Mapping[str, object] | str, **fields: object) -> None:
        if isinstance(event, str):
            payload = {"event": event, "wall_monotonic_s": self._monotonic(), **fields}
        else:
            payload = dict(event)
        self._handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def flush(self) -> None:
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
    stream_timeout_value = config.get("stream_timeout_s", 90.0)
    if (
        isinstance(stream_timeout_value, bool)
        or not isinstance(stream_timeout_value, (int, float))
        or float(stream_timeout_value) <= 0
    ):
        raise ValueError("stream_timeout_s must be positive")
    stream_timeout_s = float(stream_timeout_value)
    duration_s = _positive_number(config, "duration_s")
    poll_interval_s = _positive_number(config, "poll_interval_s")
    completion_drain_value = config.get("completion_drain_s", 1.0)
    if (
        isinstance(completion_drain_value, bool)
        or not isinstance(completion_drain_value, (int, float))
        or float(completion_drain_value) <= 0
    ):
        raise ValueError("completion_drain_s must be positive")
    completion_drain_s = float(completion_drain_value)
    flush_interval_s = _positive_number(config, "flush_interval_s")
    warmup_image_count_min = config.get("warmup_image_count_min", 11)
    if (
        isinstance(warmup_image_count_min, bool)
        or not isinstance(warmup_image_count_min, int)
        or warmup_image_count_min < 2
    ):
        raise ValueError("warmup_image_count_min must be an integer of at least two")
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
        completion_drain_s=completion_drain_s,
        stream_timeout_s=stream_timeout_s,
        flush_interval_s=flush_interval_s,
        warmup_image_count_min=warmup_image_count_min,
    )
    writer.flush()
    node = None
    subscription_nodes: list[object] = []
    subscribed_topics: list[tuple[object, str]] = []
    callback_references: list[Callable[..., object]] = []
    status = 3
    completed = False
    overflow_total = 0
    epoch_ns = 0
    depth_topics: dict[int, str] = {}
    trigger_topics: dict[int, str] = {}
    observation_start_sim_ns = 0
    started = monotonic()
    completion_seen_at: float | None = None
    try:
        node = node_factory()
        if node is None:
            raise ProbeFailure("node_factory_returned_none")
        clock_callback = buffer.clock_callback
        if not subscribe_retained(
            node,
            callback_references,
            clock_type,
            "/clock",
            clock_callback,
        ):
            raise ProbeFailure("clock_subscription_failed")
        subscribed_topics.append((node, "/clock"))

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
                    subscription_node = node_factory()
                    if subscription_node is None:
                        raise ProbeFailure("subscription_node_factory_returned_none")
                    subscription_nodes.append(subscription_node)
                    topic = depth_topics[vehicle_id]
                    image_callback = buffer.image_callback(vehicle_id, topic)
                    if not subscribe_retained(
                        subscription_node,
                        callback_references,
                        image_type,
                        topic,
                        image_callback,
                    ):
                        raise ProbeFailure("image_subscription_failed")
                    subscribed_topics.append((subscription_node, topic))
                    if mode_value == "phased":
                        trigger_topic = trigger_topics[vehicle_id]
                        trigger_callback = buffer.trigger_callback(vehicle_id, trigger_topic)
                        if not subscribe_retained(
                            subscription_node,
                            callback_references,
                            trigger_type,
                            trigger_topic,
                            trigger_callback,
                        ):
                            raise ProbeFailure("trigger_subscription_failed")
                        subscribed_topics.append((subscription_node, trigger_topic))
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
                writer.flush()
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

        warmup_image_counts = {vehicle_id: 0 for vehicle_id in range(vehicle_count)}
        warmup_trigger_counts = {vehicle_id: 0 for vehicle_id in range(vehicle_count)}
        warmup_first_sim_ns: dict[int, int] = {}
        warmup_last_sim_ns: dict[int, int] = {}
        warmup_dimensions: dict[int, tuple[int, int]] = {}
        stream_deadline = monotonic() + stream_timeout_s
        while monotonic() < stream_deadline:
            for event in buffer.drain():
                vehicle_id = event.get("vehicle_id")
                if not isinstance(vehicle_id, int) or vehicle_id not in warmup_image_counts:
                    continue
                if event.get("event") == "image":
                    warmup_image_counts[vehicle_id] += 1
                    sim_ns = event.get("sim_ns")
                    width = event.get("width")
                    height = event.get("height")
                    if not all(isinstance(value, int) for value in (sim_ns, width, height)):
                        raise ProbeFailure("warmup_image_metadata_invalid")
                    dimensions = (int(width), int(height))
                    previous_dimensions = warmup_dimensions.setdefault(vehicle_id, dimensions)
                    if dimensions != previous_dimensions:
                        raise ProbeFailure("warmup_image_dimensions_changed")
                    warmup_first_sim_ns.setdefault(vehicle_id, int(sim_ns))
                    warmup_last_sim_ns[vehicle_id] = int(sim_ns)
                elif event.get("event") == "trigger-received":
                    warmup_trigger_counts[vehicle_id] += 1
            dropped = buffer.take_overflow_count()
            if dropped:
                overflow_total += dropped
                writer.write("queue-overflow", dropped_count=dropped, phase="warmup")
                raise ProbeFailure("callback_queue_overflow")
            if all(count >= warmup_image_count_min for count in warmup_image_counts.values()):
                latest_clock, _ = buffer.clock_snapshot()
                if latest_clock is None:
                    raise ProbeFailure("clock_sample_missing")
                observation_start_sim_ns = align_epoch_ns(latest_clock + 1)
                break
            if completion_marker.exists():
                raise ProbeFailure("completion_before_stream_readiness")
            sleep(poll_interval_s)
        else:
            writer.write(
                "warmup",
                accepted=False,
                image_counts=warmup_image_counts,
                trigger_counts=warmup_trigger_counts,
            )
            raise ProbeFailure("stream_readiness_timeout")

        writer.write(
            "warmup",
            accepted=True,
            image_counts=warmup_image_counts,
            trigger_counts=warmup_trigger_counts,
            observation_start_sim_ns=observation_start_sim_ns,
        )
        writer.flush()

        depth_observations: dict[str, dict[str, int | float]] = {}
        for vehicle_id in range(vehicle_count):
            first_sim_ns = warmup_first_sim_ns[vehicle_id]
            last_sim_ns = warmup_last_sim_ns[vehicle_id]
            count = warmup_image_counts[vehicle_id]
            if last_sim_ns <= first_sim_ns:
                raise ProbeFailure("warmup_image_frequency_invalid")
            width, height = warmup_dimensions[vehicle_id]
            depth_observations[depth_topics[vehicle_id]] = {
                "width": width,
                "height": height,
                "frequency_hz": (count - 1) * 1_000_000_000 / (last_sim_ns - first_sim_ns),
                "message_count": count,
            }

        ready_payload = {
            "schema": "flydrones-camera-phase-ready-v1",
            "mode": mode_value,
            "vehicle_count": vehicle_count,
            "epoch_ns": epoch_ns,
            "observation_start_sim_ns": observation_start_sim_ns,
            "warmup_image_counts": warmup_image_counts,
            "warmup_trigger_counts": warmup_trigger_counts,
            "depth_topics": [depth_topics[index] for index in range(vehicle_count)],
            "depth_observations": depth_observations,
            "trigger_topics": (
                [trigger_topics[index] for index in range(vehicle_count)]
                if mode_value == "phased"
                else []
            ),
        }
        _atomic_json(ready_marker, ready_payload)
        writer.write("ready", **{key: value for key, value in ready_payload.items() if key != "schema"})
        writer.flush()

        offsets = camera_phase_offsets_ns(vehicle_count)
        last_flush_at = monotonic()
        last_transport_event_kind: str | None = None
        while monotonic() - started < duration_s:
            drained_events = buffer.drain()
            for event in drained_events:
                if event.get("event") in {"trigger-received", "image"}:
                    last_transport_event_kind = str(event["event"])
                if event["event"] == "trigger-received":
                    vehicle_id = int(event["vehicle_id"])
                    receipt_sim_ns = event.get("receipt_sim_ns")
                    if not isinstance(receipt_sim_ns, int):
                        writer.write({**event, "event": "malformed"})
                        continue
                    cycle = round((receipt_sim_ns - epoch_ns - offsets[vehicle_id]) / 100_000_000)
                    planned_sim_ns = epoch_ns + cycle * 100_000_000 + offsets[vehicle_id]
                    if planned_sim_ns < observation_start_sim_ns:
                        continue
                    sequence = int(event["sequence"])
                    writer.write({
                        "event": "trigger",
                        "vehicle_id": vehicle_id,
                        "cycle": cycle,
                        "topic": event["topic"],
                        "planned_sim_ns": planned_sim_ns,
                        "published_sim_ns": receipt_sim_ns,
                        "receipt_monotonic_s": event["receipt_monotonic_s"],
                        "sequence": sequence,
                    })
                else:
                    if event.get("event") == "image":
                        sim_ns = event.get("sim_ns")
                        vehicle_id = event.get("vehicle_id")
                        if not isinstance(sim_ns, int) or not isinstance(vehicle_id, int):
                            writer.write({**event, "event": "malformed"})
                            continue
                        if mode_value == "phased":
                            cycle = round(
                                (sim_ns - epoch_ns - offsets[vehicle_id]) / 100_000_000
                            )
                            target_sim_ns = (
                                epoch_ns + cycle * 100_000_000 + offsets[vehicle_id]
                            )
                            if target_sim_ns < observation_start_sim_ns:
                                continue
                        elif sim_ns < observation_start_sim_ns:
                            continue
                    writer.write(event)
            dropped = buffer.take_overflow_count()
            if dropped:
                overflow_total += dropped
                writer.write("queue-overflow", dropped_count=dropped)
            now = monotonic()
            if now - last_flush_at >= flush_interval_s:
                writer.flush()
                last_flush_at = now
            if completion_marker.exists():
                if completion_seen_at is None:
                    completion_seen_at = now
                if (
                    buffer.empty()
                    and last_transport_event_kind == "image"
                    and now - completion_seen_at >= completion_drain_s
                ):
                    completed = True
                    status = 2 if overflow_total else 0
                    break
            sleep(poll_interval_s)
        else:
            raise ProbeFailure("duration_timeout")
    except ProbeFailure as exc:
        writer.write("error", reason=str(exc), message=str(exc))
        writer.flush()
        status = 3
    except Exception as exc:
        writer.write("error", reason="runtime_error", message=f"{type(exc).__name__}: {exc}")
        writer.flush()
        status = 3
    finally:
        if node is not None:
            for owner, topic in reversed(subscribed_topics):
                try:
                    owner.unsubscribe(topic)
                except Exception as exc:
                    writer.write("error", reason="unsubscribe_failed", topic=topic, message=str(exc))
                    status = 3
        callback_references.clear()
        subscription_nodes.clear()
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
    parser.add_argument("--stream-timeout-s", type=float, default=90.0)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.01)
    parser.add_argument("--completion-drain-s", type=float, default=1.0)
    parser.add_argument("--flush-interval-s", type=float, default=0.25)
    parser.add_argument("--warmup-image-count-min", type=int, default=11)
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
            "stream_timeout_s": args.stream_timeout_s,
            "duration_s": args.duration_s,
            "poll_interval_s": args.poll_interval_s,
            "completion_drain_s": args.completion_drain_s,
            "flush_interval_s": args.flush_interval_s,
            "warmup_image_count_min": args.warmup_image_count_min,
            "queue_capacity": args.queue_capacity,
        },
        node_factory=None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
