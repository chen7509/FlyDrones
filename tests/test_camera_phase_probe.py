from __future__ import annotations

import gc
import json
import weakref
from pathlib import Path
from types import SimpleNamespace

from flydrones.camera_phase import CameraPhaseThresholds, CameraScheduleMode
from tools.probe_camera_phase_wsl import (
    CallbackBuffer,
    run_probe,
    subscribe_retained,
    summarize_probe_log,
)

EPOCH_NS = 1_000_000_000
WORLD = "flydrones_forest"


def depth_topic(vehicle_id: int) -> str:
    return (
        f"/world/{WORLD}/model/x500_depth_fly_{vehicle_id}"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
    )


def stamp_message(sim_ns: int, *, width: int = 160, height: int = 120):
    return SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(
                sec=sim_ns // 1_000_000_000,
                nsec=sim_ns % 1_000_000_000,
            )
        ),
        width=width,
        height=height,
    )


class FakeNode:
    def __init__(self, topics: list[str], callbacks: dict[str, object] | None = None) -> None:
        self.topics = list(topics)
        self.callbacks = callbacks if callbacks is not None else {}
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def topic_list(self) -> list[str]:
        return list(self.topics)

    def subscribe(self, _message_type, topic: str, callback) -> bool:
        self.callbacks[topic] = callback
        self.subscribed.append(topic)
        return True

    def unsubscribe(self, topic: str) -> bool:
        self.unsubscribed.append(topic)
        return True

    def emit_clock(self, sim_ns: int) -> None:
        self.callbacks["/clock"](
            SimpleNamespace(
                sim=SimpleNamespace(
                    sec=sim_ns // 1_000_000_000,
                    nsec=sim_ns % 1_000_000_000,
                )
            )
        )


class WeakCallbackNode:
    def __init__(self) -> None:
        self.callback: weakref.ReferenceType | None = None

    def subscribe(self, _message_type, _topic: str, callback) -> bool:
        self.callback = weakref.ref(callback)
        return True


def test_subscribe_retained_keeps_callback_alive_for_weak_transport_binding():
    node = WeakCallbackNode()
    callback_references: list[object] = []

    def callback(_message) -> None:
        return None

    assert subscribe_retained(node, callback_references, object, "/clock", callback) is True
    del callback
    gc.collect()

    assert node.callback is not None
    assert node.callback() is callback_references[0]


