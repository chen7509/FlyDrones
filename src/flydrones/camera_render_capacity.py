"""Frozen contracts and fail-closed scoring for sustained camera capacity trials."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

_CELLS = {
    "idle-0": (0, "native-cpp"),
    "native-1": (1, "native-cpp"),
    "python-5": (5, "python"),
    "native-5": (5, "native-cpp"),
}
_ROWS = (
    ("idle-0", "native-1", "python-5", "native-5"),
    ("native-5", "python-5", "native-1", "idle-0"),
    ("python-5", "idle-0", "native-5", "native-1"),
)
_FROZEN_THRESHOLDS: dict[str, float | int] = {
    "min_rtf": 0.95,
    "min_image_hz": 9.5,
    "max_image_hz": 10.5,
    "max_phase_error_p95_ns": 8_000_000,
    "max_spacing_median_error_ns": 8_000_000,
    "scored_duration_s": 30.0,
    "wall_timeout_s": 120.0,
    "repeatability_rtf_range_max": 0.03,
    "native_improvement_min": 0.05,
}
_INTEGRITY_FIELDS = (
    "missed_trigger_count",
    "queue_overflow_count",
    "duplicate_trigger_count",
    "duplicate_image_count",
    "unmatched_trigger_count",
    "unmatched_image_count",
    "cross_model_error_count",
)
_PHASE_PERFORMANCE_REASONS = {
    "image_frequency_out_of_range": "image_frequency_out_of_range",
    "phase_error_p95_exceeded": "phase_error_p95_exceeded",
    "spacing_median_error_exceeded": "spacing_error_exceeded",
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class CapacityCell:
    name: str
    subscriber_count: int
    implementation: str

    def __post_init__(self) -> None:
        expected = _CELLS.get(self.name)
        if expected is None:
            raise ValueError(f"unknown cell name: {self.name}")
        if isinstance(self.subscriber_count, bool) or not isinstance(self.subscriber_count, int):
            raise ValueError("subscriber_count must be an integer")
        if self.subscriber_count != expected[0]:
            raise ValueError(f"subscriber_count differs from frozen cell {self.name}")
        if self.implementation != expected[1]:
            raise ValueError(f"implementation differs from frozen cell {self.name}")


@dataclass(frozen=True)
class CapacityRun:
    name: str
    cell: CapacityCell
    repetition: int
    sequence: int

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "cell": self.cell.name,
            "subscriber_count": self.cell.subscriber_count,
            "implementation": self.cell.implementation,
            "repetition": self.repetition,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class CapacityThresholds:
    min_rtf: float
    min_image_hz: float
    max_image_hz: float
    max_phase_error_p95_ns: int
    max_spacing_median_error_ns: int
    scored_duration_s: float
    wall_timeout_s: float
    repeatability_rtf_range_max: float
    native_improvement_min: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapacityThresholds:
        if set(value) != set(_FROZEN_THRESHOLDS):
            raise ValueError("threshold keys differ from frozen contract")
        normalized: dict[str, float | int] = {}
        for key, expected in _FROZEN_THRESHOLDS.items():
            actual = _finite_number(value.get(key))
            if actual is None or actual != float(expected):
                raise ValueError(f"{key} differs from frozen value {expected}")
            normalized[key] = int(actual) if isinstance(expected, int) else actual
        return cls(**normalized)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def capacity_schedule() -> tuple[CapacityRun, ...]:
    repetitions = {name: 0 for name in _CELLS}
    runs: list[CapacityRun] = []
    for sequence, cell_name in enumerate((name for row in _ROWS for name in row), start=1):
        repetitions[cell_name] += 1
        count, implementation = _CELLS[cell_name]
        repetition = repetitions[cell_name]
        cell = CapacityCell(cell_name, count, implementation)
        runs.append(CapacityRun(
            name=f"capacity-{sequence:02d}-{cell_name}-r{repetition}",
            cell=cell,
            repetition=repetition,
            sequence=sequence,
        ))
    return tuple(runs)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _append_once(values: list[str], reason: str) -> None:
    if reason not in values:
        values.append(reason)


def score_capacity_run(
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    thresholds: CapacityThresholds,
) -> dict[str, object]:
    evidence: list[str] = []
    performance: list[str] = []
    cell_name = manifest.get("cell")
    expected = _CELLS.get(cell_name) if isinstance(cell_name, str) else None
    if expected is None:
        evidence.append("cell_identity_invalid")
        expected_subscribers = -1
        expected_implementation = ""
    else:
        expected_subscribers, expected_implementation = expected

    if manifest.get("subscriber_count") != expected_subscribers:
        evidence.append("subscriber_count_mismatch")
    if manifest.get("observer_implementation") != expected_implementation:
        evidence.append("observer_implementation_mismatch")
    if manifest.get("renderer_attestation_accepted") is not True:
        evidence.append("renderer_attestation_rejected")
    if manifest.get("px4_vehicle_count") != 5 or manifest.get("px4_all_healthy") is not True:
        evidence.append("px4_health_invalid")
    if manifest.get("px4_all_disarmed") is not True:
        evidence.append("px4_not_disarmed")
    if manifest.get("px4_all_landed") is not True:
        evidence.append("px4_not_landed")

    duration = _finite_number(manifest.get("scored_duration_sim_s"))
    scored_window_complete = (
        duration is not None and duration >= thresholds.scored_duration_s
    )
    if not scored_window_complete:
        evidence.append("scored_duration_incomplete")
    if _finite_number(manifest.get("scored_wall_timeout_s")) != thresholds.wall_timeout_s:
        evidence.append("wall_timeout_mismatch")
    if (
        manifest.get("depth_subscription_count_start") != expected_subscribers
        or manifest.get("depth_subscription_count_end") != expected_subscribers
    ):
        _append_once(evidence, "subscriber_count_mismatch")
    if manifest.get("trigger_stream_count") != 5:
        evidence.append("trigger_stream_count_mismatch")
    if manifest.get("source_hashes_match") is not True:
        evidence.append("source_hash_mismatch")
    if manifest.get("native_executable_hash_match") is not True:
        evidence.append("native_executable_hash_mismatch")
    if manifest.get("px4_build_identity_match") is not True:
        evidence.append("px4_build_identity_mismatch")
    if manifest.get("observer_closed_cleanly") is not True:
        evidence.append("observer_not_clean")
    if manifest.get("scheduler_closed_cleanly") is not True:
        evidence.append("scheduler_not_clean")
    if manifest.get("stop_exit_code") != 0:
        evidence.append("stop_failed")
    if manifest.get("launcher_exit_code") != 0:
        evidence.append("launcher_failed")
    if manifest.get("shared_px4_files_restored") is not True:
        evidence.append("shared_px4_files_not_restored")
    if manifest.get("trial_cleanup_verified") is not True:
        evidence.append("cleanup_not_verified")
    if manifest.get("evidence_accepted") is not True:
        evidence.append("manifest_evidence_rejected")
    ulogs = manifest.get("ulog_artifacts")
    if (
        not isinstance(ulogs, list)
        or len(ulogs) != 5
        or {
            item.get("vehicle_id")
            for item in ulogs
            if isinstance(item, Mapping)
        }
        != set(range(5))
        or any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("path"), str)
            or not item.get("path")
            or not isinstance(item.get("bytes"), int)
            or item.get("bytes", 0) <= 0
            or not isinstance(item.get("sha256"), str)
            or len(item.get("sha256", "")) != 64
            for item in ulogs
        )
    ):
        evidence.append("px4_ulogs_incomplete")

    phase = _mapping(summary.get("camera_phase"))
    if phase.get("trigger_stream_count") != 5:
        _append_once(evidence, "trigger_stream_count_mismatch")
    if any(phase.get(field) != 0 for field in _INTEGRITY_FIELDS):
        evidence.append("camera_integrity_error")

    vehicles = _mapping(phase.get("vehicles"))
    if expected_subscribers == 0:
        if phase.get("depth_subscription_absent") is not True or vehicles:
            evidence.append("unexpected_depth_subscription")
    elif expected_subscribers > 0:
        if len(vehicles) != expected_subscribers:
            evidence.append("camera_vehicle_count_mismatch")
        for vehicle in vehicles.values():
            item = _mapping(vehicle)
            if item.get("width") != 160 or item.get("height") != 120:
                _append_once(evidence, "camera_dimensions_invalid")
            if item.get("format") != "R_FLOAT32":
                _append_once(evidence, "camera_format_invalid")
            if scored_window_complete:
                frequency = _finite_number(item.get("frequency_hz"))
                if frequency is None:
                    _append_once(evidence, "image_frequency_missing_or_invalid")
                elif not thresholds.min_image_hz <= frequency <= thresholds.max_image_hz:
                    _append_once(performance, "image_frequency_out_of_range")
                phase_error = _finite_number(item.get("phase_error_p95_ns"))
                if phase_error is None:
                    _append_once(evidence, "phase_error_p95_missing_or_invalid")
                elif phase_error > thresholds.max_phase_error_p95_ns:
                    _append_once(performance, "phase_error_p95_exceeded")
        if expected_subscribers == 5 and scored_window_complete:
            spacing = _finite_number(phase.get("adjacent_spacing_median_error_ns"))
            if spacing is None:
                _append_once(evidence, "spacing_median_error_missing_or_invalid")
            elif spacing > thresholds.max_spacing_median_error_ns:
                _append_once(performance, "spacing_error_exceeded")
        if phase.get("accepted") is not True:
            phase_reasons = phase.get("reasons")
            if (
                not isinstance(phase_reasons, list)
                or not phase_reasons
                or any(not isinstance(reason, str) for reason in phase_reasons)
                or any(reason not in _PHASE_PERFORMANCE_REASONS for reason in phase_reasons)
                or any(
                    _PHASE_PERFORMANCE_REASONS[reason] not in performance
                    for reason in phase_reasons
                )
            ):
                evidence.append("camera_phase_summary_rejected")

    runtime = _mapping(summary.get("runtime"))
    if _mapping(runtime.get("resources")).get("accepted") is not True:
        evidence.append("resource_evidence_invalid")
    rtf = _finite_number(_mapping(runtime.get("rtf")).get("scored_window"))
    if rtf is None:
        evidence.append("rtf_missing_or_invalid")
    elif scored_window_complete and rtf < thresholds.min_rtf:
        performance.append("rtf_below_threshold")

    evidence_valid = not evidence
    performance_pass = evidence_valid and not performance
    return {
        "name": manifest.get("name"),
        "cell": cell_name,
        "repetition": manifest.get("repetition"),
        "sequence": manifest.get("sequence"),
        "rtf": rtf,
        "score_status": "scored" if scored_window_complete else "unscored",
        "evidence_valid": evidence_valid,
        "performance_pass": performance_pass,
        "evidence_failures": evidence,
        "performance_failures": performance,
        "failures": [*evidence, *performance],
    }


def _configured_schedule(config: Mapping[str, object]) -> list[Mapping[str, object]]:
    schedule = config.get("schedule")
    if not isinstance(schedule, list) or not all(isinstance(item, Mapping) for item in schedule):
        raise ValueError("capacity schedule missing or invalid")
    return schedule


def _inconclusive(scores: Sequence[Mapping[str, object]], reasons: Sequence[str]) -> dict[str, object]:
    return {
        "schema": "flydrones-camera-render-capacity-campaign-summary-v1",
        "classification": "non_monotonic_or_inconclusive",
        "production_integration_eligible": False,
        "reasons": list(reasons),
        "scores": [dict(score) for score in scores],
    }


def classify_capacity_campaign(
    runs: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
    config: Mapping[str, object],
) -> dict[str, object]:
    thresholds = CapacityThresholds.from_mapping(_mapping(config.get("thresholds")))
    expected_runs = capacity_schedule()
    expected_schedule = [run.as_dict() for run in expected_runs]
    if [dict(item) for item in _configured_schedule(config)] != expected_schedule:
        raise ValueError("configured capacity schedule differs from frozen schedule")

    scores = [score_capacity_run(manifest, summary, thresholds) for manifest, summary in runs]
    identities = [score.get("name") for score in scores]
    expected_identities = [run.name for run in expected_runs]
    reasons: list[str] = []
    if len(scores) != len(expected_runs):
        reasons.append("run_count_mismatch")
    if len(set(identities)) != len(identities):
        reasons.append("duplicate_run_identity")
    if identities != expected_identities:
        reasons.append("run_identity_or_order_mismatch")
    if any(score.get("evidence_valid") is not True for score in scores):
        reasons.append("invalid_run_evidence")
    if reasons:
        return _inconclusive(scores, reasons)

    by_cell: dict[str, list[dict[str, object]]] = {name: [] for name in _CELLS}
    for score in scores:
        by_cell[str(score["cell"])].append(score)
    if any(len(cell_scores) != 3 for cell_scores in by_cell.values()):
        return _inconclusive(scores, ["cell_repetition_count_mismatch"])

    medians: dict[str, float] = {}
    ranges: dict[str, float] = {}
    for name, cell_scores in by_cell.items():
        values = [float(score["rtf"]) for score in cell_scores]
        medians[name] = statistics.median(values)
        ranges[name] = max(values) - min(values)
    if any(value > thresholds.repeatability_rtf_range_max + 1e-12 for value in ranges.values()):
        return _inconclusive(scores, ["rtf_repeatability_range_exceeded"])

    if any(score["performance_pass"] is not True for score in by_cell["idle-0"]):
        classification = "host_or_baseline_capacity_failure"
        eligible = False
    else:
        native_pass = all(score["performance_pass"] is True for score in by_cell["native-5"])
        python_fail = all(score["performance_pass"] is False for score in by_cell["python-5"])
        if native_pass and python_fail:
            classification = "python_transport_boundary"
            eligible = True
        elif not native_pass:
            improvement = medians["native-5"] - medians["python-5"]
            if improvement + 1e-12 >= thresholds.native_improvement_min:
                classification = "mixed_python_and_render_capacity"
            else:
                classification = "sustained_render_transport_capacity"
            eligible = False
        else:
            return _inconclusive(scores, ["python_and_native_results_do_not_isolate_boundary"])

    return {
        "schema": "flydrones-camera-render-capacity-campaign-summary-v1",
        "classification": classification,
        "production_integration_eligible": eligible,
        "reasons": [],
        "cell_median_rtf": medians,
        "cell_rtf_range": ranges,
        "native_minus_python_median_rtf": medians["native-5"] - medians["python-5"],
        "scores": scores,
    }
