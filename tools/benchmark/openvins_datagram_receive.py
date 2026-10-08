"""Bounded read of a supplied UDP socket; no creation, send or live authority.

Caller owns socket lifetime and must independently establish namespace/process
and simulation-clock provenance. Endpoint agreement is not PID authentication.
The timestamp is userspace recvmsg-return time, not a kernel arrival timestamp.
"""
from __future__ import annotations

import copy
import socket
from dataclasses import dataclass
from threading import Lock

from tools.benchmark.owned_daemon_connection import _error


@dataclass(frozen=True)
class ReceivedDatagram:
    data: bytes
    peer: tuple[str, int]
    received_ns: int


class DatagramReceiver:
    MAX_EVENTS = 8192
    LOCAL = ("127.0.0.1", 14548)
    PEER = ("127.0.0.1", 14588)

    def __init__(self, sock, guard, now, start_ns, journal):
        if (type(start_ns) is not int or not 0 <= start_ns < 2**64 - 8_000_000_000
                or not all(callable(f) for f in (guard, now, journal))):
            raise ValueError("explicit receive clock/guard/journal required")
        self._recv_flags = getattr(socket, "MSG_DONTWAIT", None)
        if type(self._recv_flags) not in (int, socket.MsgFlag) or self._recv_flags <= 0:
            raise ValueError("platform MSG_DONTWAIT required")
        self._recv_flags = int(self._recv_flags)
        self._sock, self._guard, self._now, self._journal = sock, guard, now, journal
        self._last = self._start = start_ns
        self._events, self._journal_errors = [], []
        self._regular_events = 0
        self._failure = None
        self._lock = Lock()
        try:
            self._check()
        except BaseException as exc:
            self._fail(exc)
            raise

    @property
    def progress(self):
        return dict(failure=self._failure, sender_process_proven=False, network_authorized=False,
                    live_convergence_qualified=False, fusion_qualified=False)

    @property
    def evidence(self):
        return dict(events=copy.deepcopy(self._events), failure=self._failure,
                    journal_errors=copy.deepcopy(self._journal_errors),
                    timestamp_basis="userspace monotonic recvmsg return, not kernel arrival",
                    sender_process_proven=False, network_authorized=False,
                    live_convergence_qualified=False, fusion_qualified=False)

    def _open(self):
        if self._failure is not None:
            raise ValueError("datagram receiver failure latched: " + self._failure)

    def _clock(self):
        self._open()
        value = self._now()
        self._open()
        if type(value) is not int or not self._last <= value < 2**64:
            raise ValueError("datagram receive clock invalid or regressed")
        self._last = value
        if value >= self._start + 8_000_000_000:
            raise ValueError("datagram receive global deadline")
        return value

    @staticmethod
    def _address(value, expected):
        return (type(value) is tuple and len(value) == 2 and type(value[0]) is str
                and type(value[1]) is int and value == expected)

    def _check(self):
        self._clock()
        if self._guard() is not None:
            raise ValueError("ownership guard must return None")
        self._open()
        s = self._sock
        if (not all(isinstance(v, int) and not isinstance(v, bool) for v in (s.family, s.type, s.proto))
                or s.family != socket.AF_INET or s.type != socket.SOCK_DGRAM
                or s.proto not in (0, socket.IPPROTO_UDP)):
            raise ValueError("IPv4 UDP socket required")
        timeout = s.gettimeout()
        if type(timeout) not in (int, float) or timeout != 0:
            raise ValueError("nonblocking socket required")
        if not self._address(s.getsockname(), self.LOCAL):
            raise ValueError("local endpoint changed")
        return self._clock()

    def _append(self, kind, **fields):
        if self._regular_events >= self.MAX_EVENTS:
            raise ValueError("receive event capacity")
        self._regular_events += 1
        event = dict(kind=kind, **fields)
        self._events.append(event)
        return event

    def _publish(self, event):
        if self._journal(copy.deepcopy(event)) is not None:
            raise ValueError("receive journal must return None")
        self._open()

    def _fail(self, exc):
        if self._failure is not None:
            return
        self._failure = "receive refusal (formatting error)"
        self._failure = _error(exc)
        event = dict(kind="refusal", reason=self._failure, last_checked_ns=self._last)
        self._events.append(event)  # separate terminal slot, including at capacity
        try:
            if self._journal(copy.deepcopy(event)) is not None:
                raise ValueError("refusal journal must return None")
        except BaseException as secondary:
            self._journal_errors.append(_error(secondary))

    @staticmethod
    def _description(result):
        fields = dict(return_type=type(result).__name__, data_hex=None, data_length=None,
                      flags=None, ancillary_count=None, peer=None)
        if type(result) is tuple and len(result) == 4:
            data, ancillary, flags, peer = result
            if type(data) is bytes:
                fields.update(data_hex=data[:4096].hex(), data_length=len(data))
            if type(ancillary) is list:
                fields["ancillary_count"] = len(ancillary)
            if type(flags) is int and -2**63 <= flags < 2**64:
                fields["flags"] = flags
            if type(peer) is tuple and len(peer) == 2 and type(peer[0]) is str and type(peer[1]) is int:
                fields["peer"] = (peer[0][:256], peer[1] if -2**63 <= peer[1] < 2**64 else None)
        return fields

    def poll(self):
        self._open()
        if not self._lock.acquire(blocking=False):
            self._fail(ValueError("concurrent datagram receive"))
            raise ValueError("concurrent datagram receive")
        try:
            self._check()
            if self._regular_events + 2 > self.MAX_EVENTS:
                raise ValueError("receive event capacity before read")
            self._publish(self._append("receive_attempt", last_checked_ns=self._last))
            started = self._check()
            try:
                result = self._sock.recvmsg(4096, 0, self._recv_flags)
            except BlockingIOError:
                returned = self._check()
                if returned - started >= 2_000_000_000:
                    raise ValueError("receive call timeout") from None
                return None
            # Save actual returned bytes before any clock/guard/journal callback.
            event = self._append("receive_return", started_ns=started, received_ns=None,
                                 **self._description(result))
            try:
                received = self._clock()
            except BaseException:
                try:
                    self._publish(event)
                except BaseException as secondary:
                    self._journal_errors.append(_error(secondary))
                raise
            event["received_ns"] = received
            self._publish(event)
            if received - started >= 2_000_000_000:
                raise ValueError("receive call timeout")
            self._check()
            if type(result) is not tuple or len(result) != 4:
                raise ValueError("recvmsg return shape")
            data, ancillary, flags, peer = result
            if (type(data) is not bytes or not 1 <= len(data) <= 4096
                    or type(ancillary) is not list or ancillary or type(flags) is not int or flags != 0
                    or not self._address(peer, self.PEER)):
                raise ValueError("datagram payload/ancillary/flags/source refused")
            self._open()
            return ReceivedDatagram(data, peer, received)
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._lock.release()

    def check(self):
        """Non-consuming revalidation, for the final send boundary."""
        self._open()
        if not self._lock.acquire(blocking=False):
            self._fail(ValueError("concurrent datagram check"))
            raise ValueError("concurrent datagram check")
        try:
            self._check()
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self._lock.release()
