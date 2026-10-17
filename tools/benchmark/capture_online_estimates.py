"""Consume owned native fast output during capture; never grants flight authority.

The native adapter flushes its fast file before acknowledging an IMU request.
This client consumes that exact prefix before the next source input is delivered.
Filesystem operations still require the existing outer process supervisor.
"""

from __future__ import annotations

import json
import math
import os
import stat
import time

import numpy as np

from tools.benchmark.openvins_online_shadow import NativeClient

PROFILE = "native-ack-fast-output-v1"
PERIOD_NS = 20_000_000
MAX_BYTES = 16_384


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate native prediction field")
        result[key] = value
    return result


def _secondary(primary, errors):
    """Keep secondary failures on the original exception (also on Python3.10)."""
    details = [repr(error) for error in errors]
    primary.online_estimate_cleanup_errors = details
    add_note = getattr(primary, "add_note", None)
    if add_note is not None:
        for detail in details:
            add_note("online estimate cleanup: " + detail)


class LiveEstimateNativeClient(NativeClient):
    """Same child/transport owner, plus a bounded online output consumer.

    These are raw native outputs, not calibrated controller observations.
    Quality/reset nulls and fusion eligibility false remain native facts.
    """

    def __init__(self, command, output, **kwargs):
        self._fast_path = output / "fast.jsonl"
        self._fast_fd = None
        self._next_target = None
        self._last_imu, self._last_camera = None, None
        self._camera_ack = self._last_ack = None
        self._fast_count = self._camera_count = 0
        self._feed_failure = None
        self._feed_closed = False
        # Reject old outputs before parent Popen, including dangling symlinks.
        if self._fast_path.exists() or self._fast_path.is_symlink():
            raise FileExistsError("native fast output already exists")
        self._events = (output / "online-estimates.jsonl").open("x", encoding="utf-8")
        try:
            super().__init__(command, output, **kwargs)
        except BaseException as primary:
            try:
                self._events.close()
            except BaseException as cleanup:
                _secondary(primary, [cleanup])
            raise

    def _write(self, event, **fields):
        record = dict(
            event=event, native_pid=self.process.pid, profile=PROFILE, fusion_eligible=False, controller_ready=False, **fields
        )
        self._events.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        self._events.flush()

    def _read(self):
        if self._fast_fd is None:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._fast_path, flags)
            try:
                observed = os.fstat(descriptor)
                selected = self._fast_path.lstat()
                if (
                    not stat.S_ISREG(observed.st_mode)
                    or not stat.S_ISREG(selected.st_mode)
                    or (observed.st_dev, observed.st_ino) != (selected.st_dev, selected.st_ino)
                ):
                    raise ValueError("native fast output must be the selected regular file")
            except BaseException:
                os.close(descriptor)
                raise
            self._fast_fd = descriptor
        observed, selected = os.fstat(self._fast_fd), self._fast_path.lstat()
        offset = os.lseek(self._fast_fd, 0, os.SEEK_CUR)
        if (
            not stat.S_ISREG(selected.st_mode)
            or (observed.st_dev, observed.st_ino) != (selected.st_dev, selected.st_ino)
            or observed.st_size < offset
        ):
            raise ValueError("native fast output changed/truncated")
        payload = os.read(self._fast_fd, MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("native fast output exceeds per-ack bound")
        return payload

    def _prediction(self, row, ack):
        if (
            type(row) is not dict
            or type(row.get("target_ns")) is not int
            or row["target_ns"] != self._next_target
            or type(row.get("trigger_sequence")) is not int
            or row["trigger_sequence"] != ack["sequence"]
            or type(row.get("available_imu_ns")) is not int
            or row["available_imu_ns"] != ack["sample_ns"]
            or row.get("last_camera_ns") != self._last_camera
            or row.get("fusion_eligible") is not False
            or row.get("quality") is not None
            or row.get("reset_counter") is not None
            or row.get("filter_unchanged") is not True
            or type(row.get("success")) is not bool
            or type(row.get("internal_initialized")) is not bool
            or type(row.get("public_initialized")) is not bool
            or row.get("camera_imu_offset_s") != 0.0
        ):
            raise ValueError("native prediction identity/state mismatch")
        begin, end = row.get("native_begin_ns"), row.get("native_end_ns")
        if type(begin) is not int or type(end) is not int or not ack["start_ns"] <= begin <= end <= ack["end_ns"]:
            raise ValueError("native prediction call clocks mismatch")
        for name in ("filter_time_s", "propagation_wall_s"):
            value = row.get(name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid native prediction clock")
        if row["propagation_wall_s"] < 0:
            raise ValueError("negative propagation duration")
        if row["success"]:
            if row["internal_initialized"] is not True:
                raise ValueError("successful prediction without initialization")
            for name, shape in (("state13", (13,)), ("covariance12", (12, 12))):
                array = np.asarray(row.get(name), dtype=float)
                if array.shape != shape or not np.all(np.isfinite(array)):
                    raise ValueError("invalid raw native prediction array")
        elif row.get("state13") is not None or row.get("covariance12") is not None:
            raise ValueError("unsuccessful native prediction contains state")

    def send(self, action, pixels=None):
        if self._feed_closed or self._feed_failure:
            raise RuntimeError("online estimate feed unavailable")
        started = time.monotonic()
        try:
            sample = action["sample_ns"]
            if type(sample) is not int or sample <= 0:
                raise ValueError("invalid source sample")
            imu = action["kind"] == "imu"
            if imu and self._last_imu is not None and not 0 < sample - self._last_imu <= 4_000_000:
                raise ValueError("live IMU regression/gap")
            ack = super().send(action, pixels)
            self._last_ack = ack
            if type(ack.get("sample_ns")) is not int or ack["sample_ns"] != sample:
                raise ValueError("native acknowledgement sample differs from source action")
            if self.process.poll() is not None:
                raise RuntimeError("owned native process exited")
            if self._next_target is None:
                if not imu:
                    raise ValueError("online feed requires IMU first")
                self._next_target = ((sample + PERIOD_NS - 1) // PERIOD_NS) * PERIOD_NS
            expected = imu and self._next_target < sample
            payload = self._read()
            if expected:
                if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
                    raise ValueError("missing/truncated/extra native prediction")
                row = json.loads(payload, object_pairs_hook=_pairs)
                self._prediction(row, ack)
                self._write(
                    "fast_prediction",
                    prediction=row,
                    ack=ack,
                    camera_ack_sequence=None if self._camera_ack is None else self._camera_ack["sequence"],
                )
                self._fast_count += 1
                self._next_target += PERIOD_NS
            elif payload:
                raise ValueError("unexpected native prediction without IMU target")
            if action["kind"] == "camera":
                self._last_camera, self._camera_ack = sample, ack
                self._write("camera_state", ack=ack)
                self._camera_count += 1
            if imu:
                self._last_imu = sample
            if time.monotonic() - started >= self.timeout_s:
                raise TimeoutError("native acknowledgement/output deadline")
            return ack
        except BaseException as exc:
            self._feed_failure = self.failed = repr(exc)
            try:
                self._write("failure", failure=self._feed_failure, ack=self._last_ack)
            except BaseException:
                pass  # Preserve primary failure; outer recorder retains missing journal boundary.
            raise

    def finish(self):
        if self._feed_closed:
            raise RuntimeError("online estimate feed already closed")
        self._feed_closed = True
        primary = None
        cleanup_errors = []
        try:
            result = super().finish()
            result["online_estimates"] = dict(
                profile=PROFILE,
                native_pid=self.process.pid,
                fast_predictions=self._fast_count,
                camera_states=self._camera_count,
                failure=self._feed_failure,
                fusion_eligible=False,
                controller_ready=False,
            )
        except BaseException as exc:
            primary = exc
        if self._fast_fd is not None:
            try:
                os.close(self._fast_fd)
            except BaseException as exc:
                cleanup_errors.append(exc)
            finally:
                self._fast_fd = None
        try:
            self._events.close()
        except BaseException as exc:
            cleanup_errors.append(exc)
        if primary is not None:
            _secondary(primary, cleanup_errors)
            raise primary
        if cleanup_errors:
            _secondary(cleanup_errors[0], cleanup_errors[1:])
            raise cleanup_errors[0]
        return result
