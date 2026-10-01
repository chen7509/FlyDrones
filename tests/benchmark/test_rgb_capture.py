import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from flydrones.benchmark.gateway import NativeGazeboPx4Backend
from flydrones.benchmark.rgb_capture import (
    RgbFrameRecorder,
    rgb_capture_failures,
    verify_rgb_manifest,
)


def test_rgb_recorder_preserves_raw_bytes_timestamp_and_hash(tmp_path):
    recorder = RgbFrameRecorder(tmp_path)
    frame = np.arange(6, dtype=np.uint8).reshape(1, 2, 3)

    assert recorder.add(1_000_000_000, frame)
    summary = recorder.finish()
    payload = (tmp_path / summary["frames"][0]["path"]).read_bytes()

    assert payload == b"P6\n2 1\n255\n" + frame.tobytes()
    assert summary["frames"][0]["frame_ns"] == 1_000_000_000
    assert summary["frames"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert summary["out_of_order_drops"] == 0


def test_rgb_recorder_counts_repeated_or_backwards_time(tmp_path):
    recorder = RgbFrameRecorder(tmp_path)
    frame = np.zeros((1, 1, 3), dtype=np.uint8)

    assert recorder.add(100, frame)
    assert not recorder.add(100, frame)
    assert not recorder.add(99, frame)
    assert recorder.finish()["out_of_order_drops"] == 2
    assert not recorder.add(101, frame)


def test_rgb_recorder_rejects_invalid_shape_and_evidence_overwrite(tmp_path):
    recorder = RgbFrameRecorder(tmp_path)
    with pytest.raises(ValueError, match="RGB shape"):
        recorder.add(1, np.zeros((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="positive"):
        recorder.add(0, np.zeros((1, 1, 3), dtype=np.uint8))
    recorder.add(1, np.zeros((1, 1, 3), dtype=np.uint8))
    recorder.finish()
    with pytest.raises(FileExistsError):
        recorder.finish()


def test_backend_opt_in_records_camera_message_without_pose(tmp_path):
    backend = NativeGazeboPx4Backend(tmp_path, tmp_path / "episode", {"goal": [0, 0, 1]}, record_rgb=True)
    message = SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(sec=2, nsec=5)),
        height=1, width=2, data=bytes(range(6)),
    )

    backend._on_image("rgb")(message)
    backend.close()

    assert backend.rgb_capture_summary["frames"][0]["frame_ns"] == 2_000_000_005
    assert (tmp_path / "episode/rgb-frames/2000000005.ppm").is_file()


def test_optional_rgb_gate_fails_closed_when_requested():
    assert rgb_capture_failures(None, None, required=False) == []
    assert rgb_capture_failures(None, None, required=True) == ["rgb_capture_missing"]
    assert rgb_capture_failures({"frames": []}, None, required=True) == ["rgb_capture_missing"]
    assert rgb_capture_failures({"frames": [{}], "out_of_order_drops": 1}, None,
                                required=True) == ["rgb_capture_nonmonotonic"]
    assert rgb_capture_failures({"frames": [{}]}, "write failed", required=True) == ["rgb_capture_error"]


def test_rgb_manifest_rechecks_saved_frame_bytes(tmp_path):
    recorder = RgbFrameRecorder(tmp_path)
    recorder.add(10, np.zeros((1, 1, 3), dtype=np.uint8))
    recorder.finish()
    assert len(verify_rgb_manifest(tmp_path)["frames"]) == 1

    (tmp_path / "rgb-frames/10.ppm").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed RGB frame"):
        verify_rgb_manifest(tmp_path)
