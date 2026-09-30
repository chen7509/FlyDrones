"""Frozen contracts and fail-closed scoring for PX4 sensor-readiness trials."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

_PHASE_VEHICLE_COUNTS = {
    "development": (1, 2, 5),
    "formal": (5,) * 10,
}
_FROZEN_THRESHOLDS: dict[str, float | int] = {
    "min_rtf": 0.95,
    "scored_duration_s": 30.0,
    "wall_timeout_s": 120.0,
    "repeatability_rtf_range_max": 0.03,
    "formal_run_count": 10,
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sensor_topics(vehicle_count: int) -> dict[str, str]:
    suffixes = {
        "imu": "imu_sensor/imu",
        "magnetometer": "magnetometer_sensor/magnetometer",
        "gps": "navsat_sensor/navsat",
        "barometer": "air_pressure_sensor/air_pressure",
    }
    return {
        f"{vehicle_id}:{sensor}": (
            "/world/flydrones_forest/model/"
            f"x500_depth_fly_{vehicle_id}/link/base_link/sensor/{suffix}"
        )
        for vehicle_id in range(vehicle_count)
        for sensor, suffix in suffixes.items()
    }


@dataclass(frozen=True)
class ReadinessRun:
    name: str
    phase: str
    vehicle_count: int
    repetition: int
    sequence: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessThresholds:
    min_rtf: float
    scored_duration_s: float
    wall_timeout_s: float
    repeatability_rtf_range_max: float
    formal_run_count: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ReadinessThresholds:
        if set(value) != set(_FROZEN_THRESHOLDS):
            raise ValueError("threshold keys differ from frozen readiness contract")
        normalized: dict[str, float | int] = {}
        for key, expected in _FROZEN_THRESHOLDS.items():
            actual = _finite_number(value.get(key))
            if actual is None or actual != float(expected):
                raise ValueError(f"{key} differs from frozen value {expected}")
            normalized[key] = int(actual) if isinstance(expected, int) else actual
        return cls(**normalized)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def readiness_schedule(phase: str) -> tuple[ReadinessRun, ...]:
    counts = _PHASE_VEHICLE_COUNTS.get(phase)
    if counts is None:
        raise ValueError(f"unknown readiness phase: {phase}")
    repetitions: dict[int, int] = {}
    runs: list[ReadinessRun] = []
    for sequence, vehicle_count in enumerate(counts, start=1):
        repetitions[vehicle_count] = repetitions.get(vehicle_count, 0) + 1
        repetition = repetitions[vehicle_count]
        runs.append(
            ReadinessRun(
                name=(
                    f"readiness-{phase}-{sequence:02d}-"
                    f"v{vehicle_count}-r{repetition}"
                ),
                phase=phase,
                vehicle_count=vehicle_count,
                repetition=repetition,
                sequence=sequence,
            )
        )
    return tuple(runs)


def _valid_ulogs(value: Any, vehicle_count: int) -> bool:
    if not isinstance(value, list) or len(value) != vehicle_count:
        return False
    identities = {
        item.get("vehicle_id")
        for item in value
        if isinstance(item, Mapping)
    }
    if identities != set(range(vehicle_count)):
        return False
    return all(
        isinstance(item, Mapping)
        and isinstance(item.get("path"), str)
        and bool(item.get("path"))
        and isinstance(item.get("bytes"), int)
        and not isinstance(item.get("bytes"), bool)
        and item.get("bytes", 0) > 0
        and _valid_sha256(item.get("sha256"))
        for item in value
    )


def score_readiness_run(
    manifest: Mapping[str, object],
    summary: Mapping[str, object],
    thresholds: ReadinessThresholds,
) -> dict[str, object]:
    evidence: list[str] = []
    performance: list[str] = []

    vehicle_count = manifest.get("vehicle_count")
    valid_vehicle_count = (
        isinstance(vehicle_count, int)
        and not isinstance(vehicle_count, bool)
        and vehicle_count in {1, 2, 5}
    )
    expected_topics = int(vehicle_count) * 4 if valid_vehicle_count else 0
    errors = manifest.get("errors")
    if not isinstance(errors, list) or errors:
        evidence.append("artifact_collection_failed")

    build = _mapping(manifest.get("px4_build_evidence"))
    if not (
        build.get("schema") == "flydrones-px4-build-evidence-v1"
        and build.get("build_name") == "px4_sitl_nolockstep"
        and build.get("nolockstep") is True
        and isinstance(build.get("px4_revision"), str)
        and len(str(build.get("px4_revision"))) == 40
        and _valid_sha256(build.get("binary_sha256"))
        and _valid_sha256(build.get("boardconfig_sha256"))
        and build.get("board_definition") == "#define CONFIG_BOARD_NOLOCKSTEP 1"
    ):
        evidence.append("px4_build_evidence_invalid")

    source = _mapping(manifest.get("sensor_source_evidence"))
    expected_topic_paths = _sensor_topics(int(vehicle_count)) if valid_vehicle_count else {}
    source_topics = _mapping(source.get("topics"))
    if not (
        source.get("schema") == "flydrones-gazebo-sensor-source-warmup-v1"
        and source.get("accepted") is True
        and source.get("expected_topic_count") == expected_topics
        and source.get("message_topic_count") == expected_topics
        and set(source_topics) == set(expected_topic_paths)
        and all(
            _mapping(source_topics[key]).get("topic") == topic
            and _mapping(source_topics[key]).get("returncode") == 0
            and _mapping(source_topics[key]).get("message_received") is True
            for key, topic in expected_topic_paths.items()
        )
    ):
        evidence.append("sensor_source_evidence_invalid")

    topology = _mapping(manifest.get("sensor_topology_evidence"))
    topology_topics = _mapping(topology.get("topics"))
    if not (
        topology.get("schema") == "flydrones-px4-sensor-topic-connections-v1"
        and topology.get("accepted") is True
        and topology.get("expected_topic_count") == expected_topics
        and topology.get("publisher_count") == expected_topics
        and topology.get("subscriber_count") == expected_topics
        and set(topology_topics) == set(expected_topic_paths)
        and all(
            _mapping(topology_topics[key]).get("topic") == topic
            and _mapping(topology_topics[key]).get("returncode") == 0
            and _mapping(topology_topics[key]).get("publisher") is True
            and _mapping(topology_topics[key]).get("subscriber") is True
            and _mapping(topology_topics[key]).get("publisher_count") == 1
            and _mapping(topology_topics[key]).get("subscriber_count") == 1
            for key, topic in expected_topic_paths.items()
        )
    ):
        evidence.append("sensor_topology_evidence_invalid")

    cleanup = _mapping(manifest.get("cleanup_evidence"))
    stopped = cleanup.get("stopped")
    already_gone = cleanup.get("already_gone")
    cleanup_items = [
        *(stopped if isinstance(stopped, list) else []),
        *(already_gone if isinstance(already_gone, list) else []),
    ]
    expected_roles = {
        "gazebo-server",
        *(
            (f"px4-{vehicle_id}" for vehicle_id in range(int(vehicle_count)))
            if valid_vehicle_count
            else ()
        ),
    }
    if not (
        cleanup.get("schema") == "flydrones-owned-process-cleanup-v1"
        and cleanup.get("recorded_processes") == (
            int(vehicle_count) + 1 if valid_vehicle_count else -1
        )
        and cleanup.get("ownership_mismatch") == []
        and cleanup.get("failed_to_stop") == []
        and isinstance(stopped, list)
        and isinstance(already_gone, list)
        and len(cleanup_items) == cleanup.get("recorded_processes")
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("pid"), int)
            and item.get("pid", 0) > 0
            and isinstance(item.get("start_ticks"), int)
            and item.get("start_ticks", 0) > 0
            and isinstance(item.get("role"), str)
            for item in cleanup_items
        )
        and {item.get("role") for item in cleanup_items if isinstance(item, Mapping)}
        == expected_roles
        and len(
            {
                (item.get("pid"), item.get("start_ticks"))
                for item in cleanup_items
                if isinstance(item, Mapping)
            }
        )
        == len(cleanup_items)
    ):
        evidence.append("cleanup_evidence_invalid")

    restoration = _mapping(manifest.get("restoration_evidence"))
    restoration_items = _mapping(restoration.get("items"))
    if not (
        restoration.get("schema") == "flydrones-px4-shared-restoration-v1"
        and restoration.get("restored") is True
        and set(restoration_items) == {"world", "OakD-Lite-Fly", "x500_depth_fly"}
        and all(
            _mapping(item).get("matched") is True
            and _valid_sha256(_mapping(item).get("backup_sha256"))
            and _mapping(item).get("backup_sha256")
            == _mapping(item).get("restored_sha256")
            for item in restoration_items.values()
        )
    ):
        evidence.append("restoration_evidence_invalid")
    if manifest.get("launcher_exit_code") != 0:
        evidence.append("launcher_failed")
    if manifest.get("platform_ready") is not True:
        evidence.append("platform_not_ready")
    if manifest.get("initial_all_healthy") is not True:
        evidence.append("initial_health_invalid")
    if manifest.get("post_window_all_healthy") is not True:
        evidence.append("post_window_health_invalid")

    duration = _finite_number(manifest.get("scored_duration_sim_s"))
    if duration is None or duration < thresholds.scored_duration_s:
        evidence.append("scored_duration_incomplete")
    if _finite_number(manifest.get("scored_wall_timeout_s")) != thresholds.wall_timeout_s:
        evidence.append("wall_timeout_mismatch")
    if manifest.get("sensor_timeout_count") != 0:
        evidence.append("sensor_timeout_observed")
    if manifest.get("trial_cleanup_verified") is not True:
        evidence.append("cleanup_not_verified")
    if manifest.get("shared_px4_files_restored") is not True:
        evidence.append("shared_px4_files_not_restored")
    if not valid_vehicle_count or not _valid_ulogs(
        manifest.get("ulog_artifacts"), int(vehicle_count) if valid_vehicle_count else 0
    ):
        evidence.append("px4_ulogs_incomplete")

    vehicles = _mapping(summary.get("vehicles"))
    if valid_vehicle_count:
        expected_ids = {str(vehicle_id) for vehicle_id in range(int(vehicle_count))}
        if set(vehicles) != expected_ids:
            evidence.append("vehicle_health_evidence_incomplete")
        elif any(
            _mapping(vehicle).get("initial_healthy") is not True
            or _mapping(vehicle).get("post_window_healthy") is not True
            for vehicle in vehicles.values()
        ):
            evidence.append("vehicle_health_evidence_incomplete")

    rtf = _finite_number(_mapping(summary.get("runtime")).get("rtf"))
    if rtf is None:
        evidence.append("rtf_missing_or_invalid")
    elif rtf < thresholds.min_rtf:
        performance.append("rtf_below_threshold")

    evidence_valid = not evidence
    performance_pass = evidence_valid and not performance
    return {
        "name": manifest.get("name"),
        "phase": manifest.get("phase"),
        "vehicle_count": vehicle_count,
        "repetition": manifest.get("repetition"),
        "sequence": manifest.get("sequence"),
        "rtf": rtf,
        "evidence_valid": evidence_valid,
        "performance_pass": performance_pass,
        "evidence_failures": evidence,
        "performance_failures": performance,
        "failures": [*evidence, *performance],
    }


def _configured_schedule(config: Mapping[str, object], phase: str) -> list[Mapping[str, object]]:
    schedules = config.get("schedules")
    if not isinstance(schedules, Mapping):
        raise ValueError("readiness schedules missing or invalid")
    schedule = schedules.get(phase)
    if not isinstance(schedule, list) or not all(isinstance(item, Mapping) for item in schedule):
        raise ValueError(f"readiness {phase} schedule missing or invalid")
    return schedule


def _result(
    classification: str,
    scores: Sequence[Mapping[str, object]],
    *,
    eligible: bool,
    reasons: Sequence[str] = (),
) -> dict[str, object]:
    passed = sum(score.get("performance_pass") is True for score in scores)
    return {
        "schema": "flydrones-px4-sensor-readiness-campaign-summary-v1",
        "classification": classification,
        "camera_rerun_eligible": eligible,
        "readiness_rate": passed / len(scores) if scores else 0.0,
        "reasons": list(reasons),
        "scores": [dict(score) for score in scores],
    }


def classify_readiness_campaign(
    runs: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
    config: Mapping[str, object],
    *,
    phase: str,
) -> dict[str, object]:
    thresholds = ReadinessThresholds.from_mapping(_mapping(config.get("thresholds")))
    expected_runs = readiness_schedule(phase)
    expected_schedule = [run.as_dict() for run in expected_runs]
    configured = [dict(item) for item in _configured_schedule(config, phase)]
    if configured != expected_schedule:
        raise ValueError(f"configured readiness {phase} schedule differs from frozen schedule")

    scores = [score_readiness_run(manifest, summary, thresholds) for manifest, summary in runs]
    expected_identities = [run.name for run in expected_runs]
    identities = [score.get("name") for score in scores]
    reasons: list[str] = []
    if len(scores) != len(expected_runs):
        reasons.append("run_count_mismatch")
    if len(set(identities)) != len(identities):
        reasons.append("duplicate_run_identity")
    if identities != expected_identities:
        reasons.append("run_identity_or_order_mismatch")
    for score, expected in zip(scores, expected_runs, strict=False):
        if any(
            score.get(field) != expected.as_dict()[field]
            for field in ("phase", "vehicle_count", "repetition", "sequence")
        ):
            if "run_identity_or_order_mismatch" not in reasons:
                reasons.append("run_identity_or_order_mismatch")
            break
    if any(score.get("evidence_valid") is not True for score in scores):
        reasons.append("invalid_run_evidence")
    if reasons:
        return _result(
            "inconclusive_or_invalid", scores, eligible=False, reasons=reasons
        )

    if phase == "development":
        if all(score.get("performance_pass") is True for score in scores):
            return _result("development_pass", scores, eligible=False)
        return _result("baseline_below_realtime", scores, eligible=False)

    if len(scores) != thresholds.formal_run_count:
        return _result(
            "inconclusive_or_invalid",
            scores,
            eligible=False,
            reasons=("formal_run_count_mismatch",),
        )
    if any(score.get("performance_pass") is not True for score in scores):
        return _result("baseline_below_realtime", scores, eligible=False)

    rtfs = [float(score["rtf"]) for score in scores]
    rtf_range = max(rtfs) - min(rtfs)
    if rtf_range > thresholds.repeatability_rtf_range_max + 1e-12:
        result = _result(
            "realtime_unstable",
            scores,
            eligible=False,
            reasons=("rtf_repeatability_range_exceeded",),
        )
    else:
        result = _result("stable_sensor_readiness", scores, eligible=True)
    result["median_rtf"] = statistics.median(rtfs)
    result["rtf_range"] = rtf_range
    return result
