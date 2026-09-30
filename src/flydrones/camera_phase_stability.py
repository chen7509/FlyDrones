"""Frozen schedules and fail-closed scoring for camera phase experiments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any

from flydrones.renderer_stability import score_renderer_trial


@dataclass(frozen=True)
class CameraPhaseRun:
    name: str
    camera_schedule_mode: str
    fleet_size: int
    renderer_profile: str = "d3d12-nvidia"
    pair_id: int | None = None
    pair_position: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def smoke_schedule() -> tuple[CameraPhaseRun, ...]:
    return (
        CameraPhaseRun("camera-phase-smoke-phased-single", "phased", 1),
        CameraPhaseRun("camera-phase-smoke-simultaneous-five", "simultaneous", 5),
        CameraPhaseRun("camera-phase-smoke-phased-five", "phased", 5),
    )


def _canonical_formal_schedule() -> tuple[CameraPhaseRun, ...]:
    pairs = (
        ("simultaneous", "phased"),
        ("phased", "simultaneous"),
        ("simultaneous", "phased"),
        ("phased", "simultaneous"),
        ("simultaneous", "phased"),
    )
    return tuple(
        CameraPhaseRun(
            name=f"camera-phase-pair-{pair_id}-{position}-{mode}",
            camera_schedule_mode=mode,
            fleet_size=5,
            pair_id=pair_id,
            pair_position=position,
        )
        for pair_id, pair in enumerate(pairs, start=1)
        for position, mode in enumerate(pair, start=1)
    )


def formal_schedule(config: Mapping[str, object]) -> tuple[CameraPhaseRun, ...]:
    expected = _canonical_formal_schedule()
    configured = config.get("formal_schedule")
    if configured is not None and configured != [item.as_dict() for item in expected]:
        raise ValueError("formal camera phase schedule differs from the preregistered sequence")
    return expected


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _threshold(config: Mapping[str, object], key: str, default: float) -> float:
    value = _finite(_mapping(config.get("thresholds")).get(key))
    return default if value is None else value


def score_phase_trial(
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    config: Mapping[str, object],
) -> dict[str, object]:
    """Apply existing operational gates plus camera-mode evidence gates."""
    base = score_renderer_trial(manifest, summary)
    failures = list(base["failures"])
    mode = manifest.get("camera_schedule_mode")
    if mode not in {"simultaneous", "phased"}:
        failures.append("camera_schedule_mode_invalid")
    if base.get("renderer_profile") != "d3d12-nvidia":
        failures.append("renderer_not_d3d12_nvidia")
    if manifest.get("camera_scheduler_stop_after_trigger_count") is not None:
        failures.append("formal_auxiliary_fault_injection")
    if manifest.get("camera_phase_probe_closed_cleanly") is not True:
        failures.append("camera_phase_probe_not_clean")
    if manifest.get("camera_scheduler_closed_cleanly") is not True:
        failures.append("camera_scheduler_not_clean")
    model_evidence = _mapping(manifest.get("camera_model_evidence"))
    if (
        model_evidence.get("schema") != "flydrones-camera-model-phase-v1"
        or model_evidence.get("mode") != mode
    ):
        failures.append("camera_model_evidence_invalid")

    phase = summary.get("camera_phase")
    if not isinstance(phase, Mapping):
        failures.append("camera_phase_summary_missing")
        phase = {}
    elif phase.get("schema") != "flydrones-camera-phase-summary-v1":
        failures.append("camera_phase_summary_schema_invalid")
    if phase and (phase.get("mode") != mode or phase.get("vehicle_count") != 5):
        failures.append("camera_phase_summary_identity_mismatch")
    if phase and phase.get("accepted") is not True:
        failures.append("camera_phase_summary_rejected")

    frequency_min = _threshold(config, "frequency_hz_min", 9.5)
    frequency_max = _threshold(config, "frequency_hz_max", 10.5)
    phase_error_max_ns = int(_threshold(config, "phase_error_p95_ms_max", 8.0) * 1_000_000)
    spacing_error_max_ns = int(
        _threshold(config, "spacing_median_error_ms_max", 8.0) * 1_000_000
    )
    vehicles = _mapping(phase.get("vehicles"))
    if len(vehicles) != 5:
        failures.append("camera_vehicle_evidence_incomplete")
    else:
        frequencies = [
            _finite(_mapping(vehicles.get(str(vehicle_id))).get("mean_frequency_hz"))
            for vehicle_id in range(5)
        ]
        if any(
            value is None or value < frequency_min or value > frequency_max
            for value in frequencies
        ):
            failures.append("camera_frequency_out_of_range")
        if mode == "phased" and any(
            (_finite(_mapping(vehicles.get(str(vehicle_id))).get("phase_error_p95_ns")) is None)
            or float(_mapping(vehicles.get(str(vehicle_id))).get("phase_error_p95_ns"))
            > phase_error_max_ns
            for vehicle_id in range(5)
        ):
            failures.append("camera_phase_error_p95_exceeded")

    if mode == "phased":
        if phase.get("target_offsets_ns") != [
            0, 20_000_000, 40_000_000, 60_000_000, 80_000_000
        ]:
            failures.append("camera_target_offsets_invalid")
        spacing = _mapping(phase.get("adjacent_spacing_median_error_ns"))
        if len(spacing) != 5 or any(
            (_finite(value) is None or float(value) > spacing_error_max_ns)
            for value in spacing.values()
        ):
            failures.append("camera_spacing_error_exceeded")

    integrity_fields = (
        "missed_trigger_count",
        "queue_overflow_count",
        "duplicate_trigger_count",
        "duplicate_image_count",
        "unmatched_trigger_count",
        "unmatched_image_count",
        "cross_model_error_count",
    )
    if phase and any(phase.get(key) != 0 for key in integrity_fields):
        failures.append("camera_phase_integrity_error")

    failures = list(dict.fromkeys(failures))
    return {
        **base,
        "camera_schedule_mode": mode,
        "passed": not failures,
        "failures": failures,
        "camera_phase": dict(phase),
    }


def _frozen_value(manifest: Mapping[str, object]) -> dict[str, object]:
    return {
        key: manifest.get(key)
        for key in (
            "seed",
            "campaign_id",
            "repository_revision",
            "controller_revision",
            "px4_revision",
            "frozen_hashes",
            "software_versions",
        )
    }


def _sustained_degradation(values: Sequence[float | None], threshold: float) -> bool:
    if any(value is None for value in values):
        return True
    finite = [float(value) for value in values if value is not None]
    return any(
        left < middle < right and right - left > threshold
        for left, middle, right in zip(finite, finite[1:], finite[2:])
    )


def _median_metric(scores: Sequence[Mapping[str, object]], key: str) -> float | None:
    values = [_finite(_mapping(score.get("metrics")).get(key)) for score in scores]
    if any(value is None for value in values) or not values:
        return None
    return median(float(value) for value in values if value is not None)


def score_phase_campaign(
    trials: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
    config: Mapping[str, object],
) -> dict[str, object]:
    expected = formal_schedule(config)
    validation_failures: list[str] = []
    if len(trials) != 10:
        validation_failures.append(f"expected_10_trials_got_{len(trials)}")
    baseline = _frozen_value(trials[0][0]) if trials else None
    scores: list[dict[str, object]] = []
    for index, (manifest, summary) in enumerate(trials):
        if index >= len(expected):
            validation_failures.append(f"unexpected_trial_at_position_{index + 1}")
            scores.append(score_phase_trial(manifest, summary, config))
            continue
        run = expected[index]
        pair = _mapping(manifest.get("pair"))
        renderer = _mapping(manifest.get("renderer"))
        if manifest.get("name") != run.name:
            validation_failures.append(f"trial_{index + 1}_name_or_order_mismatch")
        if manifest.get("camera_schedule_mode") != run.camera_schedule_mode:
            validation_failures.append(f"trial_{index + 1}_mode_mismatch")
        if renderer.get("requested_profile") != "d3d12-nvidia":
            validation_failures.append(f"trial_{index + 1}_renderer_mismatch")
        if pair.get("id") != run.pair_id or pair.get("position") != run.pair_position:
            validation_failures.append(f"trial_{index + 1}_pair_metadata_mismatch")
        if baseline is not None and _frozen_value(manifest) != baseline:
            validation_failures.append(f"trial_{index + 1}_frozen_inputs_mismatch")
        scores.append(score_phase_trial(manifest, summary, config))

    grouped = {
        mode: [score for score in scores if score.get("camera_schedule_mode") == mode]
        for mode in ("simultaneous", "phased")
    }
    pairs: list[dict[str, object]] = []
    for pair_id in range(1, 6):
        members = {
            score.get("camera_schedule_mode"): score
            for score in scores
            if _mapping(score.get("pair")).get("id") == pair_id
        }
        simultaneous = members.get("simultaneous")
        phased = members.get("phased")
        if simultaneous is None or phased is None:
            validation_failures.append(f"pair_{pair_id}_incomplete")
            continue
        sim_metrics = _mapping(simultaneous.get("metrics"))
        phase_metrics = _mapping(phased.get("metrics"))
        deltas = {}
        for key in ("tail_max_ms", "tail_p99_ms", "rtf"):
            left = _finite(sim_metrics.get(key))
            right = _finite(phase_metrics.get(key))
            deltas[key] = right - left if left is not None and right is not None else None
        pairs.append({
            "pair_id": pair_id,
            "simultaneous_trial": simultaneous.get("name"),
            "phased_trial": phased.get("name"),
            "phased_minus_simultaneous": deltas,
        })

    phased = grouped["phased"]
    simultaneous = grouped["simultaneous"]
    trend_threshold = _threshold(config, "sustained_degradation_ms", 5.0)
    phased_no_trend = not _sustained_degradation(
        [_finite(_mapping(score.get("metrics")).get("tail_max_ms")) for score in phased],
        trend_threshold,
    )
    simultaneous_no_trend = not _sustained_degradation(
        [_finite(_mapping(score.get("metrics")).get("tail_max_ms")) for score in simultaneous],
        trend_threshold,
    )
    tail_deltas = [
        _finite(_mapping(pair.get("phased_minus_simultaneous")).get("tail_max_ms"))
        for pair in pairs
    ]
    complete_deltas = [float(value) for value in tail_deltas if value is not None]
    negative_count = sum(value < 0 for value in complete_deltas)
    tail_delta_median = median(complete_deltas) if len(complete_deltas) == 5 else None
    sim_p99 = _median_metric(simultaneous, "tail_p99_ms")
    phased_p99 = _median_metric(phased, "tail_p99_ms")
    p99_degradation = phased_p99 - sim_p99 if sim_p99 is not None and phased_p99 is not None else None
    sim_rtf = _median_metric(simultaneous, "rtf")
    phased_rtf = _median_metric(phased, "rtf")
    rtf_degradation = sim_rtf - phased_rtf if sim_rtf is not None and phased_rtf is not None else None

    absolute_pass = bool(
        not validation_failures
        and len(scores) == 10
        and len(phased) == 5
        and len(simultaneous) == 5
        and all(score.get("passed") is True for score in scores)
    )
    efficacy_pass = bool(
        phased_no_trend
        and negative_count >= int(_threshold(config, "negative_pair_count_min", 4))
        and tail_delta_median is not None
        and tail_delta_median <= _threshold(
            config, "paired_tail_max_median_delta_ms_max", -5.0
        )
        and p99_degradation is not None
        and p99_degradation <= _threshold(
            config, "tail_p99_median_degradation_ms_max", 2.0
        )
        and rtf_degradation is not None
        and rtf_degradation <= _threshold(config, "rtf_median_degradation_max", 0.01)
    )
    verdict = (
        "rejected" if not absolute_pass
        else "supported" if efficacy_pass
        else "operational_but_not_proven"
    )
    return {
        "schema": "flydrones-camera-phase-stability-campaign-v1",
        "verdict": verdict,
        "formal_artifacts_complete": not validation_failures and len(scores) == 10,
        "validation_failures": list(dict.fromkeys(validation_failures)),
        "trials": scores,
        "pairs": pairs,
        "phased_no_sustained_degradation": phased_no_trend,
        "simultaneous_no_sustained_degradation": simultaneous_no_trend,
        "negative_tail_max_pairs": negative_count,
        "paired_tail_max_median_delta_ms": tail_delta_median,
        "tail_p99_median_degradation_ms": p99_degradation,
        "rtf_median_degradation": rtf_degradation,
        "absolute_gates_pass": absolute_pass,
        "efficacy_gates_pass": efficacy_pass,
    }
