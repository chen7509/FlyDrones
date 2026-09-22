import pytest

from flydrones.connectome_training.profiling import summarize_latency


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
