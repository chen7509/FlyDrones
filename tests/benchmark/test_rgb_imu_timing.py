import pytest

from flydrones.benchmark.rgb_imu_timing import analyze_decision_window, analyze_timing


def test_timing_reports_imu_nearest_neighbor_and_frame_rate():
    result = analyze_timing([1_000_000_000, 1_100_000_000, 1_200_000_000],
                            [999_000, 1_099_000, 1_199_000, 1_201_000])

    assert result["frame_count"] == 3
    assert result["imu_count"] == 4
    assert result["median_frame_rate_hz"] == pytest.approx(10)
    assert result["nearest_imu_delta_ms_p95"] == pytest.approx(1)
    assert result["frames_inside_imu_range"] == 3
    assert result["nearest_imu_delta_ms_p95_inside_range"] == pytest.approx(1)


def test_timing_reports_unpaired_startup_frames_separately():
    result = analyze_timing([100_000_000, 1_000_000_000, 1_100_000_000],
                            [999_000, 1_099_000, 1_101_000])
    assert result["frames_outside_imu_range"] == 1
    assert result["nearest_imu_delta_ms_p95_inside_range"] == pytest.approx(1)
    assert result["nearest_imu_delta_ms_p95"] > 1


def test_timing_rejects_nonmonotonic_sources():
    with pytest.raises(ValueError, match="frame timestamps"):
        analyze_timing([2, 1], [1, 2])
    with pytest.raises(ValueError, match="IMU timestamps"):
        analyze_timing([1, 2], [2, 1])


def test_decision_window_keeps_raw_gaps_visible_but_scores_only_used_interval():
    frames = [100_000_000, 200_000_000, 300_000_000, 400_000_000, 500_000_000]
    imu_us = [195_000, 200_000, 250_000, 300_000, 350_000, 400_000, 405_000]
    decisions = [
        {"sim_ns": 200_000_000, "frame_ns": 200_000_000},
        {"sim_ns": 350_000_000, "frame_ns": 300_000_000},
        {"sim_ns": 400_000_000, "frame_ns": 400_000_000},
    ]

    report = analyze_decision_window(frames, imu_us, decisions, max_gap_ms=60)

    assert report["raw_frames_before_window"] == 1
    assert report["raw_frames_after_window"] == 1
    assert report["window_frame_count"] == 3
    assert report["window_frames_outside_imu_range"] == 0
    assert report["window_nearest_imu_delta_ms_max"] == 0
    assert report["window_imu_gap_ms_max"] == 50
    assert report["coverage_accepted"] is True


def test_decision_window_fails_on_unpaired_frame_or_large_imu_gap():
    decisions = [{"sim_ns": 100_000_000, "frame_ns": 100_000_000},
                 {"sim_ns": 300_000_000, "frame_ns": 300_000_000}]
    outside = analyze_decision_window(
        [100_000_000, 200_000_000, 300_000_000], [150_000, 250_000], decisions,
    )
    assert outside["coverage_accepted"] is False
    assert outside["window_frames_outside_imu_range"] == 2

    sparse = analyze_decision_window(
        [100_000_000, 200_000_000, 300_000_000], [100_000, 300_000],
        [{"sim_ns": 100_000_000, "frame_ns": 100_000_000},
         {"sim_ns": 300_000_000, "frame_ns": 300_000_000}],
    )
    assert sparse["window_imu_gap_ms_max"] == 200
    assert sparse["coverage_accepted"] is False


def test_decision_window_rejects_missing_frame_and_nonmonotonic_decisions():
    frames = [100, 200, 300]
    imu_us = [1, 2]
    with pytest.raises(ValueError, match="unrecorded"):
        analyze_decision_window(frames, imu_us, [{"sim_ns": 150, "frame_ns": 150},
                                                 {"sim_ns": 300, "frame_ns": 300}])
    with pytest.raises(ValueError, match="decision timestamps"):
        analyze_decision_window(frames, imu_us, [{"sim_ns": 200, "frame_ns": 100},
                                                 {"sim_ns": 100, "frame_ns": 200}])
