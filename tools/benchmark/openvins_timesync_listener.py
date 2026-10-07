"""Strict bounded non-PTY listener decoder; no process/network authority.

Pinned listener ordinals count consumption, not uORB generations. A future
harness must journal raw chunks and poll check() on silence; this is not a
background watchdog or proof of source/channel ownership.
"""

from __future__ import annotations

import re
from typing import NoReturn


class TimesyncListenerDecoder:
    TIMEOUT_NS = 2_000_000_000
    MAX_CHUNK = 4096
    MAX_FRAME = 1024
    MAX_TOTAL = 4 * 1024 * 1024
    _HEADER = re.compile(rb"TOPIC: timesync_status instance (0|[1-9][0-9]{0,2}) #([1-9][0-9]{0,9})")
    _FIELDS = (
        ("timestamp", 1, 2**64-1),
        ("remote_timestamp", 1, 2**64-1),
        ("observed_offset", -(2**63), 2**63-1),
        ("estimated_offset", -(2**63), 2**63-1),
        ("round_trip_time", 0, 2**32-1),
        ("source_protocol", 0, 255),
    )
    _DECIMAL = rb"(0|-?[1-9][0-9]{0,19})"
    _PINNED_MULTI_PREFIX = b"\x1b[2J\n\x1b[H"

    def __init__(self, instance: int, expected_records: int, start_ns: int,
                 *, output_profile: str = "plain-v1"):
        if type(instance) is not int or not 0 <= instance <= 255:
            raise ValueError("invalid topic instance")
        if type(expected_records) is not int or not 1 <= expected_records <= 4096:
            raise ValueError("invalid expected records")
        if type(start_ns) is not int or not 0 <= start_ns < 2**64:
            raise ValueError("invalid starting clock")
        if type(output_profile) is not str or output_profile not in ("plain-v1", "px4-d6f12ad-multi-v1"):
            raise ValueError("invalid output profile")
        if output_profile == "px4-d6f12ad-multi-v1" and expected_records < 2:
            raise ValueError("pinned multi profile requires multiple records")
        self._profile = output_profile
        self._prefix = self._PINNED_MULTI_PREFIX if output_profile == "px4-d6f12ad-multi-v1" else b""
        self._prefix_index = 0
        self._instance = instance
        self._expected = expected_records
        self._last_now = self._last_complete = start_ns
        self._partial = b""
        self._frame_bytes = self._total = self._line = self._count = 0
        self._record: dict[str, int] = {}
        self._fault: str | None = None
        self._closed = False

    def _fail(self, reason: str) -> NoReturn:
        self._fault = reason
        raise ValueError(reason)

    def check(self, now_ns: int) -> None:
        if self._fault is not None:
            raise ValueError("listener failure latched: " + self._fault)
        if self._closed:
            raise ValueError("listener already finished")
        if type(now_ns) is not int or not 0 <= now_ns < 2**64:
            self._fail("invalid local clock")
        if now_ns < self._last_now:
            self._fail("local clock regression")
        self._last_now = now_ns
        if now_ns - self._last_complete >= self.TIMEOUT_NS:
            self._fail("listener complete-frame timeout")

    def _accept_line(self, line: bytes) -> dict | None:
        if self._count == self._expected:
            self._fail("extra record or trailing data")
        if self._line == 0:
            if line != b"":
                self._fail("listener preamble or diagnostic")
        elif self._line == 1:
            match = self._HEADER.fullmatch(line)
            if match is None:
                self._fail("listener header malformed")
            instance, ordinal = (int(value) for value in match.groups())
            if instance != self._instance or ordinal != self._count + 1:
                self._fail("listener instance or ordinal gap")
            self._record = {"instance": instance, "ordinal": ordinal}
        elif self._line == 2:
            if line != b" timesync_status":
                self._fail("inner topic mismatch")
        elif 3 <= self._line <= 8:
            name, low, high = self._FIELDS[self._line - 3]
            suffix = rb" \([0-9]{1,20}\.[0-9]{6} seconds ago\)" if name == "timestamp" else b""
            match = re.fullmatch(b"    " + name.encode() + b": " + self._DECIMAL + suffix, line)
            if match is None:
                self._fail("field order or format: " + name)
            value = int(match[1])
            if not low <= value <= high:
                self._fail("field range: " + name)
            self._record[name] = value
        elif self._line == 9:
            if line != b"":
                self._fail("padding terminator missing")
            self._count += 1
            self._line = self._frame_bytes = 0
            record, self._record = self._record, {}
            return record
        self._line += 1
        return None

    def feed(self, data: bytes, now_ns: int) -> list[dict]:
        self.check(now_ns)
        if type(data) is not bytes or len(data) > self.MAX_CHUNK:
            self._fail("invalid or oversized byte chunk")
        self._total += len(data)
        if self._total > self.MAX_TOTAL:
            self._fail("total byte limit")
        records = []
        for byte in data:
            if self._count == self._expected:
                self._fail("extra record or trailing data")
            self._frame_bytes += 1
            if self._frame_bytes > self.MAX_FRAME:
                self._fail("frame byte limit")
            if self._prefix_index < len(self._prefix):
                if byte != self._prefix[self._prefix_index]:
                    self._fail("pinned multi prefix mismatch")
                self._prefix_index += 1
                continue
            if byte != 10 and not 32 <= byte <= 126:
                self._fail("non-ASCII or control output")
            if byte != 10:
                self._partial += bytes([byte])
                continue
            line, self._partial = self._partial, b""
            record = self._accept_line(line)
            if record is not None:
                self._last_complete = now_ns
                self._prefix_index = 0
                records.append(record)
        return records

    def finish(self, now_ns: int, exit_code: int) -> dict:
        self.check(now_ns)
        if type(exit_code) is not int or exit_code != 0:
            self._fail("listener nonzero or unknown exit")
        if self._partial or self._line or self._prefix_index or self._count != self._expected:
            self._fail("listener truncated or premature EOF")
        self._closed = True
        return {
            "records": self._count, "bytes": self._total, "output_profile": self._profile,
            "listener_consumption_only": True,
            "live_listener_qualified": False, "network_authorized": False,
            "fusion_qualified": False,
        }
