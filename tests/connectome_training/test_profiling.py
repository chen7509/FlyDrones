from types import SimpleNamespace

import pytest

from flydrones.connectome_training.profiling import profile_controller, summarize_latency


def test_latency_summary_has_interpolated_percentiles_and_components():
    samples = [
        {"elapsed_wall_s": 0.10, "brain_wall_s": 0.08},
        {"elapsed_wall_s": 0.20, "brain_wall_s": 0.15},
        {"elapsed_wall_s": 0.30, "brain_wall_s": 0.22},
        {"elapsed_wall_s": 0.40, "brain_wall_s": 0.29},
    ]
    result = summarize_latency(samples)
    assert result["samples"] == 4
    assert result["total_s"]["mean"] == pytest.approx(0.25)
    assert result["total_s"]["p95"] == pytest.approx(0.385)
    assert result["neural_s"]["p99"] > result["neural_s"]["p95"]
    assert result["overhead_s"]["mean"] == pytest.approx(0.065)


def test_empty_latency_samples_are_rejected():
    with pytest.raises(ValueError, match="at least one latency sample"):
        summarize_latency([])


def test_missing_total_latency_is_rejected():
    with pytest.raises(ValueError, match="elapsed_wall_s"):
        summarize_latency([{"brain_wall_s": 0.1}])


@pytest.mark.parametrize("value", [-0.1, True, "0.1", float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["elapsed_wall_s", "brain_wall_s"])
def test_invalid_duration_cannot_enter_statistics(field, value):
    row = {"elapsed_wall_s": 0.2, "brain_wall_s": 0.1, field: value}
    with pytest.raises(ValueError):
        summarize_latency([row])


def test_component_larger_than_reported_total_is_not_silently_clipped():
    with pytest.raises(ValueError):
        summarize_latency([{"elapsed_wall_s": 0.1, "brain_wall_s": 0.2}])


def test_profiler_retains_outer_call_times_separately_from_self_report(monkeypatch):
    # Clock substitution avoids scheduler-dependent sleep tests. The controller
    # deliberately underreports; only the external 100 ms measurement is evidence.
    ticks = iter([1_000_000_000, 1_100_000_000])
    monkeypatch.setattr("time.perf_counter_ns", lambda: next(ticks))
    controller = SimpleNamespace(step=lambda obs: SimpleNamespace(
        elapsed_wall_s=0.001, evidence={"brain_wall_s": 0.0005}
    ))
    result = profile_controller(controller, [SimpleNamespace(sim_ns=50_000_000)])
    assert result["outer_s"]["p95"] == pytest.approx(0.1)
    assert result["total_s"]["p95"] == pytest.approx(0.001)
    row = result["raw_samples"][0]
    assert row["started_perf_ns"] == 1_000_000_000
    assert row["finished_perf_ns"] == 1_100_000_000
    assert row["sim_ns"] == 50_000_000
    assert row["elapsed_wall_s"] == 0.001


def test_outer_clock_regression_refuses(monkeypatch):
    ticks = iter([2, 1])
    monkeypatch.setattr("time.perf_counter_ns", lambda: next(ticks))
    controller = SimpleNamespace(step=lambda obs: SimpleNamespace(
        elapsed_wall_s=0., evidence={"brain_wall_s": 0.}
    ))
    with pytest.raises(ValueError, match="clock"):
        profile_controller(controller, [SimpleNamespace(sim_ns=1)])
