from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.run_camera_phase_scheduler_wsl import run_scheduler

EPOCH_NS = 1_000_000_000
WORLD = "flydrones_forest"


def depth_topic(vehicle_id: int, *, world: str = WORLD, suffix: str | None = None) -> str:
    model_id = str(vehicle_id) if suffix is None else suffix
    return (
        f"/world/{world}/model/x500_depth_fly_{model_id}"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
    )


class FakePublisher:
    def __init__(self, topic: str, *, connected: bool, fail_publish: bool = False) -> None:
        self.topic = topic
        self.connected = connected
        self.fail_publish = fail_publish
        self.messages: list[bool] = []

    def valid(self) -> bool:
        return True

    def has_connections(self) -> bool:
        return self.connected

    def publish(self, message) -> None:
        if self.fail_publish:
            raise RuntimeError("injected publisher failure")
        self.messages.append(bool(message.data))


class FakeNode:
    def __init__(
        self,
        topics: list[str],
        *,
        trigger_connections: bool = True,
        subscribe_ok: bool = True,
        fail_publish_vehicle: int | None = None,
    ) -> None:
        self.topics = list(topics)
        self.trigger_connections = trigger_connections
        self.subscribe_ok = subscribe_ok
        self.fail_publish_vehicle = fail_publish_vehicle
        self.clock_callback = None
        self.publishers: dict[str, FakePublisher] = {}
        self.unsubscribed: list[str] = []

    def topic_list(self) -> list[str]:
        return list(self.topics)

    def subscribe(self, _message_type, topic: str, callback) -> bool:
        if not self.subscribe_ok:
            return False
        assert topic == "/clock"
        self.clock_callback = callback
        return True

    def unsubscribe(self, topic: str) -> bool:
        self.unsubscribed.append(topic)
        return True

    def advertise(self, topic: str, _message_type) -> FakePublisher:
        vehicle_id = int(topic.split("x500_depth_fly_", 1)[1].split("/", 1)[0])
        publisher = FakePublisher(
            topic,
            connected=self.trigger_connections,
            fail_publish=vehicle_id == self.fail_publish_vehicle,
        )
        self.publishers[topic] = publisher
        return publisher

    def emit_clock(self, sim_ns: int) -> None:
        assert self.clock_callback is not None
        self.clock_callback(
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
        clocks: list[int],
        completion_marker: Path,
        *,
        complete_after_publishes: int | None,
    ) -> None:
        self.node = node
        self.clocks = list(clocks)
        self.completion_marker = completion_marker
        self.complete_after_publishes = complete_after_publishes
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration
        if self.clocks:
            self.node.emit_clock(self.clocks.pop(0))
        published = sum(len(publisher.messages) for publisher in self.node.publishers.values())
        if self.complete_after_publishes is not None and published >= self.complete_after_publishes:
            self.completion_marker.touch()


def config(tmp_path: Path, *, vehicle_count: int = 5, **updates: object) -> dict[str, object]:
    result: dict[str, object] = {
        "output": tmp_path / "camera-scheduler.jsonl",
        "ready_marker": tmp_path / "camera-scheduler-ready.json",
        "completion_marker": tmp_path / "trial-complete.marker",
        "vehicle_count": vehicle_count,
        "world": WORLD,
        "topology_timeout_s": 0.2,
        "duration_s": 2.0,
        "poll_interval_s": 0.01,
        "stop_after_trigger_count": None,
        "formal": False,
    }
    result.update(updates)
    return result


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run_fake(
    tmp_path: Path,
    *,
    node: FakeNode,
    clocks: list[int],
    complete_after_publishes: int | None,
    scheduler_config: dict[str, object] | None = None,
) -> tuple[int, list[dict[str, object]]]:
    selected = scheduler_config or config(tmp_path)
    runtime = FakeRuntime(
        node,
        clocks,
        Path(selected["completion_marker"]),
        complete_after_publishes=complete_after_publishes,
    )
    status = run_scheduler(
        selected,
        node_factory=lambda: node,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
    )
    return status, read_events(Path(selected["output"]))


def test_scheduler_requires_exact_topology_clock_and_trigger_connections(tmp_path):
    node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)])

    status, events = run_fake(
        tmp_path,
        node=node,
        clocks=[EPOCH_NS + offset for offset in range(0, 104_000_001, 4_000_000)],
        complete_after_publishes=6,
    )

    assert status == 0
    assert Path(config(tmp_path)["ready_marker"]).exists()
    assert [event["event"] for event in events][0] == "start"
    assert {"topology", "ready", "trigger", "stop"}.issubset(
        event["event"] for event in events
    )
    ready = next(event for event in events if event["event"] == "ready")
    assert ready["epoch_ns"] == EPOCH_NS
    assert ready["depth_topics"] == [depth_topic(vehicle_id) for vehicle_id in range(5)]
    assert ready["trigger_topics"] == [f"{depth_topic(vehicle_id)}/trigger" for vehicle_id in range(5)]
    assert node.unsubscribed == ["/clock"]


