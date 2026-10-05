import copy

import pytest

from tools.benchmark.diagnostic_reference_freshness import analyze_reference
from tools.benchmark.physics_substep_trace import SubstepTrace


def traces(kind="static", count=201):
    rows = []
    for i in range(1, count + 1):
        for phase, step in [("pre", i - 1), ("post", i)]:
            t = step * 0.001
            acceleration = 2.0 if kind in ("accelerating", "cached") else 0.0
            velocity = 2 * t if kind == "accelerating" else 1.0 if kind == "cached" else 0.0
            position = step * (step + 1) * 0.000001 if kind == "accelerating" else 0.0
            rows.append(
                dict(
                    phase=phase,
                    sim_ns=i * 1_000_000,
                    dt_ns=1_000_000,
                    state_time_ns=step * 1_000_000,
                    wall_ns=len(rows) + 1,
                    available=True,
                    position=[position, 0.0, 0.0],
                    velocity_world=[velocity, 0.0, 0.0],
                    accel_world=[acceleration, 0.0, 0.0],
                    angular_world=[0.0, 0.0, 0.0],
                    quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
                )
            )
    return rows


@pytest.mark.parametrize("kind", ["static", "accelerating"])
def test_consistent_motion_is_not_freshness_certification(kind):
    out = analyze_reference(traces(kind))
    assert out["contradictory_pose_runs"] == []
    assert out["classification"] == "indeterminate"
    assert out["max_acceleration_velocity_residual_m_s"] < 1e-12
    assert out["max_velocity_position_residual_m"] < 1e-12
    assert out["component_refresh_verified"] is False
    assert out["eligible_for_px4_fusion"] is False


def test_cached_pose_with_nonzero_dynamics_is_retained():
    out = analyze_reference(traces("cached"))
    assert out["classification"] == "internally_inconsistent_reference"
    assert len(out["contradictory_pose_runs"]) == 1
    run = out["contradictory_pose_runs"][0]
    assert run["start_ns"] == 1_000_000 and run["end_ns"] == 201_000_000
    assert run["duration_ns"] == 200_000_000
    assert run["reported_speed_max_m_s"] == 1
    assert out["max_acceleration_velocity_residual_m_s"] == pytest.approx(0.002)
    assert out["max_velocity_position_residual_m"] == pytest.approx(0.001)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "order",
        "booltime",
        "floatstep",
        "rewindwall",
        "unavailable",
        "nan",
        "quaternion",
        "state_time",
        "truncated",
        "empty",
    ],
)
def test_invalid_reference_refused(fault):
    rows = copy.deepcopy(traces())
    if fault == "missing":
        del rows[40]
    if fault == "order":
        rows[40], rows[41] = rows[41], rows[40]
    if fault == "booltime":
        rows[40]["sim_ns"] = True
    if fault == "floatstep":
        rows[40]["dt_ns"] = 1000000.0
    if fault == "rewindwall":
        rows[40]["wall_ns"] = 1
    if fault == "unavailable":
        rows[40]["available"] = False
    if fault == "nan":
        rows[40]["velocity_world"][0] = float("nan")
    if fault == "quaternion":
        rows[40]["quaternion_xyzw"] = [0, 0, 0, 0]
    if fault == "state_time":
        rows[40]["state_time_ns"] += 1
    if fault == "truncated":
        rows.pop()
    if fault == "empty":
        rows = []
    with pytest.raises(ValueError):
        analyze_reference(rows)


def test_new_trace_explicitly_disclaims_backend_timestamp(tmp_path):
    trace = SubstepTrace(tmp_path)
    row = traces()[0]
    trace.record("pre", 1_000_000, 1_000_000, row, 1)
    trace.stream.close()
    import json

    logged = json.loads((tmp_path / "physics-substeps.jsonl").read_text())
    assert logged["state_time_basis"] == "callback_phase_only"
    assert logged["component_refresh_verified"] is False


@pytest.mark.parametrize("kind", ["sum", "norm"])
def test_finite_inputs_with_overflowing_aggregates_refused(kind):
    rows = traces(count=2001)
    for row in rows:
        if kind == "sum":
            row["accel_world"] = [1e308, 0.0, 0.0]
        else:
            row["velocity_world"] = [1.1e308] * 3
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_reference(rows)