class FakeRuntime:
    def __init__(
        self,
        node: FakeNode,
        selected: dict[str, object],
        *,
        phase_error_ns: int = 0,
        overflow_batch: bool = False,
        force_overflow: bool = False,
        delay_final_image_until_after_completion: bool = False,
        warmup_vehicle_ids: tuple[int, ...] | None = None,
    ) -> None:
        self.node = node
        self.selected = selected
        self.phase_error_ns = phase_error_ns
        self.overflow_batch = overflow_batch
        self.force_overflow = force_overflow
        self.delay_final_image_until_after_completion = delay_final_image_until_after_completion
        self.warmup_vehicle_ids = warmup_vehicle_ids
        self.pending_final: tuple[int, int] | None = None
        self.now = 0.0
        self.sent_clock = False
        self.sent_warmup = False
        self.sent_stream = False

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration
        if self.pending_final is not None:
            vehicle_id, actual = self.pending_final
            self.node.emit_clock(actual)
            self.node.callbacks[depth_topic(vehicle_id)](stamp_message(actual))
            self.pending_final = None
            self.sent_stream = True
            return
        if "/clock" in self.node.callbacks and not self.sent_clock:
            self.node.emit_clock(EPOCH_NS)
            self.sent_clock = True
            return
        mode = CameraScheduleMode(str(self.selected["mode"]))
        vehicle_count = int(self.selected["vehicle_count"])
        image_callbacks = [depth_topic(vehicle_id) for vehicle_id in range(vehicle_count)]
        expected_callbacks = list(image_callbacks)
        if mode is CameraScheduleMode.PHASED:
            expected_callbacks.extend(f"{topic}/trigger" for topic in image_callbacks)
        if all(topic in self.node.callbacks for topic in expected_callbacks) and not self.sent_warmup:
            selected_ids = self.warmup_vehicle_ids or tuple(range(vehicle_count))
            for sample_index in range(int(self.selected["warmup_image_count_min"])):
                for vehicle_id in selected_ids:
                    planned = (
                        EPOCH_NS
                        + sample_index * 100_000_000
                        + vehicle_id * 20_000_000
                    )
                    if mode is CameraScheduleMode.PHASED:
                        self.node.emit_clock(planned)
                        self.node.callbacks[f"{depth_topic(vehicle_id)}/trigger"](
                            SimpleNamespace(data=True)
                        )
                    self.node.emit_clock(planned)
                    self.node.callbacks[depth_topic(vehicle_id)](stamp_message(planned))
            self.sent_warmup = True
            return
        ready = Path(self.selected["ready_marker"])
        if not ready.exists() or self.sent_stream:
            return
        ready_payload = json.loads(ready.read_text(encoding="utf-8"))
        observation_start_ns = int(ready_payload["observation_start_sim_ns"])
        for cycle in range(101 if self.force_overflow else 11):
            for vehicle_id in range(vehicle_count):
                planned = observation_start_ns + cycle * 100_000_000 + vehicle_id * 20_000_000
                if mode is CameraScheduleMode.PHASED:
                    self.node.emit_clock(planned)
                    self.node.callbacks[f"{depth_topic(vehicle_id)}/trigger"](
                        SimpleNamespace(data=True)
                    )
                actual = planned + self.phase_error_ns
                if (
                    self.delay_final_image_until_after_completion
                    and cycle == 10
                    and vehicle_id == vehicle_count - 1
                ):
                    self.pending_final = (vehicle_id, actual)
                    Path(self.selected["completion_marker"]).touch()
                    return
                self.node.emit_clock(actual)
                self.node.callbacks[depth_topic(vehicle_id)](stamp_message(actual))
                if not self.overflow_batch:
                    break
            if not self.overflow_batch and cycle == 0:
                break
        self.sent_stream = True
        Path(self.selected["completion_marker"]).touch()


def config(
    tmp_path: Path,
    *,
    mode: CameraScheduleMode,
    vehicle_count: int = 1,
    queue_capacity: int = 2048,
) -> dict[str, object]:
    result: dict[str, object] = {
        "output": tmp_path / "camera-phase.jsonl",
        "ready_marker": tmp_path / "camera-phase-ready.json",
        "summary": tmp_path / "camera-phase-summary.json",
        "completion_marker": tmp_path / "trial-complete.marker",
        "mode": mode.value,
        "vehicle_count": vehicle_count,
        "world": WORLD,
        "topology_timeout_s": 0.2,
        "stream_timeout_s": 0.2,
        "duration_s": 2.0,
        "poll_interval_s": 0.01,
        "flush_interval_s": 0.25,
        "warmup_image_count_min": 11,
        "queue_capacity": queue_capacity,
    }
    if mode is CameraScheduleMode.PHASED:
        scheduler_ready = tmp_path / "camera-scheduler-ready.json"
        scheduler_ready.parent.mkdir(parents=True, exist_ok=True)
        scheduler_ready.write_text(
            json.dumps(
                {
                    "schema": "flydrones-camera-scheduler-ready-v1",
                    "epoch_ns": EPOCH_NS,
                    "vehicle_count": vehicle_count,
                    "trigger_topics": [f"{depth_topic(index)}/trigger" for index in range(vehicle_count)],
                }
            ),
            encoding="utf-8",
        )
        result["scheduler_ready_marker"] = scheduler_ready
    return result


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run_fake(
    tmp_path: Path,
    *,
    mode: CameraScheduleMode,
    vehicle_count: int = 1,
    queue_capacity: int = 2048,
    overflow_batch: bool = True,
    force_overflow: bool = False,
    delay_final_image_until_after_completion: bool = False,
    warmup_vehicle_ids: tuple[int, ...] | None = None,
) -> tuple[int, FakeNode, dict[str, object], list[dict[str, object]]]:
    selected = config(
        tmp_path,
        mode=mode,
        vehicle_count=vehicle_count,
        queue_capacity=queue_capacity,
    )
    node = FakeNode([depth_topic(index) for index in range(vehicle_count)])
    runtime = FakeRuntime(
        node,
        selected,
        overflow_batch=overflow_batch,
        force_overflow=force_overflow,
        delay_final_image_until_after_completion=delay_final_image_until_after_completion,
        warmup_vehicle_ids=warmup_vehicle_ids,
    )
    status = run_probe(
        selected,
        node_factory=lambda: node,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
    )
    return status, node, selected, read_events(Path(selected["output"]))


