"""Offline evaluation for consecutive hybrid PX4/Gazebo acceptance runs."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

_PREFLIGHT_CHECKS = {
    "all_reached_altitude",
    "local_depth_ready",
    "all_local_depth_ready",
}
_NAVIGATION_CHECKS = {
    "all_escaped",
    "all_rallied",
    "all_landed",
    "zero_forest_contacts",
    "safe_forest_clearance",
}
_SEPARATION_CHECKS = {"safe_intervehicle_separation"}


def _load_summary(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"accepted": False, "checks": {}, "metrics": {}, "_load_error": str(exc)}
    if not isinstance(value, dict):
        return {"accepted": False, "checks": {}, "metrics": {}, "_load_error": "summary is not an object"}
    return value


def _false_check(checks: dict, names: set[str]) -> bool:
    return any(name in checks and checks[name] is not True for name in names)


def _finite_metric(metrics: dict, name: str) -> float | None:
    try:
        value = float(metrics[name])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _failure_category(summary: dict) -> str | None:
    checks = summary.get("checks")
    metrics = summary.get("metrics")
    if not isinstance(checks, dict) or not isinstance(metrics, dict):
        return "infrastructure"
    if _false_check(checks, _PREFLIGHT_CHECKS):
        return "preflight"
    if _false_check(checks, _NAVIGATION_CHECKS):
        return "navigation"
    if _false_check(checks, _SEPARATION_CHECKS):
        return "separation"

    planner_p95 = _finite_metric(metrics, "planner_p95_ms")
    if planner_p95 is None or planner_p95 >= 20.0:
        return "planner-performance"

    central_commands = _finite_metric(metrics, "central_control_commands")
    known_checks = _PREFLIGHT_CHECKS | _NAVIGATION_CHECKS | _SEPARATION_CHECKS
    remaining_checks_pass = all(value is True for key, value in checks.items() if key not in known_checks)
    if (
        summary.get("_load_error")
        or summary.get("accepted") is not True
        or central_commands != 0.0
        or not checks
        or not remaining_checks_pass
    ):
        return "infrastructure"
    return None


def _aggregate_repeatability_metrics(summaries: list[dict], consecutive: int) -> dict:
    forest_clearances = [
        value
        for summary in summaries
        if (value := _finite_metric(summary.get("metrics", {}), "minimum_forest_clearance_m")) is not None
    ]
    peer_clearances = [
        value
        for summary in summaries
        if (value := _finite_metric(summary.get("metrics", {}), "minimum_intervehicle_distance_m")) is not None
    ]
    planner_p95_values = [
        value
        for summary in summaries
        if (value := _finite_metric(summary.get("metrics", {}), "planner_p95_ms")) is not None
    ]
    return {
        "runs": len(summaries),
        "passing_runs": sum(_failure_category(summary) is None for summary in summaries),
        "consecutive_passes": consecutive,
        "minimum_forest_clearance_m": min(forest_clearances) if forest_clearances else None,
        "minimum_intervehicle_distance_m": min(peer_clearances) if peer_clearances else None,
        "worst_planner_p95_ms": max(planner_p95_values) if planner_p95_values else None,
        "central_control_commands": sum(
            int(_finite_metric(summary.get("metrics", {}), "central_control_commands") or 0.0)
            for summary in summaries
        ),
    }


def evaluate_px4_repetitions(
    run_dirs: Sequence[str | Path],
    *,
    required: int = 5,
) -> dict:
    if required <= 0:
        raise ValueError("required consecutive run count must be positive")
    paths = [Path(run_dir) for run_dir in run_dirs]
    summaries = [_load_summary(path / "summary.json") for path in paths]
    consecutive = 0
    failures = []
    for index, (path, summary) in enumerate(zip(paths, summaries), start=1):
        category = _failure_category(summary)
        if category is None:
            consecutive += 1
        else:
            failures.append({"run": index, "path": str(path), "category": category})
            consecutive = 0
    metrics = _aggregate_repeatability_metrics(summaries, consecutive)
    metrics["required_consecutive_passes"] = int(required)
    return {
        "accepted": len(summaries) >= required and consecutive >= required,
        "metrics": metrics,
        "failures": failures,
    }
