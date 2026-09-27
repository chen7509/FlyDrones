from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from flydrones.camera_phase import CameraPhaseThresholds, CameraScheduleMode
from tools.probe_camera_phase_wsl import (
    CallbackBuffer,
    run_probe,
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
    def __init__(self, topics: list[str]) -> None:
        self.topics = list(topics)
        self.callbacks: dict[str, object] = {}
        self.unsubscribed: list[str] = []

    def topic_list(self) -> list[str]:
        return list(self.topics)

    def subscribe(self, _message_type, topic: str, callback) -> bool:
        self.callbacks[topic] = callback
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


class FakeRuntime:
    def __init__(
        self,
        node: FakeNode,
        selected: dict[str, object],
        *,
        phase_error_ns: int = 0,
        overflow_batch: bool = False,
        force_overflow: bool = False,
    ) -> None:
        self.node = node
        self.selected = selected
        self.phase_error_ns = phase_error_ns
        self.overflow_batch = overflow_batch
        self.force_overflow = force_overflow
        self.now = 0.0
        self.sent_clock = False
        self.sent_stream = False

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration
        if "/clock" in self.node.callbacks and not self.sent_clock:
            self.node.emit_clock(EPOCH_NS)
            self.sent_clock = True
            return
        ready = Path(self.selected["ready_marker"])
        if not ready.exists() or self.sent_stream:
            return
        mode = CameraScheduleMode(str(self.selected["mode"]))
        vehicle_count = int(self.selected["vehicle_count"])
        for cycle in range(101 if self.force_overflow else 11):
            for vehicle_id in range(vehicle_count):
                planned = EPOCH_NS + cycle * 100_000_000 + vehicle_id * 20_000_000
                if mode is CameraScheduleMode.PHASED:
                    self.node.emit_clock(planned)
                    self.node.callbacks[f"{depth_topic(vehicle_id)}/trigger"](
                        SimpleNamespace(data=True)
                    )
                actual = planned + self.phase_error_ns
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
        "duration_s": 2.0,
        "poll_interval_s": 0.01,
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


def test_probe_retains_actual_image_and_trigger_events_and_writes_summary(tmp_path):
    status, _, selected, events = run_fake(
        tmp_path,
        mode=CameraScheduleMode.PHASED,
    )

    assert status == 0
    image = next(event for event in events if event["event"] == "image")
    trigger = next(event for event in events if event["event"] == "trigger")
    assert image["sim_ns"] == EPOCH_NS
    assert image["receipt_sim_ns"] == EPOCH_NS
    assert image["receipt_monotonic_s"] > 0
    assert image["sequence"] == 0
    assert image["vehicle_id"] == 0
    assert trigger["planned_sim_ns"] == EPOCH_NS
    summary = json.loads(Path(selected["summary"]).read_text(encoding="utf-8"))
    assert summary["accepted"] is True
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
