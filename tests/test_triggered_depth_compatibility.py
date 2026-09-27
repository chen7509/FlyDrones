from copy import deepcopy

from tools.check_triggered_depth_camera_wsl import classify_probe

IMAGE_TOPIC = "/world/trigger_probe/model/camera_model/link/camera_link/sensor/depth/depth_image"
TRIGGER_TOPIC = f"{IMAGE_TOPIC}/trigger"


def accepted_events() -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {
            "event": "start",
            "image_topic": IMAGE_TOPIC,
            "trigger_topic": TRIGGER_TOPIC,
            "renderer_profile": "d3d12-nvidia",
        },
        {
            "event": "renderer",
            "accepted": True,
            "requested_profile": "d3d12-nvidia",
            "egl_renderer": "D3D12 (NVIDIA GeForce RTX)",
        },
        {"event": "pretrigger_window_complete"},
    ]
    for index, sim_ns in enumerate((1_000_000_000, 1_100_000_000, 1_200_000_000)):
        events.extend(
            (
                {
                    "event": "trigger",
                    "trigger_index": index,
                    "topic": TRIGGER_TOPIC,
                    "message_type": "gz.msgs.Boolean",
                    "published": True,
                },
                {
                    "event": "image",
                    "trigger_index": index,
                    "topic": IMAGE_TOPIC,
                    "sim_ns": sim_ns,
                },
            )
        )
    events.extend(
        (
            {"event": "cleanup", "owned_process_released": True, "returncode": 0},
            {"event": "stop"},
        )
    )
    return events


def test_triggered_depth_probe_accepts_complete_three_trigger_sequence():
    result = classify_probe(accepted_events())

    assert result["accepted"] is True
    assert result["reasons"] == []
    assert result["pretrigger_image_count"] == 0
    assert result["images_per_trigger"] == {"0": 1, "1": 1, "2": 1}


def test_triggered_depth_probe_requires_no_pretrigger_image():
    events = accepted_events()
    events.insert(
        2,
        {
            "event": "image",
            "trigger_index": None,
            "topic": IMAGE_TOPIC,
            "sim_ns": 900_000_000,
        },
    )

    result = classify_probe(events)

    assert result["accepted"] is False
    assert "pretrigger_image_observed" in result["reasons"]


def test_triggered_depth_probe_requires_one_new_image_per_trigger():
    events = [
        event
        for event in accepted_events()
        if not (event.get("event") == "image" and event.get("trigger_index") == 1)
    ]

    result = classify_probe(events)

    assert result["accepted"] is False
    assert "image_count_mismatch" in result["reasons"]
    assert result["images_per_trigger"] == {"0": 1, "1": 0, "2": 1}


def test_triggered_depth_probe_rejects_wrong_message_or_topic():
    events = deepcopy(accepted_events())
    trigger = next(event for event in events if event.get("event") == "trigger")
    trigger["topic"] = "/wrong/trigger"
    trigger["message_type"] = "gz.msgs.StringMsg"
    image = next(event for event in events if event.get("event") == "image")
    image["topic"] = "/wrong/image"

    result = classify_probe(events)

    assert result["accepted"] is False
    assert "trigger_topic_mismatch" in result["reasons"]
    assert "trigger_message_type_mismatch" in result["reasons"]
    assert "image_topic_mismatch" in result["reasons"]


def test_probe_cleanup_is_required_for_acceptance():
    events = [event for event in accepted_events() if event.get("event") != "cleanup"]

    result = classify_probe(events)

    assert result["accepted"] is False
    assert "cleanup_not_verified" in result["reasons"]


def test_probe_abnormal_exit_is_reported_without_hiding_resource_release():
    events = accepted_events()
    cleanup = next(event for event in events if event.get("event") == "cleanup")
    cleanup["returncode"] = -11

    result = classify_probe(events)

    assert result["accepted"] is True
    assert result["warnings"] == ["owned_process_abnormal_exit"]
