import pytest

from flydrones.runtime_timing import percentile, summarize_gap_series
from tools.probe_gazebo_runtime_wsl import parse_nvidia_smi, read_proc_metrics


@pytest.mark.parametrize(
    ("values", "quantile", "expected"),
    [
        ([], 0.95, None),
        ([17.5], 0.99, 17.5),
        ([40, 10, 30, 20], 0.50, 20.0),
        ([1, 2, 3, 4, 5], 0.95, 5.0),
    ],
)
def test_percentile_uses_nearest_rank(values, quantile, expected):
    assert percentile(values, quantile) == expected


def test_gap_summary_preserves_startup_stall_but_excludes_it_from_steady_state():
    rows = [
        {"monotonic_s": "1.0", "wall_gap_ms": "600"},
        {"monotonic_s": "10.0", "wall_gap_ms": "20"},
        {"monotonic_s": "10.1", "wall_gap_ms": "80"},
        {"monotonic_s": "10.35", "wall_gap_ms": "250"},
    ]

    summary = summarize_gap_series(rows, epoch_start_s=10.0)

    assert summary["full_run"]["max_ms"] == 600.0
    assert summary["full_run"]["at_or_over_250_ms"] == 2
    assert summary["steady_state_valid"]
    assert summary["steady_state"]["max_ms"] == 250.0
    assert summary["steady_state"]["p50_ms"] == 80.0
    assert summary["steady_state"]["at_or_over_100_ms"] == 1


def test_missing_epoch_never_treats_full_run_as_steady_state():
    summary = summarize_gap_series(
        [{"monotonic_s": "1.0", "wall_gap_ms": "20"}],
        epoch_start_s=None,
    )

    assert not summary["steady_state_valid"]
    assert summary["steady_state"] is None
    assert summary["full_run"]["max_ms"] == 20.0


def test_process_metrics_read_cpu_rss_and_thread_count(tmp_path):
    process = tmp_path / "17"
    process.mkdir()
    fields = ["0"] * 50
    fields[13] = "200"
    fields[14] = "100"
    fields[19] = "7"
    (process / "stat").write_text("17 (gz sim) S " + " ".join(fields[3:]) + "\n", encoding="utf-8")
    (process / "statm").write_text("1000 25 0 0 0 0 0\n", encoding="utf-8")

    metrics = read_proc_metrics(17, proc_root=tmp_path, clock_ticks=100, page_size=4096)

    assert metrics == {"cpu_user_s": 2.0, "cpu_system_s": 1.0, "rss_bytes": 102400, "threads": 7}


def test_nvidia_metrics_remain_unavailable_instead_of_becoming_zero():
    assert parse_nvidia_smi("") == {
        "gpu_utilization_percent": "unavailable",
        "memory_used_mib": "unavailable",
    }
    assert parse_nvidia_smi("37, 812\n") == {
        "gpu_utilization_percent": 37.0,
        "memory_used_mib": 812.0,
    }
