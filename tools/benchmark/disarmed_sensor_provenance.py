"""Live sensor evidence primitives; no estimator, flight commands or fusion permission."""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
from collections import Counter

import numpy as np

from flydrones.benchmark.camera_info_capture import CameraInfoRecorder
from flydrones.benchmark.rgb_capture import RgbFrameRecorder


def validate_event(event, *, allow_legacy_info=False):
    common = {"kind", "arrival_monotonic_ns", "observed_sim_ns"}
    fields = {
        "imu": {"sample_ns", "gyro_flu", "accel_flu"},
        "rgb": {"sample_ns", "width", "height"},
        "depth": {"sample_ns", "width", "height"},
        "info": {"camera_info", "sample_ns"},
        "heartbeat": {"system_id", "base_mode", "custom_mode"},
    }
    kind = event.get("kind")
    if allow_legacy_info and kind == "info" and "sample_ns" not in event:
        fields["info"] = {"camera_info"}
    if kind not in fields or set(event) != common | fields[kind]:
        raise ValueError("unexpected sensor event fields")
    for key in ["arrival_monotonic_ns", "observed_sim_ns"] + (["sample_ns"] if "sample_ns" in event else []):
        if type(event[key]) is not int or event[key] < (0 if key == "observed_sim_ns" else 1):
            raise ValueError("invalid event clock")
    result = dict(event)
    if "sample_ns" in event:
        result["sim_age_at_callback_ns"] = event["observed_sim_ns"] - event["sample_ns"]
    if kind == "imu":
        for source, target in [("gyro_flu", "gyro_frd"), ("accel_flu", "accel_frd")]:
            values = event[source]
            if (
                not isinstance(values, (list, tuple))
                or len(values) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            ):
                raise ValueError("invalid IMU vector")
            result[source] = list(values)
            result[target] = [values[0], -values[1], -values[2]]
    if kind in ("rgb", "depth") and (event["width"] != 160 or event["height"] != 120):
        raise ValueError("unexpected sensor resolution")
    if kind == "heartbeat":
        if any(type(event[k]) is not int for k in ("system_id", "base_mode", "custom_mode")):
            raise ValueError("invalid heartbeat")
        if event["base_mode"] & 128:
            raise ValueError("armed heartbeat during disarmed capture")
    return result


