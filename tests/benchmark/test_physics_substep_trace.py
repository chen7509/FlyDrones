import io
import json

import numpy as np
import pytest

from tools.benchmark.capture_disarmed_sensors import parse_capture_args
from tools.benchmark.physics_substep_trace import SubstepTrace, phase_closures


def state(acc=0.0, vel=0.0):
    return dict(
        position=[0.0, 0.0, 0.0],
        velocity_world=[vel, 0.0, 0.0],
        accel_world=[acc, 0.0, 0.0],
        angular_world=[0.0, 0.0, 0.0],
        quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
    )


def test_record_pre_post_time_and_initial_unavailability(tmp_path):
    trace = SubstepTrace(tmp_path)
    trace.record("pre", 1_000_000, 1_000_000, None, 100)
    trace.record("post", 1_000_000, 1_000_000, state(), 101)
    trace.record("pre", 2_000_000, 1_000_000, state(), 102)
    trace.record("post", 2_000_000, 1_000_000, state(), 103)
    summary = trace.finish()
    rows = [json.loads(s) for s in (tmp_path / "physics-substeps.jsonl").read_text().splitlines()]
    assert [r["state_time_ns"] for r in rows] == [0, 1_000_000, 1_000_000, 2_000_000]
    assert rows[0]["available"] is False
    assert summary["records"] == 4 and not summary["complete"]


@pytest.mark.parametrize(
    "fault", ["phase", "duplicate", "gap", "dt", "paused-clock", "nan", "qnorm", "unavailable", "wall", "limit"]
)
def test_fault_latches(tmp_path, fault):
    trace = SubstepTrace(tmp_path)
    trace.record("pre", 1_000_000, 1_000_000, state(), 100)
    phase, ns, dt, s, wall = "post", 1_000_000, 1_000_000, state(), 101
    if fault == "phase":
        phase = "pre"
    if fault == "duplicate":
        phase = "post"
        ns = 0
    if fault == "gap":
        ns = 3_000_000
    if fault == "dt":
        dt = 2_000_000
    if fault == "paused-clock":
        ns = True
    if fault == "nan":
        s["accel_world"][0] = float("nan")
    if fault == "qnorm":
        s["quaternion_xyzw"][-1] = 2.0
    if fault == "unavailable":
        ns = 100_000_000
        s = None
    if fault == "wall":
        wall = 99
    if fault == "limit":
        trace.max_bytes = 1
    with pytest.raises(ValueError):
        trace.record(phase, ns, dt, s, wall)
    with pytest.raises(ValueError):
        trace.record("post", 1_000_000, 1_000_000, state(), 102)
    assert trace.finish()["failure"]


@pytest.mark.parametrize("fault", ["write", "short", "flush", "close"])
def test_io_failure_retains_terminal_snapshot(tmp_path, fault):
    trace = SubstepTrace(tmp_path)
    trace.stream.close()

    class Fault(io.StringIO):
        def write(self, text):
            if fault == "write":
                raise OSError("write failed")
            if fault == "short":
                return len(text) - 1
            return super().write(text)

        def flush(self):
            if fault == "flush":
                raise OSError("flush failed")

        def close(self):
            if fault == "close":
                raise OSError("close failed")
            super().close()

    trace.stream = Fault()
    if fault in ("write", "short"):
        with pytest.raises(ValueError):
            trace.record("pre", 1_000_000, 1_000_000, state(), 100)
    else:
        for i in range(1, 101):
            trace.record("pre", i * 1_000_000, 1_000_000, state(), 100 + i * 2)
            if i == 100 and fault == "flush":
                with pytest.raises(ValueError):
                    trace.record("post", i * 1_000_000, 1_000_000, state(), 101 + i * 2)
            else:
                trace.record("post", i * 1_000_000, 1_000_000, state(), 101 + i * 2)
    summary = trace.finish()
    assert summary["failure"] and summary["last_attempt"] and not summary["complete"]


def post_rows(alternating=False):
    rows = []
    v = 0.0
    for i in range(101):
        a = (1.0, -1.0, -1.0, 1.0)[i % 4] if alternating else 2.0
        if i:
            v += a * 0.001
        rows.append(dict(sim_ns=(i + 1) * 1_000_000, phase="post", available=True, **state(a, v)))
    return rows


def test_constant_acceleration_full_and_four_phases_close():
    out = phase_closures(post_rows(), 1_000_000, 101_000_000)
    assert out["full"]["right_error_norm_m_s"] < 1e-12
    assert out["full"]["trapezoid_error_norm_m_s"] < 1e-12
    assert len(out["quarter_phases"]) == 4
    assert all(p["right_error_norm_m_s"] < 1e-12 for p in out["quarter_phases"])


def test_alternating_full_rate_closes_but_all_quarter_phases_alias():
    out = phase_closures(post_rows(True), 1_000_000, 101_000_000)
    assert out["full"]["right_error_norm_m_s"] < 1e-12
    assert all(p["right_error_norm_m_s"] > 0.09 for p in out["quarter_phases"])
    assert out["root_cause_proven"] is False


@pytest.mark.parametrize("fault", ["gap", "duplicate", "nan"])
def test_analysis_rejects_bad_trace(fault):
    rows = post_rows()
    if fault == "gap":
        rows.pop(40)
    if fault == "duplicate":
        rows.insert(40, rows[40])
    if fault == "nan":
        rows[40]["accel_world"][0] = np.nan
    with pytest.raises(ValueError):
        phase_closures(rows, 1_000_000, 101_000_000)


@pytest.mark.parametrize("extra", [[], ["--shadow-binary", "x", "--shadow-config", "y"]])
def test_sensor_only_requires_explicit_consistent_mode(extra):
    with pytest.raises(SystemExit):
        parse_capture_args(["--output", "x", "--physics-trace-profile", "substep-lateral-v1"] + extra)
    with pytest.raises(SystemExit):
        parse_capture_args(["--output", "x", "--motion-profile", "lateral-wrench-v1"])


def test_explicit_sensor_only_and_old_native_modes_are_distinct():
    args = parse_capture_args(
        ["--output", "x", "--motion-profile", "lateral-wrench-v1", "--physics-trace-profile", "substep-lateral-v1"]
    )
    assert args.shadow_binary is None
    args = parse_capture_args(
        ["--output", "x", "--motion-profile", "lateral-wrench-v1", "--shadow-binary", "x", "--shadow-config", "y"]
    )
    assert args.physics_trace_profile is None
    with pytest.raises(SystemExit):
        parse_capture_args(
            [
                "--output",
                "x",
                "--motion-profile",
                "lateral-wrench-v1",
                "--physics-trace-profile",
                "substep-lateral-v1",
                "--shadow-binary",
                "x",
                "--shadow-config",
                "y",
            ]
        )
