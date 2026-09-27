from __future__ import annotations

from copy import deepcopy

import pytest

from flydrones.camera_phase import (
    CameraPhaseThresholds,
    CameraScheduleMode,
    TriggerSchedulerState,
    align_epoch_ns,
    camera_phase_offsets_ns,
    canonical_phase_score_fields,
    depth_topic_vehicle_id,
    summarize_camera_phase,
)

PERIOD_NS = 100_000_000
STEP_NS = 4_000_000
EPOCH_NS = 1_000_000_000
WORLD = "flydrones_forest"


def depth_topic(vehicle_id: int, *, model_id: str | None = None) -> str:
    suffix = str(vehicle_id) if model_id is None else model_id
    return (
        f"/world/{WORLD}/model/x500_depth_fly_{suffix}"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
    )


def lifecycle_events(vehicle_count: int) -> list[dict[str, object]]:
    return [
        {"event": "start", "epoch_ns": EPOCH_NS, "wall_monotonic_ns": 1},
        {
            "event": "topology",
            "depth_topics": [depth_topic(vehicle_id) for vehicle_id in range(vehicle_count)],
            "wall_monotonic_ns": 2,
        },
        {"event": "ready", "wall_monotonic_ns": 3},
        {"event": "stop", "wall_monotonic_ns": 4},
    ]


def phased_events(*, phase_errors_ns: dict[int, int] | None = None) -> list[dict[str, object]]:
    errors = phase_errors_ns or {}
    events = lifecycle_events(5)
    for cycle in range(11):
        for vehicle_id, offset_ns in enumerate(camera_phase_offsets_ns(5)):
            planned_ns = EPOCH_NS + cycle * PERIOD_NS + offset_ns
            events.extend(
                (
                    {
                        "event": "trigger",
                        "vehicle_id": vehicle_id,
                        "cycle": cycle,
                        "planned_sim_ns": planned_ns,
                        "published_sim_ns": planned_ns,
                    },
                    {
                        "event": "image",
                        "vehicle_id": vehicle_id,
                        "topic": depth_topic(vehicle_id),
                        "sim_ns": planned_ns + errors.get(vehicle_id, 0),
                        "sequence": cycle,
                    },
                )
            )
    return events


def simultaneous_events(
    *,
    vehicle_count: int = 5,
    timestamps: tuple[int, ...] | None = None,
) -> list[dict[str, object]]:
    stamps = timestamps or tuple(EPOCH_NS + cycle * PERIOD_NS for cycle in range(11))
    events = lifecycle_events(vehicle_count)
    for vehicle_id in range(vehicle_count):
        for sequence, sim_ns in enumerate(stamps):
            events.append(
                {
                    "event": "image",
                    "vehicle_id": vehicle_id,
                    "topic": depth_topic(vehicle_id),
                    "sim_ns": sim_ns,
                    "sequence": sequence,
                }
            )
    return events


def summarize(
    events: list[dict[str, object]],
    *,
    mode: CameraScheduleMode = CameraScheduleMode.PHASED,
    vehicle_count: int = 5,
) -> dict[str, object]:
    return summarize_camera_phase(
        events,
        mode=mode,
        vehicle_count=vehicle_count,
        thresholds=CameraPhaseThresholds(),
    )


def test_camera_phase_offsets_are_exact_for_one_and_five_vehicles():
    assert camera_phase_offsets_ns(1) == (0,)
    assert camera_phase_offsets_ns(5) == (
        0,
        20_000_000,
        40_000_000,
        60_000_000,
        80_000_000,
    )
    with pytest.raises(ValueError, match="vehicle_count"):
        camera_phase_offsets_ns(2)


def test_epoch_alignment_never_precedes_current_simulation_time():
    assert align_epoch_ns(0) == 0
    assert align_epoch_ns(EPOCH_NS) == EPOCH_NS
    assert align_epoch_ns(EPOCH_NS + 1) == EPOCH_NS + PERIOD_NS
    assert align_epoch_ns(EPOCH_NS + PERIOD_NS - 1) == EPOCH_NS + PERIOD_NS
    with pytest.raises(ValueError, match="non-negative"):
        align_epoch_ns(-1)


