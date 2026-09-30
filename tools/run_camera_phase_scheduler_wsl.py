"""Publish phased Gazebo camera triggers from simulation clock time."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DEPTH_SUFFIX = "/link/camera_link/sensor/StereoOV7251/depth_image"


class SchedulerFailure(RuntimeError):
    pass


class JsonlWriter:
    def __init__(self, path: Path, monotonic: Callable[[], float]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", encoding="utf-8", buffering=65_536)
        self._monotonic = monotonic
        self._lock = threading.Lock()

    def write(self, event: str, **fields: object) -> None:
        payload = {"event": event, "wall_monotonic_s": self._monotonic(), **fields}
        with self._lock:
            self._handle.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    def flush(self) -> None:
        with self._lock:
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
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


def _positive_float(config: Mapping[str, object], name: str) -> float:
    value = config.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def _publisher_valid(publisher: object) -> bool:
    valid = getattr(publisher, "valid", None)
    return bool(valid()) if callable(valid) else publisher is not None


def _publisher_connected(publisher: object) -> bool:
    connected = getattr(publisher, "has_connections", None)
    return bool(connected()) if callable(connected) else False


def _discover_depth_topics(
    topics: list[str],
    *,
    world: str,
    vehicle_count: int,
    mapper: Callable[..., int | None],
) -> tuple[dict[int, str], list[str]]:
    candidates = [topic for topic in topics if topic.endswith(DEPTH_SUFFIX)]
    reasons: list[str] = []
    if len(candidates) != len(set(candidates)):
        reasons.append("duplicate_depth_topic")
    mapping: dict[int, str] = {}
    for topic in candidates:
        vehicle_id = mapper(topic, world=world, vehicle_count=vehicle_count)
        if vehicle_id is None:
            reasons.append("cross_model_depth_topic")
            continue
        if vehicle_id in mapping:
            reasons.append("duplicate_vehicle_topic")
            continue
        mapping[vehicle_id] = topic
    if sorted(mapping) != list(range(vehicle_count)):
        reasons.append("missing_depth_topic")
    return mapping, list(dict.fromkeys(reasons))


def run_scheduler(
    config: Mapping[str, object],
    *,
    node_factory: Callable[[], object] | None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    output = _path(config, "output")
    ready_marker = _path(config, "ready_marker")
    completion_marker = _path(config, "completion_marker")
    vehicle_count = config.get("vehicle_count")
    if vehicle_count not in (1, 5):
        raise ValueError("vehicle_count must be 1 or 5")
    vehicle_count = int(vehicle_count)
    world = config.get("world", "flydrones_forest")
    if not isinstance(world, str) or not world:
        raise ValueError("world must be a non-empty string")
    topology_timeout_s = _positive_float(config, "topology_timeout_s")
    duration_s = _positive_float(config, "duration_s")
    poll_interval_s = _positive_float(config, "poll_interval_s")
    flush_interval_s = _positive_float(config, "flush_interval_s")
    dispatch_delay_ns = config.get("dispatch_delay_ns", 0)
    if (
        isinstance(dispatch_delay_ns, bool)
        or not isinstance(dispatch_delay_ns, int)
        or dispatch_delay_ns < 0
        or dispatch_delay_ns >= 20_000_000
    ):
        raise ValueError("dispatch_delay_ns must be an integer in [0, 20000000)")
    stop_after = config.get("stop_after_trigger_count")
    if stop_after is not None and (
        isinstance(stop_after, bool) or not isinstance(stop_after, int) or stop_after <= 0
    ):
        raise ValueError("stop_after_trigger_count must be a positive integer or null")
    if config.get("formal") is True and stop_after is not None:
        raise ValueError("formal scheduler config forbids development fault injection")
    if config.get("formal") is True and dispatch_delay_ns != 4_000_000:
        raise ValueError("formal scheduler config requires the frozen 4000000 ns dispatch delay")

    output.parent.mkdir(parents=True, exist_ok=True)
    ready_marker.parent.mkdir(parents=True, exist_ok=True)
    completion_marker.parent.mkdir(parents=True, exist_ok=True)
    ready_marker.unlink(missing_ok=True)

    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from flydrones.camera_phase import (
        TriggerSchedulerState,
        align_epoch_ns,
        depth_topic_vehicle_id,
    )

    if node_factory is None:
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.clock_pb2 import Clock
        from gz.transport13 import Node

        node_factory = Node
        boolean_factory: Callable[[], object] = Boolean
        clock_type: object = Clock
    else:
        def boolean_factory() -> object:
            return SimpleNamespace(data=False)

        clock_type = object

    writer = JsonlWriter(output, monotonic)
    writer.write(
        "start",
        schema="flydrones-camera-scheduler-v1",
        vehicle_count=vehicle_count,
        world=world,
        stop_after_trigger_count=stop_after,
        dispatch_delay_ns=dispatch_delay_ns,
        formal=config.get("formal") is True,
        flush_interval_s=flush_interval_s,
    )
    writer.flush()
    status = 3
    node = None
    subscribed = False
    clock_lock = threading.Lock()
    latest_clock_ns: int | None = None
    clock_sequence = 0
    dispatch_lock = threading.Lock()
    scheduler_state = None
    dispatch_enabled = False
    callback_failure: str | None = None
    callback_status: int | None = None
    publishers: dict[int, object] = {}
    expected_depth_topics: dict[int, str] = {}
    expected_trigger_topics: dict[int, str] = {}
    trigger_count = 0
    started = monotonic()

    def dispatch_clock(sim_ns: int) -> None:
        nonlocal callback_failure, callback_status, dispatch_enabled, trigger_count
        with dispatch_lock:
            if not dispatch_enabled or scheduler_state is None:
                return
            try:
                due = scheduler_state.advance(sim_ns)
                for slot in scheduler_state.last_missed_slots:
                    writer.write(
                        "missed",
                        vehicle_id=slot.vehicle_id,
                        cycle=slot.cycle,
                        planned_sim_ns=slot.planned_sim_ns,
                        observed_sim_ns=sim_ns,
                    )
                for slot in due:
                    message = boolean_factory()
                    message.data = True
                    publishers[slot.vehicle_id].publish(message)
                    writer.write(
                        "trigger",
                        vehicle_id=slot.vehicle_id,
                        cycle=slot.cycle,
                        topic=expected_trigger_topics[slot.vehicle_id],
                        planned_sim_ns=slot.planned_sim_ns,
                        published_sim_ns=slot.published_sim_ns,
                        late_ns=slot.late_ns,
                    )
                    trigger_count += 1
                    if stop_after is not None and trigger_count >= stop_after:
                        writer.write(
                            "fault",
                            reason="development_stop_after_trigger_count",
                            trigger_count=trigger_count,
                        )
                        callback_status = 4
                        dispatch_enabled = False
                        break
            except ValueError as exc:
                writer.write("clock-reset", sim_ns=sim_ns, message=str(exc))
                callback_failure = "clock_reversed"
                dispatch_enabled = False
            except Exception as exc:
                callback_failure = f"{type(exc).__name__}: {exc}"
                dispatch_enabled = False

    def on_clock(message) -> None:
        nonlocal latest_clock_ns, clock_sequence
        sim_ns = int(message.sim.sec) * 1_000_000_000 + int(message.sim.nsec)
        with clock_lock:
            latest_clock_ns = sim_ns
            clock_sequence += 1
        dispatch_clock(sim_ns)

    try:
        node = node_factory()
        if node is None:
            raise SchedulerFailure("node_factory_returned_none")
        if node.subscribe(clock_type, "/clock", on_clock) is False:
            raise SchedulerFailure("clock_subscription_failed")
        subscribed = True

        topology_deadline = monotonic() + topology_timeout_s
        last_topology_signature: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        last_wait_reason = "topology_incomplete"
        while monotonic() < topology_deadline:
            listed_topics = list(node.topic_list())
            depth_topics, topology_reasons = _discover_depth_topics(
                listed_topics,
                world=world,
                vehicle_count=vehicle_count,
                mapper=depth_topic_vehicle_id,
            )
            fatal_reasons = [
                reason
                for reason in topology_reasons
                if reason in {
                    "duplicate_depth_topic",
                    "duplicate_vehicle_topic",
                    "cross_model_depth_topic",
                }
            ]
            trigger_topics = {
                vehicle_id: f"{topic}/trigger" for vehicle_id, topic in depth_topics.items()
            }
            signature = (
                tuple(sorted(depth_topics.values())),
                tuple(topology_reasons),
            )
            if signature != last_topology_signature:
                writer.write(
                    "topology",
                    accepted=not topology_reasons,
                    reasons=topology_reasons,
                    depth_topics=[depth_topics[key] for key in sorted(depth_topics)],
                    trigger_topics=[trigger_topics[key] for key in sorted(trigger_topics)],
                )
                writer.flush()
                last_topology_signature = signature
            if fatal_reasons:
                raise SchedulerFailure(fatal_reasons[0])
            if not topology_reasons:
                if not publishers:
                    for vehicle_id in range(vehicle_count):
                        publisher = node.advertise(trigger_topics[vehicle_id], boolean_factory().__class__)
                        if not _publisher_valid(publisher):
                            raise SchedulerFailure("trigger_publisher_invalid")
                        publishers[vehicle_id] = publisher
                if not all(_publisher_connected(publisher) for publisher in publishers.values()):
                    last_wait_reason = "trigger_connections_incomplete"
                else:
                    with clock_lock:
                        clock_ready = latest_clock_ns is not None
                    if clock_ready:
                        expected_depth_topics = depth_topics
                        expected_trigger_topics = trigger_topics
                        break
                    last_wait_reason = "clock_sample_missing"
            else:
                last_wait_reason = "topology_incomplete"
            if completion_marker.exists():
                raise SchedulerFailure("completion_before_readiness")
            sleep(poll_interval_s)
        else:
            raise SchedulerFailure(last_wait_reason)

        with clock_lock:
            assert latest_clock_ns is not None
            epoch_ns = align_epoch_ns(latest_clock_ns)
        scheduler_state = TriggerSchedulerState(
            vehicle_count=vehicle_count,
            epoch_ns=epoch_ns,
            dispatch_delay_ns=dispatch_delay_ns,
        )
        ready_payload = {
            "schema": "flydrones-camera-scheduler-ready-v1",
            "epoch_ns": epoch_ns,
            "vehicle_count": vehicle_count,
            "dispatch_delay_ns": dispatch_delay_ns,
            "depth_topics": [expected_depth_topics[key] for key in range(vehicle_count)],
            "trigger_topics": [expected_trigger_topics[key] for key in range(vehicle_count)],
        }
        _atomic_json(ready_marker, ready_payload)
        writer.write("ready", **{key: value for key, value in ready_payload.items() if key != "schema"})
        writer.flush()
        with dispatch_lock:
            dispatch_enabled = True
        dispatch_clock(latest_clock_ns)

        last_flush_at = monotonic()
        while monotonic() - started < duration_s:
            if callback_failure is not None:
                raise SchedulerFailure(callback_failure)
            if callback_status is not None:
                status = callback_status
                break
            if completion_marker.exists():
                status = 0
                break
            current_topics, topology_reasons = _discover_depth_topics(
                list(node.topic_list()),
                world=world,
                vehicle_count=vehicle_count,
                mapper=depth_topic_vehicle_id,
            )
            if topology_reasons or current_topics != expected_depth_topics:
                writer.write(
                    "topology",
                    accepted=False,
                    reasons=topology_reasons or ["topology_changed"],
                    depth_topics=[current_topics[key] for key in sorted(current_topics)],
                )
                raise SchedulerFailure("topology_changed")
            if not all(_publisher_connected(publisher) for publisher in publishers.values()):
                raise SchedulerFailure("trigger_connection_lost")

            now = monotonic()
            if now - last_flush_at >= flush_interval_s:
                writer.flush()
                last_flush_at = now
            sleep(poll_interval_s)
        else:
            raise SchedulerFailure("duration_timeout")
    except SchedulerFailure as exc:
        writer.write("error", reason=str(exc), message=str(exc))
        writer.flush()
        status = 3
    except Exception as exc:
        writer.write("error", reason="runtime_error", message=f"{type(exc).__name__}: {exc}")
        writer.flush()
        status = 3
    finally:
        with dispatch_lock:
            dispatch_enabled = False
        if node is not None and subscribed:
            try:
                node.unsubscribe("/clock")
            except Exception as exc:
                writer.write("error", reason="clock_unsubscribe_failed", message=str(exc))
                status = 3
        writer.write("stop", exit_code=status, trigger_count=trigger_count)
        writer.close()
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish phased Gazebo camera triggers from /clock.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready-marker", type=Path, required=True)
    parser.add_argument("--completion-marker", type=Path, required=True)
    parser.add_argument("--vehicle-count", type=int, choices=(1, 5), required=True)
    parser.add_argument("--world", default="flydrones_forest")
    parser.add_argument("--topology-timeout-s", type=float, default=30.0)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.01)
    parser.add_argument("--flush-interval-s", type=float, default=0.25)
    parser.add_argument("--dispatch-delay-ns", type=int, default=0)
    parser.add_argument("--stop-after-trigger-count", type=int)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    return run_scheduler(
        {
            "output": args.output,
            "ready_marker": args.ready_marker,
            "completion_marker": args.completion_marker,
            "vehicle_count": args.vehicle_count,
            "world": args.world,
            "topology_timeout_s": args.topology_timeout_s,
            "duration_s": args.duration_s,
            "poll_interval_s": args.poll_interval_s,
            "flush_interval_s": args.flush_interval_s,
            "dispatch_delay_ns": args.dispatch_delay_ns,
            "stop_after_trigger_count": args.stop_after_trigger_count,
            "formal": args.formal,
        },
        node_factory=None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
