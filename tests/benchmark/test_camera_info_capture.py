import hashlib
from types import SimpleNamespace

import pytest

from flydrones.benchmark.camera_info_capture import (
    CameraInfoRecorder,
    camera_info_capture_failures,
    verify_camera_info_capture,
)
from flydrones.benchmark.gateway import NativeGazeboPx4Backend


def _info(fx=110.0):
    return {
        "width": 160, "height": 120, "frame_id": "camera_link",
        "intrinsics_k": [fx, 0, 80, 0, 110, 60, 0, 0, 1],
        "projection_p": [fx, 0, 80, 0, 0, 110, 60, 0, 0, 0, 1, 0],
        "distortion_model": 0, "distortion_k": [],
    }


def test_camera_info_recorder_preserves_raw_protobuf_and_stable_fields(tmp_path):
    recorder = CameraInfoRecorder(tmp_path, topic="/benchmark/rgbd/camera_info")
    recorder.add(_info(), b"protobuf-1")
    recorder.add(_info(), b"protobuf-2-different-stamp")
    summary = recorder.finish()

    assert summary["message_count"] == 2
    assert summary["changed_stable_fields"] == 0
    assert summary["first_message_sha256"] == hashlib.sha256(b"protobuf-1").hexdigest()
    assert (tmp_path / "camera-info.pb").read_bytes() == b"protobuf-1"
    assert verify_camera_info_capture(tmp_path)["camera_info"]["intrinsics_k"][0] == 110
    assert camera_info_capture_failures(summary, None, required=True) == []


def test_camera_info_capture_fails_closed_on_missing_mutation_and_corruption(tmp_path):
    empty = CameraInfoRecorder(tmp_path / "empty", topic="/camera_info").finish()
    assert camera_info_capture_failures(empty, None, required=True) == ["camera_info_missing"]
    changed = CameraInfoRecorder(tmp_path / "changed", topic="/camera_info")
    changed.add(_info(), b"a")
    changed.add(_info(120), b"b")
    summary = changed.finish()
    assert camera_info_capture_failures(summary, None, required=True) == ["camera_info_changed"]
    assert camera_info_capture_failures(summary, "callback failed", required=True) == ["camera_info_error"]
    assert camera_info_capture_failures(None, None, required=False) == []
    (tmp_path / "changed/camera-info.pb").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash"):
        verify_camera_info_capture(tmp_path / "changed")


def test_camera_info_recorder_rejects_malformed_intrinsics(tmp_path):
    recorder = CameraInfoRecorder(tmp_path, topic="/camera_info")
    bad = _info()
    bad["intrinsics_k"] = []
    with pytest.raises(ValueError, match="intrinsics"):
        recorder.add(bad, b"bad")
    bad = _info()
    bad["width"] = 0
    with pytest.raises(ValueError, match="dimensions"):
        recorder.add(bad, b"bad")


def test_backend_records_gazebo_camera_info_without_pose(tmp_path):
    backend = NativeGazeboPx4Backend(tmp_path, tmp_path / "episode", {"goal": [0, 0, 1]},
                                    record_camera_info=True)
    message = SimpleNamespace(
        width=160, height=120,
        header=SimpleNamespace(data=[SimpleNamespace(key="frame_id", value=["camera_link"])]),
        intrinsics=SimpleNamespace(k=_info()["intrinsics_k"]),
        projection=SimpleNamespace(p=_info()["projection_p"]),
        distortion=SimpleNamespace(model=0, k=[]),
        SerializeToString=lambda: b"raw-camera-info",
    )
    backend._on_camera_info(message)
    backend.close()

    assert backend.camera_info_summary["message_count"] == 1
    assert backend.camera_info_error is None
    assert (tmp_path / "episode/camera-info.pb").read_bytes() == b"raw-camera-info"
