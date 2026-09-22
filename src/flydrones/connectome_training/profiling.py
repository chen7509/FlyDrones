from __future__ import annotations

import time
from typing import Iterable

import numpy as np


def _stats(values: list[float]) -> dict[str, float]:
    data = np.asarray(values, np.float64)
    return {
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50)),
        "p95": float(np.percentile(data, 95)),
        "p99": float(np.percentile(data, 99)),
        "max": float(data.max()),
    }


def summarize_latency(samples: Iterable[dict]) -> dict:
    rows = list(samples)
    if not rows:
        raise ValueError("at least one latency sample is required")
    if any("elapsed_wall_s" not in row for row in rows):
        raise ValueError("every latency sample requires elapsed_wall_s")
    total = [float(row["elapsed_wall_s"]) for row in rows]
    neural = [
        float(
            row.get("components", {}).get(
                "neural_s", row.get("brain_wall_s", 0.0)
            )
        )
        for row in rows
    ]
    if not np.isfinite(total + neural).all():
        raise ValueError("latency samples contain non-finite values")
    overhead = [max(0.0, total_s - neural_s) for total_s, neural_s in zip(total, neural)]
    return {
        "samples": len(rows),
        "total_s": _stats(total),
        "neural_s": _stats(neural),
        "overhead_s": _stats(overhead),
    }


def profile_controller(controller, observations) -> dict:
    rows = []
    for observation in observations:
        started = time.perf_counter()
        decision = controller.step(observation)
        measured = time.perf_counter() - started
        evidence = dict(decision.evidence)
        evidence["elapsed_wall_s"] = float(decision.elapsed_wall_s)
        evidence["outer_wall_s"] = measured
        rows.append(evidence)
    result = summarize_latency(rows)
    result["outer_s"] = _stats([row["outer_wall_s"] for row in rows])
    return result