def test_callback_buffer_enqueues_only_and_retains_header_receipt_and_sequence(tmp_path):
    now = iter((1.25, 1.50))
    buffer = CallbackBuffer(capacity=8, monotonic=lambda: next(now))
    buffer.clock_callback(SimpleNamespace(sim=SimpleNamespace(sec=2, nsec=40)))
    callback = buffer.image_callback(3, depth_topic(3))

    callback(stamp_message(2_000_000_008))

    assert list(tmp_path.iterdir()) == []
    assert buffer.drain() == [
        {
            "event": "image",
            "vehicle_id": 3,
            "topic": depth_topic(3),
            "sim_ns": 2_000_000_008,
            "receipt_sim_ns": 2_000_000_040,
            "receipt_monotonic_s": 1.5,
            "sequence": 0,
            "width": 160,
            "height": 120,
        }
    ]


def test_probe_subscribes_same_images_in_both_modes_and_triggers_only_when_phased(tmp_path):
    _, simultaneous_node, _, _ = run_fake(
        tmp_path / "simultaneous",
        mode=CameraScheduleMode.SIMULTANEOUS,
        overflow_batch=False,
    )
    _, phased_node, _, _ = run_fake(
        tmp_path / "phased",
        mode=CameraScheduleMode.PHASED,
        overflow_batch=False,
    )

    assert depth_topic(0) in simultaneous_node.callbacks
    assert depth_topic(0) in phased_node.callbacks
    assert f"{depth_topic(0)}/trigger" not in simultaneous_node.callbacks
    assert f"{depth_topic(0)}/trigger" in phased_node.callbacks


def test_probe_uses_one_dedicated_subscription_node_per_vehicle(tmp_path):
    selected = config(tmp_path, mode=CameraScheduleMode.PHASED, vehicle_count=5)
    topics = [depth_topic(index) for index in range(5)]
    shared_callbacks: dict[str, object] = {}
    runtime_node = FakeNode(topics, shared_callbacks)
    created_nodes: list[FakeNode] = []

    def node_factory() -> FakeNode:
        node = FakeNode(topics, shared_callbacks)
        created_nodes.append(node)
        return node

    runtime = FakeRuntime(runtime_node, selected, overflow_batch=True)
    status = run_probe(
        selected,
        node_factory=node_factory,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
    )

    assert status == 0
    assert len(created_nodes) == 6
    assert created_nodes[0].subscribed == ["/clock"]
    for vehicle_id, node in enumerate(created_nodes[1:]):
        assert node.subscribed == [
            depth_topic(vehicle_id),
            f"{depth_topic(vehicle_id)}/trigger",
        ]


def test_probe_retains_actual_image_and_trigger_events_and_writes_summary(tmp_path):
    status, _, selected, events = run_fake(
        tmp_path,
        mode=CameraScheduleMode.PHASED,
    )

    assert status == 0
    image = next(event for event in events if event["event"] == "image")
    trigger = next(event for event in events if event["event"] == "trigger")
    ready = json.loads(Path(selected["ready_marker"]).read_text(encoding="utf-8"))
    assert ready["warmup_image_counts"] == {"0": 11}
    assert ready["depth_observations"][depth_topic(0)] == {
        "width": 160,
        "height": 120,
        "frequency_hz": 10.0,
        "message_count": 11,
    }
    assert image["sim_ns"] == ready["observation_start_sim_ns"]
    assert image["receipt_sim_ns"] == ready["observation_start_sim_ns"]
    assert image["receipt_monotonic_s"] > 0
    assert image["sequence"] == 11
    assert image["vehicle_id"] == 0
    assert trigger["planned_sim_ns"] == ready["observation_start_sim_ns"]
    summary = json.loads(Path(selected["summary"]).read_text(encoding="utf-8"))
    assert summary["accepted"] is True
    assert summary["vehicles"]["0"]["image_count"] == 11