def test_scheduler_emits_exact_phases_and_repeats_every_100ms():
    scheduler = TriggerSchedulerState(vehicle_count=5, epoch_ns=EPOCH_NS)

    assert scheduler.advance(EPOCH_NS - STEP_NS) == ()
    first = scheduler.advance(EPOCH_NS)
    second = scheduler.advance(EPOCH_NS + 20_000_000)
    next_cycle = scheduler.advance(EPOCH_NS + PERIOD_NS)

    assert [(slot.vehicle_id, slot.cycle, slot.planned_sim_ns) for slot in first + second] == [
        (0, 0, EPOCH_NS),
        (1, 0, EPOCH_NS + 20_000_000),
    ]
    assert [(slot.vehicle_id, slot.cycle, slot.planned_sim_ns) for slot in next_cycle] == [
        (0, 1, EPOCH_NS + PERIOD_NS)
    ]


def test_scheduler_handles_4ms_steps_pause_and_duplicate_clocks_without_duplicates():
    scheduler = TriggerSchedulerState(vehicle_count=5, epoch_ns=EPOCH_NS)
    emitted = []
    for sim_ns in range(EPOCH_NS - STEP_NS, EPOCH_NS + 24_000_000, STEP_NS):
        emitted.extend(scheduler.advance(sim_ns))
        assert scheduler.advance(sim_ns) == ()

    assert [(slot.vehicle_id, slot.planned_sim_ns) for slot in emitted] == [
        (0, EPOCH_NS),
        (1, EPOCH_NS + 20_000_000),
    ]
    assert scheduler.last_missed_slots == ()


def test_scheduler_dispatch_delay_preserves_image_target_and_records_publish_lateness():
    scheduler = TriggerSchedulerState(
        vehicle_count=1,
        epoch_ns=EPOCH_NS,
        dispatch_delay_ns=STEP_NS,
    )

    assert scheduler.advance(EPOCH_NS) == ()
    assert scheduler.advance(EPOCH_NS + STEP_NS) == (
        scheduler.slot_for(
            vehicle_id=0,
            cycle=0,
            observed_sim_ns=EPOCH_NS + STEP_NS,
        ),
    )
    slot = scheduler.advance(EPOCH_NS + PERIOD_NS + STEP_NS)[0]
    assert slot.planned_sim_ns == EPOCH_NS + PERIOD_NS
    assert slot.published_sim_ns == EPOCH_NS + PERIOD_NS + STEP_NS
    assert slot.late_ns == STEP_NS


def test_scheduler_rejects_time_reversal_without_advancing_state():
    scheduler = TriggerSchedulerState(vehicle_count=1, epoch_ns=EPOCH_NS)
    assert len(scheduler.advance(EPOCH_NS)) == 1

    with pytest.raises(ValueError, match="reversed"):
        scheduler.advance(EPOCH_NS - 1)

    assert scheduler.advance(EPOCH_NS + PERIOD_NS) == (
        scheduler.slot_for(vehicle_id=0, cycle=1, observed_sim_ns=EPOCH_NS + PERIOD_NS),
    )


def test_scheduler_jump_records_misses_and_publishes_only_latest_due_slot():
    scheduler = TriggerSchedulerState(vehicle_count=5, epoch_ns=EPOCH_NS)
    assert len(scheduler.advance(EPOCH_NS)) == 1

    published = scheduler.advance(EPOCH_NS + 64_000_000)

    assert [(slot.vehicle_id, slot.planned_sim_ns) for slot in published] == [
        (3, EPOCH_NS + 60_000_000)
    ]
    assert [(slot.vehicle_id, slot.planned_sim_ns) for slot in scheduler.last_missed_slots] == [
        (1, EPOCH_NS + 20_000_000),
        (2, EPOCH_NS + 40_000_000),
    ]
    assert all(slot.published_sim_ns is None for slot in scheduler.last_missed_slots)


