"""Opt-in Gazebo camera-info capture; calibration evidence, not VIO output."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path


def camera_info_fields(message) -> dict:
    """Extract stable calibration fields from a Gazebo CameraInfo protobuf."""
    frame_values = [value for entry in message.header.data if entry.key == "frame_id"
                    for value in entry.value]
    return {
        "width": int(message.width),
        "height": int(message.height),
        "frame_id": frame_values[0] if len(frame_values) == 1 else "",
        "intrinsics_k": list(message.intrinsics.k),
        "projection_p": list(message.projection.p),
        "distortion_model": int(message.distortion.model),
        "distortion_k": list(message.distortion.k),
    }


def _validate(fields: dict) -> None:
    if fields.get("width", 0) <= 0 or fields.get("height", 0) <= 0:
        raise ValueError("camera-info dimensions invalid")
    k, p = fields.get("intrinsics_k"), fields.get("projection_p")
    if (not isinstance(k, list) or len(k) != 9 or not isinstance(p, list) or len(p) != 12
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in k + p)
            or k[0] <= 0 or k[4] <= 0):
        raise ValueError("camera-info intrinsics/projection invalid")
    if not isinstance(fields.get("frame_id"), str) or not fields["frame_id"]:
        raise ValueError("camera-info frame_id missing")


def camera_info_capture_failures(summary: dict | None, error: str | None,
                                 *, required: bool) -> list[str]:
    if not required:
        return []
    if error is not None:
        return ["camera_info_error"]
    if summary is None or not summary.get("message_count"):
        return ["camera_info_missing"]
    if summary.get("changed_stable_fields"):
        return ["camera_info_changed"]
    return []


def verify_camera_info_capture(output: Path) -> dict:
    output = Path(output)
    summary = json.loads((output / "camera-info.json").read_text(encoding="utf-8"))
    if summary.get("schema") != "flydrones-camera-info-v1" or not summary.get("message_count"):
        raise ValueError("camera-info manifest missing")
    _validate(summary["camera_info"])
    if hashlib.sha256((output / "camera-info.pb").read_bytes()).hexdigest() != summary["first_message_sha256"]:
        raise ValueError("camera-info protobuf hash mismatch")
    return summary


class CameraInfoRecorder:
    def __init__(self, output: Path, *, topic: str):
        self.output = Path(output)
        self.topic = topic
        self.first_fields: dict | None = None
        self.first_payload: bytes | None = None
        self.message_count = 0
        self.changed_stable_fields = 0
        self._closed = False
        self._lock = threading.Lock()

    def add(self, fields: dict, payload: bytes) -> None:
        _validate(fields)
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("camera-info protobuf missing")
        with self._lock:
            if self._closed:
                raise RuntimeError("camera-info capture already finalized")
            if self.first_fields is None:
                self.first_fields = fields.copy()
                self.first_payload = payload
            elif fields != self.first_fields:
                self.changed_stable_fields += 1
            self.message_count += 1

    def finish(self) -> dict:
        with self._lock:
            if self._closed:
                raise FileExistsError("camera-info capture already finalized")
            self.output.mkdir(parents=True, exist_ok=True)
            digest = None
            if self.first_payload is not None:
                with (self.output / "camera-info.pb").open("xb") as stream:
                    stream.write(self.first_payload)
                digest = hashlib.sha256(self.first_payload).hexdigest()
            summary = {
                "schema": "flydrones-camera-info-v1",
                "topic": self.topic,
                "message_count": self.message_count,
                "changed_stable_fields": self.changed_stable_fields,
                "first_message_sha256": digest,
                "camera_info": self.first_fields,
            }
            with (self.output / "camera-info.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
            self._closed = True
            return summary
