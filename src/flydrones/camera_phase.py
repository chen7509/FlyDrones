"""Pure simulation-time scheduling and camera-phase evidence algorithms."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

PERIOD_NS = 100_000_000
PHASE_STEP_NS = 20_000_000
OUTPUT_PHASE_DISPATCH_DELAY_NS = 4_000_000
SIMULTANEOUS_BIN_NS = 10_000_000
DEFAULT_WORLD = "flydrones_forest"


class CameraScheduleMode(str, Enum):
    SIMULTANEOUS = "simultaneous"
    PHASED = "phased"


@dataclass(frozen=True)
class CameraPhaseThresholds:
    minimum_frequency_hz: float = 9.5
    maximum_frequency_hz: float = 10.5
    maximum_phase_error_p95_ns: int = 8_000_000
    maximum_spacing_median_error_ns: int = 8_000_000
    period_ns: int = PERIOD_NS
    simultaneous_bin_ns: int = SIMULTANEOUS_BIN_NS


@dataclass(frozen=True)
class TriggerSlot:
    vehicle_id: int
    cycle: int
    planned_sim_ns: int
    published_sim_ns: int | None
    late_ns: int | None


def camera_phase_offsets_ns(vehicle_count: int) -> tuple[int, ...]:
    if vehicle_count == 1:
        return (0,)
    if vehicle_count == 5:
        return tuple(index * PHASE_STEP_NS for index in range(vehicle_count))
    raise ValueError("vehicle_count must be 1 or 5")


def align_epoch_ns(sim_ns: int) -> int:
    if isinstance(sim_ns, bool) or not isinstance(sim_ns, int) or sim_ns < 0:
        raise ValueError("simulation time must be a non-negative integer")
    return ((sim_ns + PERIOD_NS - 1) // PERIOD_NS) * PERIOD_NS


@dataclass
class TriggerSchedulerState:
    vehicle_count: int
    epoch_ns: int
    dispatch_delay_ns: int = 0
    last_missed_slots: tuple[TriggerSlot, ...] = field(default=(), init=False)
    _next_slot_index: int = field(default=0, init=False, repr=False)
    _last_sim_ns: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        camera_phase_offsets_ns(self.vehicle_count)
        if isinstance(self.epoch_ns, bool) or not isinstance(self.epoch_ns, int) or self.epoch_ns < 0:
            raise ValueError("epoch_ns must be a non-negative integer")
        if (
            isinstance(self.dispatch_delay_ns, bool)
            or not isinstance(self.dispatch_delay_ns, int)
            or self.dispatch_delay_ns < 0
            or self.dispatch_delay_ns >= PHASE_STEP_NS
        ):
            raise ValueError("dispatch_delay_ns must be an integer in [0, 20000000)")

    def slot_for(
        self,
        *,
        vehicle_id: int,
        cycle: int,
        observed_sim_ns: int | None,
    ) -> TriggerSlot:
        offsets = camera_phase_offsets_ns(self.vehicle_count)
        if vehicle_id < 0 or vehicle_id >= self.vehicle_count or cycle < 0:
            raise ValueError("invalid vehicle_id or cycle")
        planned = self.epoch_ns + cycle * PERIOD_NS + offsets[vehicle_id]
        return TriggerSlot(
            vehicle_id=vehicle_id,
            cycle=cycle,
            planned_sim_ns=planned,
            published_sim_ns=observed_sim_ns,
            late_ns=None if observed_sim_ns is None else observed_sim_ns - planned,
        )

    def _slot_at_index(self, index: int, observed_sim_ns: int | None) -> TriggerSlot:
        cycle, vehicle_id = divmod(index, self.vehicle_count)
        return self.slot_for(
            vehicle_id=vehicle_id,
            cycle=cycle,
            observed_sim_ns=observed_sim_ns,
        )

    def advance(self, sim_ns: int) -> tuple[TriggerSlot, ...]:
        if isinstance(sim_ns, bool) or not isinstance(sim_ns, int) or sim_ns < 0:
            raise ValueError("simulation time must be a non-negative integer")
        if self._last_sim_ns is not None and sim_ns < self._last_sim_ns:
            raise ValueError("simulation time reversed")
        self.last_missed_slots = ()
        if self._last_sim_ns == sim_ns:
            return ()
        self._last_sim_ns = sim_ns

        due: list[TriggerSlot] = []
        while True:
            slot = self._slot_at_index(self._next_slot_index, observed_sim_ns=None)
            if slot.planned_sim_ns + self.dispatch_delay_ns > sim_ns:
                break
            due.append(slot)
            self._next_slot_index += 1
        if not due:
            return ()
        self.last_missed_slots = tuple(due[:-1])
        latest = due[-1]
        return (
            self.slot_for(
                vehicle_id=latest.vehicle_id,
                cycle=latest.cycle,
                observed_sim_ns=sim_ns,
            ),
        )


def depth_topic_vehicle_id(topic: str, *, world: str, vehicle_count: int) -> int | None:
    if not isinstance(topic, str) or not isinstance(world, str):
        return None
    try:
        camera_phase_offsets_ns(vehicle_count)
    except ValueError:
        return None
    pattern = re.compile(
        rf"^/world/{re.escape(world)}/model/x500_depth_fly_(0|[1-9][0-9]*)"
        r"/link/camera_link/sensor/StereoOV7251/depth_image$"
    )
    match = pattern.fullmatch(topic)
    if match is None:
        return None
    vehicle_id = int(match.group(1))
    return vehicle_id if vehicle_id < vehicle_count else None


def _percentile(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return int(ordered[lower])
    fraction = position - lower
    return int(round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction))


def _median_int(values: Sequence[int]) -> int:
    return int(round(statistics.median(values))) if values else 0


def _signed_circular_delta(value_ns: int, target_ns: int, period_ns: int) -> int:
    return int((value_ns - target_ns + period_ns // 2) % period_ns - period_ns // 2)


def _event_count(events: Sequence[Mapping[str, object]], name: str) -> int:
    return sum(event.get("event") == name for event in events)


def _valid_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def summarize_camera_phase(
    events: Sequence[Mapping[str, object]],
    *,
    mode: CameraScheduleMode,
    vehicle_count: int,
    thresholds: CameraPhaseThresholds,
) -> dict[str, object]:
    mode = CameraScheduleMode(mode)
    offsets = camera_phase_offsets_ns(vehicle_count)
    reasons: list[str] = []
    normalized: list[Mapping[str, object]] = []
    for event in events:
        if not isinstance(event, Mapping) or not isinstance(event.get("event"), str):
            reasons.append("malformed_event")
            continue
        normalized.append(event)

    for name in ("start", "topology", "ready", "stop"):
        if _event_count(normalized, name) != 1:
            reasons.append(f"lifecycle_{name}_missing")

    starts = [event for event in normalized if event.get("event") == "start"]
    epoch_ns = starts[0].get("epoch_ns") if len(starts) == 1 else None
    if not _valid_int(epoch_ns):
        ready_events = [event for event in normalized if event.get("event") == "ready"]
        epoch_ns = ready_events[0].get("epoch_ns") if len(ready_events) == 1 else None
    if not _valid_int(epoch_ns) or int(epoch_ns) < 0:
        reasons.append("malformed_event")
        epoch_ns = 0
    epoch_ns = int(epoch_ns)

    topologies = [event for event in normalized if event.get("event") == "topology"]
    if len(topologies) == 1:
        topics = topologies[0].get("depth_topics")
        mapped = (
            [depth_topic_vehicle_id(topic, world=DEFAULT_WORLD, vehicle_count=vehicle_count) for topic in topics]
            if isinstance(topics, list) and all(isinstance(topic, str) for topic in topics)
            else []
        )
        if sorted(item for item in mapped if item is not None) != list(range(vehicle_count)):
            reasons.append("topology_mismatch")

    images: dict[int, list[dict[str, int | str | None]]] = {
        vehicle_id: [] for vehicle_id in range(vehicle_count)
    }
    triggers: dict[int, list[dict[str, int]]] = {
        vehicle_id: [] for vehicle_id in range(vehicle_count)
    }
    malformed = False
    cross_model_errors = 0
    missed_trigger_count = 0
    queue_overflow_count = 0
    for event in normalized:
        event_name = event.get("event")
        if event_name == "image":
            vehicle_id = event.get("vehicle_id")
            sim_ns = event.get("sim_ns")
            topic = event.get("topic")
            sequence = event.get("sequence")
            if (
                not _valid_int(vehicle_id)
                or int(vehicle_id) not in images
                or not _valid_int(sim_ns)
                or not isinstance(topic, str)
                or (sequence is not None and not _valid_int(sequence))
            ):
                malformed = True
                continue
            vehicle_id = int(vehicle_id)
            mapped_id = depth_topic_vehicle_id(topic, world=DEFAULT_WORLD, vehicle_count=vehicle_count)
            if mapped_id != vehicle_id:
                cross_model_errors += 1
            images[vehicle_id].append({
                "sim_ns": int(sim_ns),
                "sequence": int(sequence) if sequence is not None else None,
                "topic": topic,
            })
        elif event_name == "trigger":
            vehicle_id = event.get("vehicle_id")
            cycle = event.get("cycle")
            planned = event.get("planned_sim_ns")
            published = event.get("published_sim_ns")
            if (
                not _valid_int(vehicle_id)
                or int(vehicle_id) not in triggers
                or not _valid_int(cycle)
                or int(cycle) < 0
                or not _valid_int(planned)
                or not _valid_int(published)
            ):
                malformed = True
                continue
            triggers[int(vehicle_id)].append({
                "cycle": int(cycle),
                "planned_sim_ns": int(planned),
                "published_sim_ns": int(published),
            })
        elif event_name == "missed":
            missed_trigger_count += 1
        elif event_name == "queue-overflow":
            dropped = event.get("dropped_count")
            if not _valid_int(dropped) or int(dropped) <= 0:
                malformed = True
            else:
                queue_overflow_count += int(dropped)
    if malformed:
        reasons.append("malformed_event")
    if cross_model_errors:
        reasons.append("cross_model_topic")
    if missed_trigger_count:
        reasons.append("missed_trigger")
    if queue_overflow_count:
        reasons.append("callback_queue_overflow")

    duplicate_image_count = 0
    duplicate_trigger_count = 0
    for vehicle_id in range(vehicle_count):
        image_stamps = [int(image["sim_ns"]) for image in images[vehicle_id]]
        image_sequences = [
            int(image["sequence"])
            for image in images[vehicle_id]
            if isinstance(image["sequence"], int)
        ]
        duplicate_image_count += max(
            len(image_stamps) - len(set(image_stamps)),
            len(image_sequences) - len(set(image_sequences)),
        )
        trigger_keys = [
            (trigger["cycle"], trigger["planned_sim_ns"])
            for trigger in triggers[vehicle_id]
        ]
        duplicate_trigger_count += len(trigger_keys) - len(set(trigger_keys))
    if duplicate_image_count:
        reasons.append("duplicate_image")
    if duplicate_trigger_count:
        reasons.append("duplicate_trigger")

    unmatched_trigger_count = 0
    unmatched_image_count = 0
    if mode is CameraScheduleMode.PHASED:
        for vehicle_id in range(vehicle_count):
            trigger_count = len(triggers[vehicle_id])
            image_count = len(images[vehicle_id])
            unmatched_trigger_count += max(0, trigger_count - image_count)
            unmatched_image_count += max(0, image_count - trigger_count)
            for trigger in triggers[vehicle_id]:
                expected = epoch_ns + trigger["cycle"] * thresholds.period_ns + offsets[vehicle_id]
                if trigger["planned_sim_ns"] != expected:
                    reasons.append("target_offsets_invalid")
        if unmatched_trigger_count:
            reasons.append("unmatched_trigger")
        if unmatched_image_count:
            reasons.append("unmatched_image")

    vehicle_summaries: dict[str, dict[str, object]] = {}
    phase_centers: dict[int, int] = {}
    frequency_epsilon = 1e-5
    for vehicle_id in range(vehicle_count):
        vehicle_images = sorted(images[vehicle_id], key=lambda item: int(item["sim_ns"]))
        timestamps = [int(item["sim_ns"]) for item in vehicle_images]
        intervals = [current - previous for previous, current in zip(timestamps, timestamps[1:])]
        frequency = (
            (len(timestamps) - 1) * 1_000_000_000 / (timestamps[-1] - timestamps[0])
            if len(timestamps) >= 2 and timestamps[-1] > timestamps[0]
            else 0.0
        )
        if not (
            thresholds.minimum_frequency_hz - frequency_epsilon
            <= frequency
            <= thresholds.maximum_frequency_hz + frequency_epsilon
        ):
            reasons.append("image_frequency_out_of_range")

        phases = [int((timestamp - epoch_ns) % thresholds.period_ns) for timestamp in timestamps]
        phase_errors: list[int] = []
        if mode is CameraScheduleMode.PHASED:
            target = offsets[vehicle_id]
            phase_errors = [
                abs(_signed_circular_delta(phase, target, thresholds.period_ns))
                for phase in phases
            ]
            signed_errors = [
                _signed_circular_delta(phase, target, thresholds.period_ns)
                for phase in phases
            ]
            phase_centers[vehicle_id] = (target + _median_int(signed_errors)) % thresholds.period_ns
            if _percentile(phase_errors, 0.95) > thresholds.maximum_phase_error_p95_ns:
                reasons.append("phase_error_p95_exceeded")
        else:
            phase_centers[vehicle_id] = _median_int(phases)
        vehicle_summaries[str(vehicle_id)] = {
            "image_count": len(timestamps),
            "mean_frequency_hz": frequency,
            "interval_p50_ns": _percentile(intervals, 0.50),
            "interval_p95_ns": _percentile(intervals, 0.95),
            "interval_p99_ns": _percentile(intervals, 0.99),
            "interval_max_ns": max(intervals, default=0),
            "phase_median_ns": phase_centers[vehicle_id],
            "phase_error_p50_ns": _percentile(phase_errors, 0.50),
            "phase_error_p95_ns": _percentile(phase_errors, 0.95),
            "phase_error_max_ns": max(phase_errors, default=0),
        }

    spacing_errors: dict[str, int] = {}
    if mode is CameraScheduleMode.PHASED and vehicle_count > 1:
        for vehicle_id in range(vehicle_count):
            next_vehicle = (vehicle_id + 1) % vehicle_count
            actual_spacing = (
                phase_centers[next_vehicle] - phase_centers[vehicle_id]
            ) % thresholds.period_ns
            target_spacing = (offsets[next_vehicle] - offsets[vehicle_id]) % thresholds.period_ns
            error = abs(_signed_circular_delta(actual_spacing, target_spacing, thresholds.period_ns))
            spacing_errors[f"{vehicle_id}-{next_vehicle}"] = error
        if any(error > thresholds.maximum_spacing_median_error_ns for error in spacing_errors.values()):
            reasons.append("spacing_median_error_exceeded")

    simultaneous_bins: dict[int, set[int]] = {}
    for vehicle_id, vehicle_images in images.items():
        for image in vehicle_images:
            bin_id = int(image["sim_ns"]) // thresholds.simultaneous_bin_ns
            simultaneous_bins.setdefault(bin_id, set()).add(vehicle_id)

    deduplicated_reasons = list(dict.fromkeys(reasons))
    return {
        "schema": "flydrones-camera-phase-summary-v1",
        "mode": mode.value,
        "vehicle_count": vehicle_count,
        "accepted": not deduplicated_reasons,
        "reasons": deduplicated_reasons,
        "epoch_ns": epoch_ns,
        "target_offsets_ns": list(offsets),
        "vehicles": vehicle_summaries,
        "adjacent_spacing_median_error_ns": spacing_errors,
        "max_simultaneous_cameras_10ms": max(
            (len(vehicle_ids) for vehicle_ids in simultaneous_bins.values()),
            default=0,
        ),
        "missed_trigger_count": missed_trigger_count,
        "queue_overflow_count": queue_overflow_count,
        "duplicate_trigger_count": duplicate_trigger_count,
        "duplicate_image_count": duplicate_image_count,
        "unmatched_trigger_count": unmatched_trigger_count,
        "unmatched_image_count": unmatched_image_count,
        "cross_model_error_count": cross_model_errors,
    }


_CANONICAL_VEHICLE_FIELDS = (
    "image_count",
    "mean_frequency_hz",
    "interval_p50_ns",
    "interval_p95_ns",
    "interval_p99_ns",
    "interval_max_ns",
    "phase_median_ns",
    "phase_error_p50_ns",
    "phase_error_p95_ns",
    "phase_error_max_ns",
)
_CANONICAL_INTEGRITY_FIELDS = (
    "missed_trigger_count",
    "queue_overflow_count",
    "duplicate_trigger_count",
    "duplicate_image_count",
    "unmatched_trigger_count",
    "unmatched_image_count",
    "cross_model_error_count",
)


def canonical_phase_score_fields(summary: Mapping[str, object]) -> dict[str, object]:
    """Return the complete deterministic subset used to compare phase scoring."""
    if not isinstance(summary, Mapping):
        raise ValueError("summary must be a mapping")
    if summary.get("schema") != "flydrones-camera-phase-summary-v1":
        raise ValueError("camera phase summary schema is invalid")

    mode = summary.get("mode")
    vehicle_count = summary.get("vehicle_count")
    accepted = summary.get("accepted")
    reasons = summary.get("reasons")
    epoch_ns = summary.get("epoch_ns")
    offsets = summary.get("target_offsets_ns")
    vehicles = summary.get("vehicles")
    spacing = summary.get("adjacent_spacing_median_error_ns")
    simultaneous = summary.get("max_simultaneous_cameras_10ms")
    if mode not in {item.value for item in CameraScheduleMode}:
        raise ValueError("mode is missing or invalid")
    if not _valid_int(vehicle_count) or int(vehicle_count) not in (1, 5):
        raise ValueError("vehicle_count is missing or invalid")
    if not isinstance(accepted, bool):
        raise ValueError("accepted is missing or invalid")
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        raise ValueError("reasons is missing or invalid")
    if not _valid_int(epoch_ns) or int(epoch_ns) < 0:
        raise ValueError("epoch_ns is missing or invalid")
    if (
        not isinstance(offsets, list)
        or len(offsets) != int(vehicle_count)
        or not all(_valid_int(offset) for offset in offsets)
    ):
        raise ValueError("target_offsets_ns is missing or invalid")
    if not isinstance(vehicles, Mapping):
        raise ValueError("vehicles is missing or invalid")
    if set(vehicles) != {str(index) for index in range(int(vehicle_count))}:
        raise ValueError("vehicles identities are incomplete")

    canonical_vehicles: dict[str, dict[str, object]] = {}
    for vehicle_id in range(int(vehicle_count)):
        key = str(vehicle_id)
        vehicle = vehicles[key]
        if not isinstance(vehicle, Mapping):
            raise ValueError(f"vehicle {key} summary is invalid")
        canonical_vehicle: dict[str, object] = {}
        for field_name in _CANONICAL_VEHICLE_FIELDS:
            if field_name not in vehicle:
                raise ValueError(f"vehicle {key} missing {field_name}")
            value = vehicle[field_name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"vehicle {key} {field_name} is invalid")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"vehicle {key} {field_name} is non-finite")
            canonical_vehicle[field_name] = value
        canonical_vehicles[key] = canonical_vehicle

    if not isinstance(spacing, Mapping) or not all(
        isinstance(key, str) and _valid_int(value) for key, value in spacing.items()
    ):
        raise ValueError("adjacent_spacing_median_error_ns is missing or invalid")
    if not _valid_int(simultaneous):
        raise ValueError("max_simultaneous_cameras_10ms is missing or invalid")

    integrity: dict[str, int] = {}
    for field_name in _CANONICAL_INTEGRITY_FIELDS:
        value = summary.get(field_name)
        if not _valid_int(value) or int(value) < 0:
            raise ValueError(f"{field_name} is missing or invalid")
        integrity[field_name] = int(value)

    return {
        "mode": mode,
        "vehicle_count": int(vehicle_count),
        "accepted": accepted,
        "reasons": list(reasons),
        "epoch_ns": int(epoch_ns),
        "target_offsets_ns": [int(offset) for offset in offsets],
        "vehicles": canonical_vehicles,
        "adjacent_spacing_median_error_ns": {
            key: int(spacing[key]) for key in sorted(spacing)
        },
        "max_simultaneous_cameras_10ms": int(simultaneous),
        **integrity,
    }
