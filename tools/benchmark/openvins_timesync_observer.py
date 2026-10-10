"""Offline serial reply/status contract, with no live convergence authority.

Cold PX4 epoch, exclusive producer, listener framing and actual send provenance
are external prerequisites. A listener ordinal is not a uORB generation number.
"""

from __future__ import annotations

import copy
from typing import NoReturn

from tools.benchmark.openvins_ekf2_disarmed_preflight import (
    BoundedTimesyncVerifier,
    TimesyncExchange,
)


class SerialTimesyncObserver:
    """Reserve one reply and require its matching status before reserving more."""

    PENDING_NS = 2_000_000_000
    _STATUS_RANGES = {
        "instance": (0, 255),
        "ordinal": (1, 2**32 - 1),
        "timestamp": (1, 2**64 - 1),
        "remote_timestamp": (1, 2**64 - 1),
        "observed_offset": (-(2**63), 2**63 - 1),
        "estimated_offset": (-(2**63), 2**63 - 1),
        "round_trip_time": (0, 2**32 - 1),
        "source_protocol": (0, 255),
    }

    def __init__(self, session_id: str, topic_instance: int):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("invalid session identity")
        if type(topic_instance) is not int or not 0 <= topic_instance <= 255:
            raise ValueError("invalid topic instance")
        self._instance = topic_instance
        self._verifier = BoundedTimesyncVerifier(session_id)
        self._fault: str | None = None
        self._pending: tuple[int, int, int] | None = None
        self._last_now: int | None = None
        self._last_identity: tuple[int, int] | None = None
        self._last_status_timestamp = 0
        self._ordinal = 0

    def _fail(self, reason: str) -> NoReturn:
        self._fault = reason
        raise ValueError(reason)

    def check(self, now_ns: int) -> None:
        if self._fault is not None:
            raise ValueError("observer failure latched: " + self._fault)
        if type(now_ns) is not int or not 0 <= now_ns < 2**64:
            self._fail("invalid local clock")
        if self._last_now is not None and now_ns < self._last_now:
            self._fail("local clock regression")
        self._last_now = now_ns
        if self._pending is not None and now_ns - self._pending[2] >= self.PENDING_NS:
            self._fail("pending status timeout")

    def reserve_reply(self, request_ns: int, response_ns: int, now_ns: int) -> None:
        """Record intent, not proof of a send. A transport must journal first."""
        self.check(now_ns)
        if self._pending is not None:
            self._fail("reply already pending")
        for value in (request_ns, response_ns):
            if type(value) is not int or not 0 < value < 2**63 or value % 1000:
                self._fail("invalid reply identity")
        if self._last_identity is not None and (
            request_ns <= self._last_identity[0] or response_ns <= self._last_identity[1]
        ):
            self._fail("reply identity regression or reuse")
        self._last_identity = (request_ns, response_ns)
        self._pending = (request_ns, response_ns, now_ns)

    def observe_status(self, status: dict, now_ns: int) -> dict:
        self.check(now_ns)
        if self._pending is None:
            self._fail("status without pending reply")
        if type(status) is not dict or status.keys() != self._STATUS_RANGES.keys():
            self._fail("status schema mismatch")
        for key, (low, high) in self._STATUS_RANGES.items():
            if type(status[key]) is not int or not low <= status[key] <= high:
                self._fail("status field invalid: " + key)
        if status["instance"] != self._instance or status["ordinal"] != self._ordinal + 1:
            self._fail("status identity or observation gap")
        if status["source_protocol"] != 0:
            self._fail("source protocol differs from pinned MAVLink default")
        request_ns, response_ns, _ = self._pending
        if status["remote_timestamp"] != response_ns // 1000:
            self._fail("status remote identity mismatch")
        receive_us = request_ns // 1000 + status["round_trip_time"]
        if receive_us * 1000 >= 2**63:
            self._fail("reconstructed receive clock overflow")
        if status["timestamp"] < receive_us or status["timestamp"] <= self._last_status_timestamp:
            self._fail("status publication clock invalid")
        numerator = request_ns // 1000 + receive_us - 2 * (response_ns // 1000)
        observed = numerator // 2 if numerator >= 0 else -((-numerator) // 2)
        if status["observed_offset"] != observed:
            self._fail("observed offset mismatch")
        predicted = copy.deepcopy(self._verifier)
        try:
            result = predicted.observe(TimesyncExchange(request_ns, response_ns, receive_us * 1000))
        except ValueError as exc:
            self._fail("filter refusal: " + str(exc))
        if result["reset"]:
            self._fail("filter reset requires fresh PX4 epoch")
        if status["estimated_offset"] != predicted.estimated_offset_us:
            self._fail("estimated offset mismatch")
        self._verifier = predicted
        self._pending = None
        self._ordinal = status["ordinal"]
        self._last_status_timestamp = status["timestamp"]
        return {
            "session_id": result["session_id"],
            "accepted": result["accepted"],
            "reason": result["reason"],
            "modeled_accepted_samples": result["sequence"],
            "observed_model_converged": result["converged"],
            "estimated_offset_us": predicted.estimated_offset_us,
            "live_convergence_qualified": False,
            "network_authorized": False,
            "fusion_qualified": False,
        }
