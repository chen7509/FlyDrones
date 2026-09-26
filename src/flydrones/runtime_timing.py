"""Tail-latency summaries for Gazebo wall-clock evidence."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _metrics(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "sample_count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": max(values) if values else None,
        "at_or_over_100_ms": sum(value >= 100 for value in values),
        "at_or_over_200_ms": sum(value >= 200 for value in values),
        "at_or_over_250_ms": sum(value >= 250 for value in values),
    }


def summarize_gap_series(
    rows: Iterable[Mapping[str, str]],
    *,
    epoch_start_s: float | None,
) -> dict[str, object]:
    samples = []
    for row in rows:
        timestamp = float(row["monotonic_s"])
        gap = float(row["wall_gap_ms"])
        interval_start = float(row.get("interval_start_s", timestamp - gap / 1000.0))
        samples.append((timestamp, interval_start, gap))
    full_values = [gap for _timestamp, _interval_start, gap in samples]
    steady_values = (
        [gap for _timestamp, interval_start, gap in samples if interval_start >= epoch_start_s]
        if epoch_start_s is not None
        else None
    )
    return {
        "full_run": _metrics(full_values),
        "steady_state_valid": epoch_start_s is not None and bool(steady_values),
        "steady_state": _metrics(steady_values) if steady_values else None,
        "steady_state_epoch_monotonic_s": epoch_start_s,
    }
