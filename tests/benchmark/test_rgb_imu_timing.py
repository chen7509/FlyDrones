import pytest

from flydrones.benchmark.rgb_imu_timing import analyze_timing


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
