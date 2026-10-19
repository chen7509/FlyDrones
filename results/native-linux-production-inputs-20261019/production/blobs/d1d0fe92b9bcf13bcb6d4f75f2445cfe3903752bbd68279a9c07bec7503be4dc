"""Opt-in, truth-free RGB frame capture for a single VIO dataset preflight."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np


def rgb_capture_failures(summary: dict | None, error: str | None, *, required: bool) -> list[str]:
    if not required:
        return []
    if error is not None:
        return ["rgb_capture_error"]
    if summary is None or not summary.get("frames"):
        return ["rgb_capture_missing"]
    if summary.get("out_of_order_drops"):
        return ["rgb_capture_nonmonotonic"]
    return []


def verify_rgb_manifest(output: Path) -> dict:
    output = Path(output).resolve()
    manifest = json.loads((output / "rgb-capture-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "flydrones-rgb-capture-v1" or not manifest.get("frames"):
        raise ValueError("RGB frame manifest missing or empty")
    previous = -1
    for record in manifest["frames"]:
        frame_ns = record["frame_ns"]
        if type(frame_ns) is not int or frame_ns <= previous:
            raise ValueError("RGB frame timestamps not increasing")
        path = (output / record["path"]).resolve()
        if not path.is_relative_to(output / "rgb-frames") or not path.is_file():
            raise ValueError("RGB frame path missing or outside capture")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"changed RGB frame: {record['path']}")
        previous = frame_ns
    return manifest


class RgbFrameRecorder:
    def __init__(self, output: Path):
        self.output = Path(output)
        self.frames: list[dict] = []
        self.out_of_order_drops = 0
        self._last_frame_ns = -1
        self._closed = False
        self._lock = threading.Lock()

    def add(self, frame_ns: int, rgb: np.ndarray) -> bool:
        if type(frame_ns) is not int or frame_ns <= 0:
            raise ValueError("frame timestamp must be positive integer nanoseconds")
        if (not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3
                or rgb.shape[2] != 3 or not 0 < rgb.shape[0] <= 4096
                or not 0 < rgb.shape[1] <= 4096):
            raise ValueError("RGB shape must be HxWx3 uint8")
        with self._lock:
            if self._closed:
                return False
            if frame_ns <= self._last_frame_ns:
                self.out_of_order_drops += 1
                return False
            height, width = rgb.shape[:2]
            payload = f"P6\n{width} {height}\n255\n".encode("ascii") + np.ascontiguousarray(rgb).tobytes()
            relative = Path("rgb-frames") / f"{frame_ns}.ppm"
            destination = self.output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(payload)
            self.frames.append({
                "frame_ns": frame_ns,
                "path": relative.as_posix(),
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
            self._last_frame_ns = frame_ns
            return True

    def finish(self) -> dict:
        with self._lock:
            if self._closed:
                raise FileExistsError("RGB capture already finalized")
            summary = {
                "schema": "flydrones-rgb-capture-v1",
                "frames": self.frames,
                "out_of_order_drops": self.out_of_order_drops,
            }
            manifest = self.output / "rgb-capture-manifest.json"
            with manifest.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(summary, indent=2) + "\n")
            self._closed = True
            return summary