def test_depth_topic_vehicle_mapping_is_exact_and_scoped():
    assert depth_topic_vehicle_id(depth_topic(0), world=WORLD, vehicle_count=5) == 0
    assert depth_topic_vehicle_id(depth_topic(4), world=WORLD, vehicle_count=5) == 4
    assert depth_topic_vehicle_id(depth_topic(0, model_id="00"), world=WORLD, vehicle_count=5) is None
    assert depth_topic_vehicle_id(depth_topic(5), world=WORLD, vehicle_count=5) is None
    assert depth_topic_vehicle_id(depth_topic(0).replace(WORLD, "other"), world=WORLD, vehicle_count=5) is None
    assert depth_topic_vehicle_id(depth_topic(0).replace("x500_depth_fly", "other"), world=WORLD, vehicle_count=5) is None


def test_phased_summary_accepts_unordered_events_at_8ms_boundaries_and_wrap():
    events = phased_events(phase_errors_ns={vehicle_id: 8_000_000 for vehicle_id in range(5)})

    result = summarize(list(reversed(events)))

    assert result["accepted"] is True
    assert result["reasons"] == []
    assert result["target_offsets_ns"] == [0, 20_000_000, 40_000_000, 60_000_000, 80_000_000]
    assert all(
        vehicle["phase_error_p95_ns"] == 8_000_000
        for vehicle in result["vehicles"].values()
    )
    assert max(result["adjacent_spacing_median_error_ns"].values()) == 0


def test_phased_summary_matches_one_step_delayed_images_across_period_wrap():
    result = summarize(phased_events(phase_errors_ns={4: STEP_NS}))

    assert result["accepted"] is True
    assert result["vehicles"]["4"]["phase_error_p95_ns"] == STEP_NS
    assert result["unmatched_trigger_count"] == 0
    assert result["unmatched_image_count"] == 0


def test_phased_summary_uses_image_header_time_instead_of_receipt_time():
    events = phased_events(phase_errors_ns={0: 8_000_000})
    for event in events:
        if event.get("event") == "image":
            event["receipt_sim_ns"] = int(event["sim_ns"]) + 40_000_000

    result = summarize(events)

    assert result["accepted"] is True
    assert result["vehicles"]["0"]["phase_error_p95_ns"] == 8_000_000


@pytest.mark.parametrize(
    "frequency_hz,delta_ns",
    ((9.5, round(1_000_000_000 / 9.5)), (10.5, round(1_000_000_000 / 10.5))),
)
def test_simultaneous_summary_accepts_frequency_boundaries(frequency_hz: float, delta_ns: int):
    events = simultaneous_events(vehicle_count=1, timestamps=(EPOCH_NS, EPOCH_NS + delta_ns))

    result = summarize(events, mode=CameraScheduleMode.SIMULTANEOUS, vehicle_count=1)

    assert result["accepted"] is True
    assert result["vehicles"]["0"]["mean_frequency_hz"] == pytest.approx(frequency_hz, abs=1e-5)


def test_simultaneous_summary_reports_maximum_cameras_in_same_10ms_bin():
    result = summarize(
        simultaneous_events(),
        mode=CameraScheduleMode.SIMULTANEOUS,
    )

    assert result["accepted"] is True
    assert result["max_simultaneous_cameras_10ms"] == 5


def test_summary_rejects_phase_and_spacing_beyond_frozen_boundaries():
    phase_result = summarize(phased_events(phase_errors_ns={0: 8_000_001}))
    spacing_result = summarize(phased_events(phase_errors_ns={0: 8_000_000, 1: -8_000_001}))

    assert "phase_error_p95_exceeded" in phase_result["reasons"]
    assert "spacing_median_error_exceeded" in spacing_result["reasons"]


