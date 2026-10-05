"""Offline sampled-state consistency, never a source of estimator measurements."""

from __future__ import annotations

import math

import numpy as np

from tools.benchmark.physics_substep_trace import _state


def _norm(value):
    result = math.hypot(*value)
    if not math.isfinite(result):
        raise ValueError("nonfinite reference norm")
    return result


def _sum(value):
    try:
        with np.errstate(over="raise", invalid="raise"):
            result = np.sum(value, axis=0)
        if not np.isfinite(result).all():
            raise ValueError("nonfinite reference aggregate")
        return result.tolist()
    except FloatingPointError as exc:
        raise ValueError("nonfinite reference aggregate") from exc


def analyze_reference(rows):
    """Validate a paired 1 ms prefix and retain every stopped-pose contradiction.

    Callback timestamps establish ordering only. Even an internally consistent
    sequence cannot establish backend component freshness or fusion eligibility.
    """
    if not isinstance(rows, list) or not 4 <= len(rows) <= 50000 or len(rows) % 2:
        raise ValueError("invalid paired trace length")
    last_wall = 0
    for index, row in enumerate(rows):
        try:
            expected_ns = (index // 2 + 1) * 1_000_000
            expected_phase = ("pre", "post")[index % 2]
            expected_state_ns = expected_ns - (1_000_000 if expected_phase == "pre" else 0)
            for key, expected in (("sim_ns", expected_ns), ("dt_ns", 1_000_000), ("state_time_ns", expected_state_ns)):
                if type(row[key]) is not int or row[key] != expected:
                    raise ValueError("invalid clock/step: " + key)
            if row["phase"] != expected_phase or row["available"] is not True:
                raise ValueError("unavailable or reordered reference")
            wall = row["wall_ns"]
            if type(wall) is not int or not 0 < wall < 2**63 or wall < last_wall:
                raise ValueError("invalid reference wall clock")
            last_wall = wall
            _state(row)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"invalid reference record {index}: {exc}") from exc

    post = rows[1::2]
    position = np.array([r["position"] for r in post], dtype=float)
    velocity = np.array([r["velocity_world"] for r in post], dtype=float)
    acceleration = np.array([r["accel_world"] for r in post], dtype=float)
    dv_error = acceleration[1:] * 0.001 - np.diff(velocity, axis=0)
    dp_error = velocity[1:] * 0.001 - np.diff(position, axis=0)
    if not np.isfinite(dv_error).all() or not np.isfinite(dp_error).all():
        raise ValueError("nonfinite reference arithmetic")
    runs = []

    def finish_run(start, end):
        duration = post[end]["sim_ns"] - post[start]["sim_ns"]
        if duration < 100_000_000:
            return
        speed = max(_norm(r["velocity_world"]) for r in post[start : end + 1])
        accel = max(_norm(r["accel_world"]) for r in post[start : end + 1])
        if speed <= 0.001 and accel <= 0.01:
            return
        runs.append(
            dict(
                start_ns=post[start]["sim_ns"],
                end_ns=post[end]["sim_ns"],
                duration_ns=duration,
                samples=end - start + 1,
                reported_speed_max_m_s=speed,
                reported_accel_max_m_s2=accel,
                first_sample=post[start],
                last_sample=post[end],
                right_accel_velocity_residual_m_s=_sum(dv_error[start:end]),
                right_velocity_position_residual_m=_sum(dp_error[start:end]),
            )
        )

    begin = 0
    for i in range(1, len(post)):
        if post[i]["position"] != post[begin]["position"] or post[i]["quaternion_xyzw"] != post[begin]["quaternion_xyzw"]:
            finish_run(begin, i - 1)
            begin = i
    finish_run(begin, len(post) - 1)
    return dict(
        records=len(rows),
        post_samples=len(post),
        start_ns=post[0]["sim_ns"],
        end_ns=post[-1]["sim_ns"],
        classification="internally_inconsistent_reference" if runs else "indeterminate",
        contradictory_pose_runs=runs,
        max_acceleration_velocity_residual_m_s=max(_norm(v) for v in dv_error),
        max_velocity_position_residual_m=max(_norm(v) for v in dp_error),
        state_time_basis="callback_phase_only",
        component_refresh_verified=False,
        installed_runtime_cause_proven=False,
        overall_sensor_consistency_qualified=False,
        eligible_for_px4_fusion=False,
        limits=dict(exact_pose_run_min_ns=100_000_000, speed_m_s=0.001, acceleration_m_s2=0.01),
        scope="sampled diagnostic consistency only; aliasing and backend refresh require separate evidence",
    )
