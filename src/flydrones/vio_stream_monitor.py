"""Local, test-only freshness monitor for delivered visual odometry frames."""

from __future__ import annotations

import json
import math
import socket
from dataclasses import dataclass

SCHEMA = "flydrones-vio-stream-v1"


@dataclass(frozen=True)
class VioStreamHealth:
    healthy: bool
    reason: str | None
    sample_age_s: float | None
    transport_delay_s: float | None
    last_frame_at_s: float | None


class VioStreamMonitor:
    """Watch relay metadata on loopback without treating PX4 pose as new VIO."""

    def __init__(
        self,
        *,
        vehicle_id: int,
        port: int,
        max_age_s: float = 0.25,
        max_transport_delay_s: float = 0.25,
    ) -> None:
        if vehicle_id < 0 or not 0 <= port <= 65535:
            raise ValueError("invalid VIO monitor endpoint")
        if max_age_s <= 0 or max_transport_delay_s <= 0:
            raise ValueError("VIO freshness limits must be positive")
        self.vehicle_id = vehicle_id
        self.max_age_s = max_age_s
        self.max_transport_delay_s = max_transport_delay_s
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.bind(("127.0.0.1", port))
            self._socket.setblocking(False)
        except Exception:
            self._socket.close()
            raise
        self.port = self._socket.getsockname()[1]
        self._sequence = -1
        self._source_stamp_ns = -1
        self._received_at: float | None = None
        self._published_at: float | None = None

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> VioStreamMonitor:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def health(self, *, now: float) -> VioStreamHealth:
        while True:
            try:
                payload, _peer = self._socket.recvfrom(2048)
            except BlockingIOError:
                break
            try:
                message = json.loads(payload)
                if message.get("schema") != SCHEMA or message.get("vehicle_id") != self.vehicle_id:
                    continue
                sequence = message["sequence"]
                source_stamp_ns = message["source_stamp_ns"]
                received_at = float(message["received_at"])
                published_at = float(message["published_at"])
                if (type(sequence) is not int or sequence <= self._sequence
                        or type(source_stamp_ns) is not int or source_stamp_ns <= self._source_stamp_ns
                        or not all(math.isfinite(value) for value in (received_at, published_at))
                        or received_at > published_at or published_at > now + 0.001):
                    continue
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
            self._sequence = sequence
            self._source_stamp_ns = source_stamp_ns
            self._received_at = received_at
            self._published_at = published_at
        if self._received_at is None or self._published_at is None:
            return VioStreamHealth(False, "missing-vio-frame", None, None, None)
        sample_age_s = now - self._received_at
        transport_delay_s = self._published_at - self._received_at
        if sample_age_s < -0.001:
            return VioStreamHealth(False, "invalid-vio-time", sample_age_s,
                                   transport_delay_s, self._published_at)
        if transport_delay_s > self.max_transport_delay_s:
            return VioStreamHealth(False, "delayed-vio-frame", sample_age_s,
                                   transport_delay_s, self._published_at)
        if sample_age_s > self.max_age_s:
            return VioStreamHealth(False, "stale-vio-frame", sample_age_s,
                                   transport_delay_s, self._published_at)
        return VioStreamHealth(True, None, sample_age_s, transport_delay_s,
                               self._published_at)