def test_summary_reports_missing_duplicate_and_unmatched_evidence():
    events = phased_events()
    removed_image = next(
        event
        for event in events
        if event.get("event") == "image" and event.get("vehicle_id") == 2
    )
    events.remove(removed_image)
    duplicate_trigger = deepcopy(next(event for event in events if event.get("event") == "trigger"))
    events.append(duplicate_trigger)
    duplicate_image = deepcopy(next(event for event in events if event.get("event") == "image"))
    events.append(duplicate_image)
    events.append(
        {
            "event": "image",
            "vehicle_id": 3,
            "topic": depth_topic(3),
            "sim_ns": EPOCH_NS + 9_999_999_999,
            "sequence": 999,
        }
    )
    events.append({"event": "missed", "vehicle_id": 4, "planned_sim_ns": EPOCH_NS})

    result = summarize(events)

    assert result["accepted"] is False
    assert {
        "missed_trigger",
        "duplicate_trigger",
        "duplicate_image",
        "unmatched_trigger",
        "unmatched_image",
    }.issubset(result["reasons"])


def test_summary_rejects_repeated_image_stamp_even_with_a_new_sequence():
    events = phased_events()
    image = deepcopy(next(event for event in events if event.get("event") == "image"))
    image["sequence"] = 999
    events.append(image)

    result = summarize(events)

    assert result["accepted"] is False
    assert "duplicate_image" in result["reasons"]


def test_summary_rejects_callback_queue_overflow_event():
    events = phased_events()
    events.append({"event": "queue-overflow", "dropped_count": 1})

    result = summarize(events)

    assert result["accepted"] is False
    assert "callback_queue_overflow" in result["reasons"]


def test_summary_rejects_cross_model_topic_and_malformed_events():
    events = phased_events()
    image = next(event for event in events if event.get("event") == "image")
    image["topic"] = depth_topic(1)
    events.append({"event": "image", "vehicle_id": "bad"})

    result = summarize(events)

    assert result["accepted"] is False
    assert "cross_model_topic" in result["reasons"]
    assert "malformed_event" in result["reasons"]


@pytest.mark.parametrize(
    "missing_event,reason",
    (
        ("start", "lifecycle_start_missing"),
        ("topology", "lifecycle_topology_missing"),
        ("ready", "lifecycle_ready_missing"),
        ("stop", "lifecycle_stop_missing"),
    ),
)
def test_summary_requires_each_lifecycle_event(missing_event: str, reason: str):
    events = [event for event in phased_events() if event.get("event") != missing_event]

    result = summarize(events)

    assert result["accepted"] is False
    assert reason in result["reasons"]


def test_canonical_phase_score_fields_pin_every_scored_value():
    canonical = canonical_phase_score_fields(summarize(phased_events()))

    assert canonical == {
        "mode": "phased",
        "vehicle_count": 5,
        "accepted": True,
        "reasons": [],
        "epoch_ns": EPOCH_NS,
        "target_offsets_ns": [0, 20_000_000, 40_000_000, 60_000_000, 80_000_000],
        "vehicles": {
            str(vehicle_id): {
                "image_count": 11,
                "mean_frequency_hz": 10.0,
                "interval_p50_ns": PERIOD_NS,
                "interval_p95_ns": PERIOD_NS,
                "interval_p99_ns": PERIOD_NS,
                "interval_max_ns": PERIOD_NS,
                "phase_median_ns": vehicle_id * 20_000_000,
                "phase_error_p50_ns": 0,
                "phase_error_p95_ns": 0,
                "phase_error_max_ns": 0,
            }
            for vehicle_id in range(5)
        },
        "adjacent_spacing_median_error_ns": {
            "0-1": 0,
            "1-2": 0,
            "2-3": 0,
            "3-4": 0,
            "4-0": 0,
        },
        "max_simultaneous_cameras_10ms": 1,
        "missed_trigger_count": 0,
        "queue_overflow_count": 0,
        "duplicate_trigger_count": 0,
        "duplicate_image_count": 0,
        "unmatched_trigger_count": 0,
        "unmatched_image_count": 0,
        "cross_model_error_count": 0,
    }


def test_canonical_phase_score_fields_reject_wrong_schema_and_missing_values():
    summary = summarize(phased_events())
    summary["schema"] = "other"
    with pytest.raises(ValueError, match="schema"):
        canonical_phase_score_fields(summary)

    summary = summarize(phased_events())
    del summary["unmatched_image_count"]
    with pytest.raises(ValueError, match="unmatched_image_count"):
        canonical_phase_score_fields(summary)
