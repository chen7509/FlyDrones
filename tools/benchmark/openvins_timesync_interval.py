"""Offline TIMESYNC rate-transaction model for pinned PX4 d6f12ad.

No wire adapter is supplied. Callers must bound I/O and independently establish
freshness, channel identity and exclusive ownership. Events are in memory only;
successful readback is not proof of actual transmission/accepted filter rate.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from threading import Lock
from typing import Protocol


def _f32(value: int | float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def restorable_interval(value: int) -> int:
    """Accept only positive int32 intervals surviving wire and PX4 conversions."""
    if type(value) is not int or not 0 < value < 2**31:
        raise ValueError("ambiguous or invalid interval")
    wire = _f32(value)
    if wire != value:
        raise ValueError("interval loses wire precision")
    rate = _f32(1_000_000.0 / wire)
    restored = _f32(1_000_000.0 / rate)
    if not 0 < restored < 2**31 or int(restored) != value:
        raise ValueError("interval does not roundtrip pinned PX4")
    return value


class IntervalTransport(Protocol):
    """Future bounded/correlated adapter contract, not an implemented transport."""

    def read_interval(self, message_id: int) -> list[dict]: ...
    def set_interval(self, message_id: int, interval_us: int) -> bool: ...


class TimesyncIntervalTransaction:
    """One apply/body/restore attempt. Live authority always remains false.

    A callable body must return literal True after its own modeled checks. The
    helper cannot interrupt blocking transport/body calls or survive process
    death. A future live harness must supply those guarantees outside this class.
    """

    MESSAGE_ID = 111
    CANDIDATE_US = 10000

    def __init__(self, transport: IntervalTransport):
        self._transport = transport
        self._used = False
        self._lock = Lock()
        self.last_result: dict | None = None

    def _read(self) -> int:
        rows = self._transport.read_interval(self.MESSAGE_ID)
        if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            raise ValueError("interval response count or shape")
        row = rows[0]
        if set(row) != {"message_id", "interval_us"}:
            raise ValueError("interval response keys")
        if type(row["message_id"]) is not int or row["message_id"] != self.MESSAGE_ID:
            raise ValueError("interval response message identity")
        return restorable_interval(row["interval_us"])

    def run(self, body: Callable[[], bool]) -> dict:
        with self._lock:
            if self._used:
                raise ValueError("single-use interval transaction")
            self._used = True
        result = {
            "baseline_us": None, "candidate_us": self.CANDIDATE_US,
            "final_us": None, "mutation_attempted": False,
            "restore_attempted": False, "primary_failure": None,
            "restore_failures": [], "events": [],
            "modeled_transaction_pass": False, "network_authorized": False,
            "live_rate_qualified": False, "fusion_qualified": False,
        }
        interruption: BaseException | None = None

        def failure(phase: str, exc: BaseException, *, restore: bool = False):
            nonlocal interruption
            # Diagnostics must not call untrusted exception formatting outside
            # a guard: __str__ may itself raise and otherwise skip restoration.
            try:
                message = str(exc)
            except BaseException:
                message = "<unprintable exception>"
            detail = f"{phase}:{type(exc).__name__}:{message}"
            if restore:
                result["restore_failures"].append(detail)
            else:
                result["primary_failure"] = detail
            result["events"].append({"phase": phase, "error": detail})
            if not isinstance(exc, Exception) and interruption is None:
                interruption = exc

        phase = "baseline"
        try:
            if not callable(body):
                raise ValueError("body must be callable")
            candidate = restorable_interval(self.CANDIDATE_US)
            baseline = self._read()
            result["baseline_us"] = baseline
            result["events"].append({"phase": phase, "interval_us": baseline})
            if baseline != candidate:
                phase = "apply"
                # A throwing/lost ACK can still follow a committed remote write.
                result["mutation_attempted"] = True
                result["events"].append({"phase": phase, "attempt_us": candidate})
                if self._transport.set_interval(self.MESSAGE_ID, candidate) is not True:
                    raise ValueError("accepted ACK missing")
                phase = "apply_readback"
                observed = self._read()
                result["events"].append({"phase": phase, "interval_us": observed})
                if observed != candidate:
                    raise ValueError("candidate readback mismatch")
            phase = "body"
            if body() is not True:
                raise ValueError("body did not pass")
            result["events"].append({"phase": phase, "passed": True})
        except BaseException as exc:
            failure(phase, exc)

        baseline = result["baseline_us"]
        if result["mutation_attempted"]:
            result["restore_attempted"] = True
            try:
                result["events"].append({"phase": "restore", "attempt_us": baseline})
                if self._transport.set_interval(self.MESSAGE_ID, baseline) is not True:
                    raise ValueError("accepted ACK missing")
            except BaseException as exc:
                failure("restore", exc, restore=True)
            # Independent evidence, including after write/ACK exceptions.
            try:
                observed = self._read()
                result["events"].append({"phase": "restore_readback", "interval_us": observed})
                if observed != baseline:
                    raise ValueError("baseline readback mismatch")
            except BaseException as exc:
                failure("restore_readback", exc, restore=True)
        if baseline is not None:
            try:
                result["final_us"] = self._read()
                result["events"].append({"phase": "final", "interval_us": result["final_us"]})
                if result["final_us"] != baseline:
                    raise ValueError("final baseline mismatch")
            except BaseException as exc:
                failure("final", exc, restore=True)
        result["modeled_transaction_pass"] = (
            result["primary_failure"] is None and not result["restore_failures"]
        )
        self.last_result = result
        if interruption is not None:
            raise interruption
        return result