def test_probe_requires_eleven_actual_images_from_every_vehicle_before_ready(tmp_path):
    status, _, selected, events = run_fake(
        tmp_path,
        mode=CameraScheduleMode.PHASED,
        vehicle_count=5,
        warmup_vehicle_ids=(0, 1, 2, 3),
    )

    assert status != 0
    assert not Path(selected["ready_marker"]).exists()
    assert any(
        event["event"] == "error" and event["reason"] == "stream_readiness_timeout"
        for event in events
    )


def test_probe_drains_delayed_final_image_after_completion_marker(tmp_path):
    status, _, selected, _ = run_fake(
        tmp_path,
        mode=CameraScheduleMode.PHASED,
        delay_final_image_until_after_completion=True,
    )

    assert status == 0
    summary = json.loads(Path(selected["summary"]).read_text(encoding="utf-8"))
    assert summary["accepted"] is True
    assert summary["unmatched_trigger_count"] == 0
    assert summary["vehicles"]["0"]["image_count"] == 11


def test_probe_queue_overflow_is_logged_and_rejects_evidence(tmp_path):
    status, _, selected, events = run_fake(
        tmp_path,
        mode=CameraScheduleMode.SIMULTANEOUS,
        vehicle_count=5,
        queue_capacity=500,
        force_overflow=True,
    )

    assert status != 0
    assert any(event["event"] == "queue-overflow" for event in events)
    summary = json.loads(Path(selected["summary"]).read_text(encoding="utf-8"))
    assert summary["accepted"] is False
    assert "callback_queue_overflow" in summary["reasons"]


def test_summary_loader_preserves_and_rejects_malformed_jsonl_and_missing_stop(tmp_path):
    log = tmp_path / "camera-phase.jsonl"
    original = (
        b'{"event":"start","epoch_ns":1000000000}\n'
        b'{"event":"topology","depth_topics":[]}\n'
        b'{"event":"ready"}\n'
        b'{broken-json\n'
    )
    log.write_bytes(original)

    summary = summarize_probe_log(
        log,
        mode=CameraScheduleMode.SIMULTANEOUS,
        vehicle_count=1,
        thresholds=CameraPhaseThresholds(),
    )

    assert log.read_bytes() == original
    assert summary["accepted"] is False
    assert "malformed_jsonl" in summary["reasons"]
    assert "lifecycle_stop_missing" in summary["reasons"]


def test_summary_loader_rejects_cross_model_and_repeated_image_stamp(tmp_path):
    log = tmp_path / "camera-phase.jsonl"
    events = [
        {"event": "start", "epoch_ns": EPOCH_NS},
        {"event": "topology", "depth_topics": [depth_topic(0)]},
        {"event": "ready"},
        {
            "event": "image",
            "vehicle_id": 0,
            "topic": depth_topic(0).replace("x500_depth_fly_0", "x500_depth_fly_1"),
            "sim_ns": EPOCH_NS,
            "sequence": 0,
        },
        {
            "event": "image",
            "vehicle_id": 0,
            "topic": depth_topic(0),
            "sim_ns": EPOCH_NS,
            "sequence": 1,
        },
        {"event": "stop"},
    ]
    log.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    summary = summarize_probe_log(
        log,
        mode=CameraScheduleMode.SIMULTANEOUS,
        vehicle_count=1,
        thresholds=CameraPhaseThresholds(),
    )

    assert "cross_model_topic" in summary["reasons"]
    assert "duplicate_image" in summary["reasons"]
