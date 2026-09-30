import gc
import weakref

import pytest

from flydrones.takeoff_readiness import TakeoffFailureReason, classify_takeoff_chain, summarize_actuator_link
from tools.probe_gazebo_actuator_link import actuator_motor_topics, subscribe_retained


class WeakCallbackNode:
    def __init__(self) -> None:
        self.callback: weakref.ReferenceType | None = None

    def subscribe(self, _message_type, _topic, callback) -> bool:
        self.callback = weakref.ref(callback)
        return True


def test_subscription_callback_is_owned_until_explicit_cleanup():
    node = WeakCallbackNode()
    callback_references: list[object] = []

    def callback(_message) -> None:
        return None

    assert subscribe_retained(node, callback_references, object, "/motor", callback) is True
    del callback
    gc.collect()

    assert node.callback is not None
    assert node.callback() is callback_references[0]


def _events(fleet_size=1, *, altitude_gain=0.8, motor_peak=0.9, include_stop=True):
    topics = actuator_motor_topics(fleet_size)
    events = [{"event": "start", "monotonic_s": 1.0, "models": list(topics)}]
    timestamp = 1.1
    for model, topic in topics.items():
        events.extend([
            {
                "event": "topology",
                "monotonic_s": timestamp,
                "model": model,
                "topic": topic,
                "subscription_ok": True,
            },
            {
                "event": "motor-command",
                "monotonic_s": timestamp + 0.1,
                "model": model,
                "topic": topic,
                "velocities": [motor_peak] * 4,
            },
            {
                "event": "odometry",
                "monotonic_s": timestamp + 0.2,
                "model": model,
                "position_m": [0.0, float(model.rsplit("_", 1)[1]), 0.0],
            },
            {
                "event": "odometry",
                "monotonic_s": timestamp + 0.3,
                "model": model,
                "position_m": [0.0, float(model.rsplit("_", 1)[1]), altitude_gain],
            },
        ])
        timestamp += 0.5
    if include_stop:
        events.append({"event": "stop", "monotonic_s": timestamp})
    return events


@pytest.mark.parametrize("fleet_size", [1, 5])
def test_exact_per_model_motor_topics_and_supported_fleet_sizes(fleet_size):
    topics = actuator_motor_topics(fleet_size)

    assert topics == {
        f"x500_depth_fly_{vehicle_id}": f"/x500_depth_fly_{vehicle_id}/command/motor_speed"
        for vehicle_id in range(fleet_size)
    }
    summary = summarize_actuator_link(_events(fleet_size), fleet_size=fleet_size)
    assert summary["accepted"]
    assert len(summary["vehicles"]) == fleet_size


def test_unsupported_fleet_size_is_rejected():
    with pytest.raises(ValueError, match="one or five"):
        actuator_motor_topics(2)


def test_cross_model_motor_topic_is_rejected():
    events = _events(5)
    motor = next(event for event in events if event["event"] == "motor-command" and event["model"].endswith("_0"))
    motor["topic"] = "/x500_depth_fly_1/command/motor_speed"

    summary = summarize_actuator_link(events, fleet_size=5)

    assert not summary["accepted"]
    assert summary["errors"]["cross_model_events"] == 1
    assert not summary["vehicles"]["x500_depth_fly_0"]["motor_command_received"]


def test_out_of_order_and_malformed_events_fail_closed_without_crashing():
    events = _events(1)
    events.insert(2, {"event": "motor-command", "monotonic_s": 0.5, "model": "x500_depth_fly_0"})
    events.insert(3, {"event": "odometry", "monotonic_s": 1.25, "model": "unknown", "position_m": "bad"})

    summary = summarize_actuator_link(events, fleet_size=1)

    assert not summary["accepted"]
    assert summary["errors"]["out_of_order_events"] >= 1
    assert summary["errors"]["malformed_events"] >= 1


def test_stationary_odometry_despite_motor_command_is_identified():
    summary = summarize_actuator_link(_events(1, altitude_gain=0.03), fleet_size=1)
    vehicle = summary["vehicles"]["x500_depth_fly_0"]

    assert summary["accepted"]
    assert vehicle["motor_command_received"]
    assert not vehicle["physical_climb"]
    assert vehicle["reason"] == TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value


def test_physical_movement_with_stationary_estimator_is_classified_separately():
    gazebo = summarize_actuator_link(_events(1, altitude_gain=0.8), fleet_size=1)["vehicles"]["x500_depth_fly_0"]
    result = classify_takeoff_chain(
        {
            "accepted": True,
            "terminal_stage": "mission-ready",
            "maximum_altitude_gain_m": 0.0,
        },
        {"actuator_output_present": True, "estimator_altitude_gain_m": 0.0},
        gazebo,
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert result["reason"] == TakeoffFailureReason.ESTIMATOR_RESPONSE_TIMEOUT.value
    assert result["gazebo_physical_climb"]
    assert not result["estimator_climb"]


def test_missing_stop_event_preserves_data_but_rejects_clean_close():
    summary = summarize_actuator_link(_events(1, include_stop=False), fleet_size=1)

    assert not summary["accepted"]
    assert not summary["closed_cleanly"]
    assert summary["vehicles"]["x500_depth_fly_0"]["odometry_samples"] == 2
