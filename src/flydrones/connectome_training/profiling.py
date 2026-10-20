from __future__ import annotations

import time
from collections.abc import Iterable
from copy import deepcopy
from numbers import Real

import numpy as np


def _stats(values: list[float]) -> dict[str, float]:
    data = np.asarray(values, np.float64)
    return {
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50, method="linear")),
        "p95": float(np.percentile(data, 95, method="linear")),
        "p99": float(np.percentile(data, 99, method="linear")),
        "max": float(data.max()),
    }


def _duration(value, field: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{field} requires a numeric duration")
    value = float(value)
    if not np.isfinite(value) or value < 0:
        raise ValueError(f"{field} requires a finite non-negative duration")
    return value


def summarize_latency(samples: Iterable[dict]) -> dict:
    rows = list(samples)
    if not rows:
        raise ValueError("at least one latency sample is required")
    if any("elapsed_wall_s" not in row for row in rows):
        raise ValueError("every latency sample requires elapsed_wall_s")
    total = [_duration(row["elapsed_wall_s"], "elapsed_wall_s") for row in rows]
    neural = [
        _duration(
            row.get("components", {}).get(
                "neural_s", row.get("brain_wall_s", 0.0)
            ), "neural_s"
        )
        for row in rows
    ]
    if any(neural_s > total_s for total_s, neural_s in zip(total, neural)):
        raise ValueError("neural duration exceeds reported total")
    overhead = [total_s - neural_s for total_s, neural_s in zip(total, neural)]
    return {
        "samples": len(rows),
        "total_s": _stats(total),
        "neural_s": _stats(neural),
        "overhead_s": _stats(overhead),
    }


def profile_controller(controller, observations, *, on_sample=None) -> dict:
    """Measure synchronous step calls; does not synchronize asynchronous devices.

    total_s/neural_s remain controller-reported diagnostics for v1 comparison.
    outer_s is the externally measured input-to-Decision-return interval; it
    excludes input acquisition, warmup, report serialization and flight transport.
    Optional on_sample receives a defensive copy after timing; its exceptions
    propagate so a failed evidence writer cannot silently qualify a run.
    """
    rows = []
    for observation in observations:
        started = time.perf_counter_ns()
        decision = controller.step(observation)
        finished = time.perf_counter_ns()
        if finished < started:
            raise ValueError("profiling clock regressed")
        measured = (finished - started) / 1_000_000_000
        evidence = dict(decision.evidence)
        evidence["elapsed_wall_s"] = decision.elapsed_wall_s
        evidence["outer_wall_s"] = measured
        evidence["started_perf_ns"] = started
        evidence["finished_perf_ns"] = finished
        evidence["sim_ns"] = observation.sim_ns
        rows.append(evidence)
        if on_sample is not None:
            on_sample(deepcopy(evidence))
    result = summarize_latency(rows)
    result["outer_s"] = _stats([row["outer_wall_s"] for row in rows])
    result["raw_samples"] = rows
    return result
