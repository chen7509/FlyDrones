"""Fail-closed authorization for camera-capacity reruns."""

from __future__ import annotations

from collections.abc import Mapping

from .px4_sensor_readiness import (
    ReadinessThresholds,
    readiness_schedule,
)


def validate_camera_rerun_gate(
    summary: Mapping[str, object], config: Mapping[str, object]
) -> dict[str, object]:
    """Accept only the exact frozen ten-run PX4 readiness pass."""
    ReadinessThresholds.from_mapping(config.get("thresholds", {}))
    schedules = config.get("schedules")
    expected = readiness_schedule("formal")
    if not isinstance(schedules, Mapping) or schedules.get("formal") != [
        run.as_dict() for run in expected
    ]:
        raise ValueError("formal readiness schedule differs from frozen contract")
    if summary.get("schema") != "flydrones-px4-sensor-readiness-campaign-summary-v1":
        raise ValueError("readiness summary schema mismatch")
    if summary.get("classification") != "stable_sensor_readiness":
        raise ValueError("formal readiness classification is not stable")
    if summary.get("camera_rerun_eligible") is not True:
        raise ValueError("formal readiness summary is not eligible for camera rerun")
    scores = summary.get("scores")
    if not isinstance(scores, list) or len(scores) != 10:
        raise ValueError("camera rerun requires ten valid passing runs")
    for score, run in zip(scores, expected, strict=True):
        if not isinstance(score, Mapping) or not (
            score.get("name") == run.name
            and score.get("phase") == "formal"
            and score.get("vehicle_count") == 5
            and score.get("repetition") == run.repetition
            and score.get("sequence") == run.sequence
            and score.get("evidence_valid") is True
            and score.get("performance_pass") is True
            and score.get("failures") == []
        ):
            raise ValueError("camera rerun requires ten valid passing runs")
    return {
        "schema": "flydrones-camera-rerun-gate-v1",
        "accepted": True,
        "run_count": len(scores),
        "classification": summary["classification"],
    }