@pytest.mark.parametrize(
    "topics,reason",
    (
        ([depth_topic(0)] * 2 + [depth_topic(i) for i in range(1, 5)], "duplicate_depth_topic"),
        ([depth_topic(i) for i in range(4)] + [depth_topic(4, world="old_world")], "cross_model_depth_topic"),
        ([depth_topic(i) for i in range(4)] + [depth_topic(4, suffix="04")], "cross_model_depth_topic"),
    ),
)
def test_scheduler_rejects_duplicate_stale_or_cross_model_topics(tmp_path, topics, reason):
    status, events = run_fake(
        tmp_path,
        node=FakeNode(topics),
        clocks=[EPOCH_NS],
        complete_after_publishes=None,
    )

    assert status != 0
    assert not Path(config(tmp_path)["ready_marker"]).exists()
    topology = next(event for event in events if event["event"] == "topology")
    assert topology["accepted"] is False
    assert reason in topology["reasons"]
    assert events[-1]["event"] == "stop"


def test_scheduler_does_not_become_ready_without_trigger_subscribers(tmp_path):
    status, events = run_fake(
        tmp_path,
        node=FakeNode(
            [depth_topic(vehicle_id) for vehicle_id in range(5)],
            trigger_connections=False,
        ),
        clocks=[EPOCH_NS],
        complete_after_publishes=None,
    )

    assert status != 0
    assert not Path(config(tmp_path)["ready_marker"]).exists()
    assert any(
        event["event"] == "error" and event["reason"] == "trigger_connections_incomplete"
        for event in events
    )


def test_scheduler_maps_each_trigger_publisher_to_the_same_vehicle(tmp_path):
    node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)])

    status, _ = run_fake(
        tmp_path,
        node=node,
        clocks=[EPOCH_NS + offset for offset in range(0, 84_000_001, 4_000_000)],
        complete_after_publishes=5,
    )

    assert status == 0
    assert list(node.publishers) == [f"{depth_topic(vehicle_id)}/trigger" for vehicle_id in range(5)]
    assert all(publisher.messages == [True] for publisher in node.publishers.values())


def test_scheduler_pause_4ms_steps_and_wrap_publish_each_slot_once(tmp_path):
    node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)])
    clocks = [EPOCH_NS, EPOCH_NS]
    clocks.extend(EPOCH_NS + offset for offset in range(4_000_000, 104_000_001, 4_000_000))

    status, events = run_fake(
        tmp_path,
        node=node,
        clocks=clocks,
        complete_after_publishes=6,
    )

    assert status == 0
    triggers = [event for event in events if event["event"] == "trigger"]
    assert [(event["vehicle_id"], event["cycle"]) for event in triggers] == [
        (0, 0),
        (1, 0),
        (2, 0),
        (3, 0),
        (4, 0),
        (0, 1),
    ]
    assert not [event for event in events if event["event"] == "missed"]


def test_scheduler_jump_logs_misses_without_catchup_batch(tmp_path):
    node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)])

    status, events = run_fake(
        tmp_path,
        node=node,
        clocks=[EPOCH_NS, EPOCH_NS + 64_000_000],
        complete_after_publishes=2,
    )

    assert status == 0
    assert [event["vehicle_id"] for event in events if event["event"] == "trigger"] == [0, 3]
    assert [event["vehicle_id"] for event in events if event["event"] == "missed"] == [1, 2]


def test_scheduler_clock_reversal_fails_closed_and_preserves_log(tmp_path):
    node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)])

    status, events = run_fake(
        tmp_path,
        node=node,
        clocks=[EPOCH_NS, EPOCH_NS + 20_000_000, EPOCH_NS + 10_000_000],
        complete_after_publishes=None,
    )

    assert status != 0
    assert any(event["event"] == "clock-reset" for event in events)
    assert events[-1]["event"] == "stop"


def test_scheduler_clock_or_publisher_failure_returns_nonzero_with_stop(tmp_path):
    clock_node = FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)], subscribe_ok=False)
    clock_status, clock_events = run_fake(
        tmp_path / "clock",
        node=clock_node,
        clocks=[],
        complete_after_publishes=None,
        scheduler_config=config(tmp_path / "clock"),
    )
    publisher_node = FakeNode(
        [depth_topic(vehicle_id) for vehicle_id in range(5)],
        fail_publish_vehicle=0,
    )
    publisher_status, publisher_events = run_fake(
        tmp_path / "publisher",
        node=publisher_node,
        clocks=[EPOCH_NS],
        complete_after_publishes=None,
        scheduler_config=config(tmp_path / "publisher"),
    )

    assert clock_status != 0
    assert clock_events[-1]["event"] == "stop"
    assert publisher_status != 0
    assert any("publisher failure" in event.get("message", "") for event in publisher_events)
    assert publisher_events[-1]["event"] == "stop"


def test_development_fault_stops_after_requested_trigger_count(tmp_path):
    selected = config(tmp_path, stop_after_trigger_count=2)
    status, events = run_fake(
        tmp_path,
        node=FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)]),
        clocks=[EPOCH_NS, EPOCH_NS + 20_000_000],
        complete_after_publishes=None,
        scheduler_config=selected,
    )

    assert status != 0
    assert events[0]["stop_after_trigger_count"] == 2
    assert [event["event"] for event in events].count("trigger") == 2
    assert any(event["event"] == "fault" for event in events)


def test_formal_config_forbids_development_fault_injection(tmp_path):
    with pytest.raises(ValueError, match="formal"):
        run_scheduler(
            config(tmp_path, formal=True, stop_after_trigger_count=1),
            node_factory=lambda: FakeNode([depth_topic(vehicle_id) for vehicle_id in range(5)]),
            monotonic=lambda: 0.0,
            sleep=lambda _duration: None,
        )
