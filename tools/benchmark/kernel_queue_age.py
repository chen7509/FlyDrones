"""Additional modeled queue-age refusal, never continuous clock qualification."""

from __future__ import annotations

import copy
import re
from threading import Lock, RLock

from tools.benchmark.kernel_datagram_arrival import _unbound
from tools.benchmark.kernel_rx_timestamping import KernelRXTimestamping
from tools.benchmark.owned_daemon_connection import _error

MAX_NS = 2**63 - 1
AGE_NS = 2_000_000_000


def _integer(value, label, *, minimum=0, maximum=MAX_NS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid " + label)
    return value


def offset_bracket(m_before, realtime_ns, m_after):
    """Conditional O=R-M interval; observed consistency is not proof of O."""
    _integer(m_before, "monotonic before")
    _integer(m_after, "monotonic after", minimum=m_before)
    _integer(realtime_ns, "realtime", minimum=1)
    if m_after - m_before >= AGE_NS:
        raise ValueError("clock sample span too uncertain")
    return realtime_ns - m_after, realtime_ns - m_before


def modeled_age(kernel_ns, now_ns, offset_lower_ns, offset_upper_ns):
    _integer(kernel_ns, "kernel timestamp", minimum=1)
    _integer(now_ns, "age clock")
    _integer(offset_lower_ns, "offset lower", minimum=-MAX_NS)
    _integer(offset_upper_ns, "offset upper", minimum=offset_lower_ns)
    lower, upper = kernel_ns - offset_upper_ns, kernel_ns - offset_lower_ns
    if lower < 0 or upper > MAX_NS:
        raise ValueError("projected monotonic interval overflow or negative")
    age_lower, age_upper = now_ns - upper, now_ns - lower
    if age_lower < 0:
        raise ValueError("modeled kernel interval may be future")
    if age_upper >= AGE_NS:
        raise ValueError("modeled kernel queue age expired")
    return {
        "monotonic_lower_ns": lower,
        "monotonic_upper_ns": upper,
        "modeled_age_lower_ns": age_lower,
        "modeled_age_upper_ns": age_upper,
        "checked_monotonic_ns": now_ns,
        "clock_mapping_qualified": False,
    }


class KernelQueueAge:
    MAX_ANCHORS = 32768
    MAX_ASSESSMENTS = 8192

    def __init__(self, kernel, now, start_ns, session_id):
        if (
            type(kernel) is not KernelRXTimestamping
            or not callable(now)
            or type(session_id) is not str
            or re.fullmatch("[A-Za-z0-9_.:-]{1,128}", session_id) is None
        ):
            raise ValueError("exact generated RX and explicit clock/session required")
        _integer(start_ns, "queue-age start")
        self._kernel, self._now, self._start, self._session = kernel, now, start_ns, session_id
        self._sock = kernel._sock
        self._writer, self._state = Lock(), RLock()
        self._owner = None
        self._failure = None
        self._last = start_ns
        self._offset = None
        self._anchors, self._assessments = [], []
        self._pending = None
        if self._sock is None or not _unbound(self._sock.getsockname()):
            raise ValueError("queue-age anchor requires prepared socket before bind")
        kernel.check(self._sock)
        self._sample(None)
        try:
            kernel.check(self._sock)
            if not _unbound(self._sock.getsockname()):
                raise ValueError("queue-age initial anchor requires socket before bind")
        except BaseException as error:
            self._fail(error)
            try:
                error.queue_age_evidence = self.evidence
            except BaseException:
                pass
            raise
        self._initial_realtime = self._anchors[0]["realtime_ns"]

    @property
    def evidence(self):
        with self._state:
            return {
                "session_id": self._session,
                "failure": self._failure,
                "anchors": copy.deepcopy(self._anchors),
                "assessments": copy.deepcopy(self._assessments),
                "pending_anchor": copy.deepcopy(self._pending),
                "offset_interval_ns": self._offset,
                "model": "observed constant R-M interval; not continuous clock proof",
                "clock_mapping_qualified": False,
                "source_authenticated": False,
                "network_authorized": False,
                "fusion_qualified": False,
                "training_eligible": False,
            }

    def _open(self):
        if self._failure is not None:
            raise ValueError("queue-age failure latched: " + self._failure)

    def _fail(self, error):
        with self._state:
            if self._failure is None:
                self._failure = "queue-age refusal (formatting pending)"
            else:
                return
        detail = _error(error)
        with self._state:
            self._failure = detail

    def _run(self, owner, action):
        if not self._writer.acquire(blocking=False):
            error = ValueError("concurrent or reentrant queue-age sampler")
            self._fail(error)
            raise error
        try:
            with self._state:
                self._open()
                if owner is not self._owner:
                    raise ValueError("queue-age receiver owner changed")
            result = action()
            with self._state:
                self._open()
                if owner is not self._owner:
                    raise ValueError("queue-age owner changed during callback")
            return result
        except BaseException as error:
            self._fail(error)
            raise
        finally:
            self._writer.release()

    def _clock(self):
        value = self._now()
        with self._state:
            self._open()
            _integer(value, "queue-age monotonic", minimum=self._last)
            self._last = value
        return value

    def _bind(self, owner, sock, kernel, now, start_ns):
        with self._state:
            self._open()
            if self._owner is not None:
                error = ValueError("queue-age sampler already bound")
                self._fail(error)
                raise error
            if (
                owner is None
                or sock is not self._sock
                or kernel is not self._kernel
                or now is not self._now
                or type(start_ns) is not int
                or start_ns != self._start
            ):
                error = ValueError("queue-age profile/clock/start binding mismatch")
                self._fail(error)
                raise error
            self._owner = owner

    def _capture(self):
        with self._state:
            self._open()
            if len(self._anchors) >= self.MAX_ANCHORS:
                raise ValueError("queue-age anchor capacity")
            row = {
                "sequence": len(self._anchors) + 1,
                "monotonic_before_ns": None,
                "realtime_ns": None,
                "monotonic_after_ns": None,
            }
            self._pending = row
        before = self._clock()
        with self._state:
            row["monotonic_before_ns"] = before
        real = self._kernel.realtime()
        with self._state:
            row["realtime_ns"] = real
            self._open()
        after = self._clock()
        with self._state:
            self._open()
            row["monotonic_after_ns"] = after
            lower, upper = offset_bracket(before, real, after)
            if self._offset is not None:
                lower, upper = max(lower, self._offset[0]), min(upper, self._offset[1])
            if lower > upper:
                raise ValueError("observed realtime/monotonic offset model inconsistent")
            self._offset = (lower, upper)
            row["offset_interval_ns"] = self._offset
            self._anchors.append(row)
            self._pending = None
            return copy.deepcopy(row)

    def _sample(self, owner):
        return self._run(owner, self._capture)

    def _current(self, owner):
        return self._run(owner, self._clock)

    def _observe_mono(self, owner, value):
        def action():
            with self._state:
                self._open()
                _integer(value, "queue-age monotonic", minimum=self._last)
                self._last = value
                return value

        return self._run(owner, action)

    def _assess(self, owner, kernel_ns):
        def action():
            with self._state:
                self._open()
                if len(self._assessments) >= self.MAX_ASSESSMENTS:
                    raise ValueError("queue-age assessment capacity")
                row = {"kernel_received_realtime_ns": kernel_ns, "result": None, "failure": None}
                self._assessments.append(row)
            try:
                _integer(kernel_ns, "kernel timestamp", minimum=1)
                if kernel_ns != self._kernel._last_kernel:
                    raise ValueError("queue-age timestamp not current parsed metadata")
                if kernel_ns < self._initial_realtime:
                    raise ValueError("kernel timestamp predates queue-age session")
                anchor = self._capture()
                with self._state:
                    self._open()
                    row["result"] = modeled_age(kernel_ns, anchor["monotonic_after_ns"], *self._offset)
                    return copy.deepcopy(row["result"])
            except BaseException as error:
                detail = _error(error)
                with self._state:
                    row["failure"] = detail
                raise

        return self._run(owner, action)