class CaptureWriter:
    def __init__(self, output, *, capacity=4096, start_worker=True, on_record=None):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid queue capacity")
        self.output = output
        self.stream = (output / "events.jsonl").open("x", encoding="utf8")
        self.rgb = RgbFrameRecorder(output)
        self.info = CameraInfoRecorder(output, topic="/benchmark/rgbd/camera_info")
        self.queue = queue.Queue(capacity)
        self.lock = threading.Lock()
        self.last = {}
        self.written = Counter()
        self.error = None
        self.closed = False
        self.thread = None
        self.max_queue = 0
        self.on_record = on_record
        if start_worker:
            self.start()

    def start(self):
        if self.thread is not None:
            raise RuntimeError("writer already started")
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, event, payload=None):
        row = validate_event(event)
        if row["kind"] == "rgb" and (not isinstance(payload, bytes) or len(payload) != 160 * 120 * 3):
            raise ValueError("invalid RGB payload")
        if row["kind"] == "info" and (not isinstance(payload, bytes) or not payload):
            raise ValueError("invalid camera info payload")
        with self.lock:
            if self.closed or self.error:
                raise RuntimeError("writer unavailable: " + str(self.error))
            kind = row["kind"]
            if "sample_ns" in row and row["sample_ns"] <= self.last.get(kind, -1):
                raise ValueError("duplicate/regressed " + kind + " timestamp")
            try:
                self.queue.put_nowait((row, payload))
            except queue.Full as exc:
                raise RuntimeError("capture queue overflow") from exc
            if "sample_ns" in row:
                self.last[kind] = row["sample_ns"]
            self.max_queue = max(self.max_queue, self.queue.qsize())

    def _write_event(self, row, payload):
        row["writer_begin_monotonic_ns"] = time.monotonic_ns()
        if row["kind"] == "rgb":
            accepted = self.rgb.add(row["sample_ns"], np.frombuffer(payload, dtype=np.uint8).reshape(120, 160, 3))
            if not accepted:
                raise ValueError("RGB recorder rejected frame")
        if row["kind"] == "info":
            self.info.add(row["camera_info"], payload)
            directory = self.output / "camera-info-messages"
            directory.mkdir(exist_ok=True)
            relative = "camera-info-messages/" + str(row["sample_ns"]) + ".pb"
            with (self.output / relative).open("xb") as stream:
                stream.write(payload)
            row["payload_path"] = relative
            row["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        # This is record preparation time, not filesystem durability or sensor-generation wall time.
        row["recorded_monotonic_ns"] = time.monotonic_ns()
        encoded = json.dumps(row, allow_nan=False) + "\n"
        if self.stream.write(encoded) != len(encoded):
            raise OSError("short sensor event write")
        self.written[row["kind"]] += 1
        if self.on_record is not None:
            self.stream.flush()
            self.on_record(dict(row), payload)

    def _worker(self):
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                self._write_event(*item)
        except BaseException as exc:
            self.error = repr(exc)
        finally:
            try:
                self.stream.close()
            except OSError as exc:
                self.error = repr(exc)

    def finish(self):
        with self.lock:
            self.closed = True
        if self.thread is None:
            self.start()
        deadline = time.monotonic() + 30
        while not self.error:
            try:
                self.queue.put(None, timeout=0.1)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    raise TimeoutError("writer drain timeout") from None
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise TimeoutError("writer did not finish")
        if self.error:
            raise RuntimeError(self.error)
        rgb, info = self.rgb.finish(), self.info.finish()
        return {
            "written": dict(self.written),
            "max_queue_depth": self.max_queue,
            "rgb": rgb,
            "camera_info": info,
            "timing_scope": "callback arrival to record preparation, not end-to-end latency",
        }


def compare_imu(imu_rows, px4_us, px4_gyro, px4_accel):
    """Nearest raw-time diagnostic only. No timestamp offset fitting or equivalence grant."""
    raw_us = np.array([r["sample_ns"] / 1000 for r in imu_rows])
    px4_us = np.asarray(px4_us)
    gyro, accel = np.asarray(px4_gyro), np.asarray(px4_accel)
    if (
        len(raw_us) < 2
        or len(px4_us) < 2
        or gyro.shape != (len(px4_us), 3)
        or accel.shape != gyro.shape
        or not np.isfinite(gyro).all()
        or not np.isfinite(accel).all()
        or not np.all(np.diff(raw_us) > 0)
        or not np.all(np.diff(px4_us) > 0)
    ):
        raise ValueError("invalid IMU comparison inputs")
    indices = np.searchsorted(raw_us, px4_us)
    indices = np.clip(indices, 1, len(raw_us) - 1)
    before = indices - 1
    use_before = abs(raw_us[before] - px4_us) <= abs(raw_us[indices] - px4_us)
    nearest = np.where(use_before, before, indices)
    valid = (px4_us >= raw_us[0]) & (px4_us <= raw_us[-1] + 4000) & (abs(px4_us - raw_us[nearest]) <= 4000)
    if not np.any(valid):
        raise ValueError("no temporally overlapping IMU samples")
    paired = nearest[valid]
    raw_g = np.array([r["gyro_flu"] for r in imu_rows]) * [1, -1, -1]
    raw_a = np.array([r["accel_flu"] for r in imu_rows]) * [1, -1, -1]
    g_error, a_error = abs(gyro[valid] - raw_g[paired]), abs(accel[valid] - raw_a[paired])
    return {
        "paired_samples": int(valid.sum()),
        "unpaired_px4_samples": int((~valid).sum()),
        "reused_raw_indices": int(len(paired) - len(set(paired))),
        "median_px4_minus_gz_us": float(np.median(px4_us[valid] - raw_us[paired])),
        "gyro_absolute_error_max": float(g_error.max()),
        "accel_absolute_error_max": float(a_error.max()),
        "gyro_absolute_error_median": float(np.median(g_error)),
        "accel_absolute_error_median": float(np.median(a_error)),
        "source_equivalence_qualified": False,
        "method": "nearest sample timestamp within4ms; no offset fitting; PX4 callback timestamp/integration differ",
    }


def audit_event_records(rows, *, required_kinds, allow_legacy_info=False):
    """Recheck recorded clocks, transforms and completeness before using diagnostics."""
    generated = {
        "gyro_frd",
        "accel_frd",
        "sim_age_at_callback_ns",
        "writer_begin_monotonic_ns",
        "recorded_monotonic_ns",
        "payload_path",
        "payload_sha256",
    }
    counts = Counter()
    last_sample = {}
    last_recorded = 0
    for row in rows:
        base = {k: v for k, v in row.items() if k not in generated}
        expected = validate_event(base, allow_legacy_info=allow_legacy_info)
        if row["kind"] == "info" and "sample_ns" in row:
            digest = row.get("payload_sha256", "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid camera info payload digest")
            expected.update(payload_path="camera-info-messages/" + str(row["sample_ns"]) + ".pb", payload_sha256=digest)
        begin, end = row.get("writer_begin_monotonic_ns"), row.get("recorded_monotonic_ns")
        if (
            type(begin) is not int
            or type(end) is not int
            or begin < row["arrival_monotonic_ns"]
            or end < begin
            or begin < last_recorded
        ):
            raise ValueError("recorded wall-clock ordering invalid")
        expected.update(writer_begin_monotonic_ns=begin, recorded_monotonic_ns=end)
        if expected != row:
            raise ValueError("changed derived fields or unexpected record data")
        kind = row["kind"]
        if "sample_ns" in row:
            if row["sample_ns"] <= last_sample.get(kind, -1):
                raise ValueError("duplicate/regressed recorded sample")
            last_sample[kind] = row["sample_ns"]
        last_recorded = end
        counts[kind] += 1
    if not set(required_kinds) <= set(counts):
        raise ValueError("required sensor stream missing")
    return dict(counts)


class CaptureJournal:
    """Run all registered owned-resource cleanups and attempt a terminal result."""

    def __init__(self, output, result):
        self.output, self.result = output, result
        self.callbacks = []

    def __enter__(self):
        return self

    def cleanup(self, label, callback, *, priority):
        self.callbacks.append((priority, label, callback))

    def __exit__(self, kind, value, traceback):
        if value is not None:
            self.result["errors"].append(repr(value))
        for _, label, callback in sorted(self.callbacks, key=lambda item: item[0]):
            try:
                callback()
            except Exception as exc:
                self.result["errors"].append(label + ": " + repr(exc))
        if self.result["errors"] or self.result["status"] != "capture_completed":
            self.result["status"] = "capture_failed"
        with (self.output / "result.json").open("x") as stream:
            json.dump(self.result, stream, indent=2)
        return value is not None


def terminate_owned_group(worker):
    """POSIX only: worker was created as a fresh session/process-group leader."""
    try:
        os.killpg(worker.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        worker.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # A child may remain even if the group leader exited on SIGTERM.
    try:
        os.killpg(worker.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise_worker(command, output, *, timeout_s=300, spawn=None, terminate=None):
    if output.exists():
        raise FileExistsError(output)
    if spawn is None:
        if os.name != "posix":
            raise RuntimeError("physical capture supervisor requires POSIX process groups")

        def spawn(command):
            return subprocess.Popen(command, start_new_session=True)

    terminate = terminate or terminate_owned_group
    worker = spawn(command)
    status = "worker_exited"
    try:
        code = worker.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        status = "supervisor_timeout"
        terminate(worker)
        code = worker.wait(timeout=5)
    else:
        # Reap only surviving descendants in this dedicated worker group.
        terminate(worker)
    output.mkdir(parents=True, exist_ok=True)
    summary = {"status": status, "worker_pid": worker.pid, "worker_exit": code, "timeout_s": timeout_s}
    if not (output / "result.json").exists():
        with (output / "result.json").open("x") as stream:
            json.dump(
                {
                    "status": "capture_failed",
                    "errors": [status + ": worker left no terminal result"],
                    "estimator_run": False,
                    "eligible_for_px4_fusion": False,
                },
                stream,
                indent=2,
            )
    summary["capture_status"] = json.loads((output / "result.json").read_text())["status"]
    with (output / "supervisor.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
    return summary
