from __future__ import annotations

import pytest

from tools.benchmark.prepare_openvins_delayed_feed import trim_streams, verify_source_hashes


def _imu(stamps: list[int]) -> list[dict]:
    return [{"timestamp_us": str(t), "gx": "0.1", "gy": "0", "gz": "0",
             "ax": "0", "ay": "0", "az": "-9.8"} for t in stamps]


def _frames(stamps: list[int]) -> list[dict]:
    return [{"timestamp_ns": str(t), "relative_ppm_path": f"rgb-frames/{t}.ppm"}
            for t in stamps]


def test_trim_preserves_original_rows_and_includes_cutoff_boundary() -> None:
    imu = _imu([28_900_000, 29_000_000, 29_050_000, 29_100_000])
    frames = _frames([28_900_000_000, 29_000_000_000, 29_100_000_000])
    kept_imu, kept_frames = trim_streams(imu, frames, 29_000_000_000, min_imu=2,
                                          min_frames=2)
    assert kept_imu == imu[1:]
    assert kept_frames == frames[1:]
    assert kept_imu[0] is imu[1]


def test_trim_rejects_nonmonotonic_or_nonfinite_imu() -> None:
    with pytest.raises(ValueError, match="IMU.*increasing"):
        trim_streams(_imu([29_000_000, 29_000_000]), _frames([29_000_000_000]),
                     29_000_000_000, min_imu=1, min_frames=1)
    imu = _imu([29_000_000, 29_100_000])
    imu[1]["ax"] = "nan"
    with pytest.raises(ValueError, match="IMU.*finite"):
        trim_streams(imu, _frames([29_000_000_000]), 29_000_000_000,
                     min_imu=1, min_frames=1)


def test_trim_rejects_unsynchronized_or_unsafe_frame_path() -> None:
    with pytest.raises(ValueError, match="image.*IMU"):
        trim_streams(_imu([29_000_000, 29_100_000]),
                     _frames([29_200_000_000]), 29_000_000_000,
                     min_imu=1, min_frames=1)
    bad = _frames([29_000_000_000])
    bad[0]["relative_ppm_path"] = "../other.ppm"
    with pytest.raises(ValueError, match="frame path"):
        trim_streams(_imu([29_000_000, 29_100_000]), bad, 29_000_000_000,
                     min_imu=1, min_frames=1)


def test_trim_rejects_short_or_nonmonotonic_frames() -> None:
    with pytest.raises(ValueError, match="image.*increasing"):
        trim_streams(_imu([29_000_000, 29_100_000]),
                     _frames([29_000_000_000, 29_000_000_000]), 29_000_000_000,
                     min_imu=1, min_frames=1)
    with pytest.raises(ValueError, match="too short"):
        trim_streams(_imu([29_000_000, 29_100_000]),
                     _frames([29_000_000_000]), 29_000_000_000,
                     min_imu=3, min_frames=2)


def test_source_hash_check_rejects_changed_capture(tmp_path) -> None:
    import hashlib

    source = tmp_path / "imu.csv"
    source.write_bytes(b"frozen")
    manifest = {"imu_csv_sha256": hashlib.sha256(b"frozen").hexdigest()}
    verify_source_hashes(manifest, {"imu_csv_sha256": source})
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_source_hashes(manifest, {"imu_csv_sha256": source})
