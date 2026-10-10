"""Bounded read-only query of an owned PX4 daemon's MAVLink startup status.

This proves only one daemon reply. A separate source-owned startup log marker
and phase transition are required before a cold TIMESYNC session may start.
"""

from __future__ import annotations

import copy
from threading import Lock

from tools.benchmark.owned_daemon_connection import (
    ConnectionRefusal,
    LinuxBackend,
    _error,
    connect_owned_daemon,
    validate_owner,
)
from tools.benchmark.px4_mavlink_startup_status import parse_mavlink_status


class StatusProbeRefusal(ValueError):
    def __init__(self, evidence):
        self.evidence = copy.deepcopy(evidence)
        super().__init__(evidence['error'])


class OwnedMavlinkStatusProbe:
    """One serial, fixed ``mavlink status`` command on a verified owned socket."""

    COMMAND = b'mavlink status\0'
    MAX_STDOUT = 32_768
    MAX_EVENTS = 128

    def __init__(self, process, expected, path, start_ns, deadline_ns, journal, *, backend=None):
        self._backend = backend or LinuxBackend()
        self._process, self._expected = process, copy.deepcopy(expected)
        self._journal = journal
        self._connection = None
        self._lock = Lock()
        self._closed = self._done = False
        self._fault = None
        self._offset = 0
        self._stdout = bytearray()
        self._trailer = bytearray()
        self._events = []
        self._result = dict(transport_complete=False, authority=False, fusion_qualified=False,
                            connection_evidence=None, raw_stdout_hex='', raw_trailer_hex='',
                            exit_code=None, parsed=None, error=None, close_error=None,
                            refusal_journal_error=None, events=self._events)
        try:
            validate_owner(self._expected)
            if (type(start_ns) is not int or type(deadline_ns) is not int
                    or not 0 <= start_ns < deadline_ns < 2**64
                    or deadline_ns - start_ns > 2_000_000_000 or not callable(journal)):
                raise ValueError('bounded two-second status clock and journal required')
            self._last_clock = start_ns
            self._deadline = deadline_ns
            now = self._check()
            self._connection, proof = connect_owned_daemon(
                process, self._expected, path, deadline_ns=deadline_ns,
                journal=lambda event: self._record('connection', observation=event),
                backend=self._backend)
            self._result['connection_evidence'] = proof
            self._connection.setblocking(False)
            self._owner()
            self._check()
            self._record('status_probe_started', at_ns=now)
        except BaseException as exc:
            if isinstance(exc, ConnectionRefusal):
                self._result['connection_evidence'] = exc.evidence
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise StatusProbeRefusal(self._result) from exc

    @property
    def evidence(self):
        return copy.deepcopy(self._result)

    def _record(self, kind, **fields):
        if len(self._events) >= self.MAX_EVENTS:
            raise ValueError('status evidence capacity exceeded')
        event = dict(kind=kind, **fields)
        self._events.append(copy.deepcopy(event))
        if self._journal(copy.deepcopy(event)) is not None:
            raise ValueError('status journal must return None')

    def _check(self):
        now = self._backend.clock()
        if type(now) is not int or not self._last_clock <= now < 2**64:
            raise ValueError('status clock regressed or invalid')
        self._last_clock = now
        if now >= self._deadline:
            raise TimeoutError('status query deadline expired')
        return now

    def _owner(self):
        current = self._backend.observe(self._process)
        validate_owner(current)
        if current != self._expected:
            raise ValueError('status owner changed')
        peer = self._backend.peer(self._connection)
        if (type(peer) is not dict or peer.keys() != {'pid', 'uid', 'gid'}
                or any(type(peer[key]) is not int or peer[key] != self._expected[key]
                       for key in ('pid', 'uid', 'gid'))):
            raise ValueError('status peer changed')

    def _returned(self, kind, **fields):
        # Preserve the syscall result before checking a now-late clock or peer.
        clock_error = None
        try:
            fields['returned_ns'] = self._backend.clock()
        except BaseException as exc:
            fields['clock_error'] = _error(exc)
            clock_error = exc
        self._record(kind, **fields)
        if clock_error is not None:
            raise clock_error
        self._check()

    def _close(self):
        if self._connection is not None and not self._closed:
            self._closed = True
            try:
                self._backend.close(self._connection)
            except BaseException as exc:
                self._result['close_error'] = _error(exc)
                raise

    def _abort(self, exc):
        first = self._fault is None
        if first:
            self._fault = _error(exc)
            self._result['error'] = self._fault
        try:
            self._close()
        except BaseException:
            pass
        if first:
            event = dict(kind='status_refusal', error=self._fault,
                         close_error=self._result['close_error'])
            if len(self._events) < self.MAX_EVENTS:
                self._events.append(copy.deepcopy(event))
            try:
                if self._journal(copy.deepcopy(event)) is not None:
                    raise ValueError('refusal journal must return None')
            except BaseException as journal_exc:
                self._result['refusal_journal_error'] = _error(journal_exc)

    def close(self):
        if not self._done and not self._closed:
            self._abort(ValueError('status probe aborted before EOF'))

    def poll(self):
        if self._done or self._fault:
            raise ValueError('status probe already completed or failed')
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError('concurrent status probe poll'))
            raise StatusProbeRefusal(self._result)
        try:
            self._check()
            self._owner()
            if self._offset < len(self.COMMAND):
                remaining = self.COMMAND[self._offset:]
                self._record('send_attempt', offset=self._offset, raw_hex=remaining.hex(),
                             at_ns=self._check())
                self._owner()
                self._check()
                try:
                    sent = self._connection.send(remaining)
                except BlockingIOError:
                    self._check()
                    return None
                self._returned('send_return', offset=self._offset, count=sent)
                if type(sent) is not int or not 0 < sent <= len(remaining):
                    raise ValueError('invalid status command send count')
                self._offset += sent
                if self._offset < len(self.COMMAND):
                    return None
            self._owner()
            self._check()
            try:
                raw = self._connection.recv(4096)
            except BlockingIOError:
                self._check()
                return None
            if type(raw) is not bytes or len(raw) > 4096:
                raise ValueError('invalid status daemon read')
            self._returned('recv_return', raw_hex=raw.hex(), eof=not raw)
            self._owner()
            self._check()
            if raw:
                if not self._trailer:
                    boundary = raw.find(b'\0')
                    if boundary >= 0:
                        self._stdout.extend(raw[:boundary])
                        self._trailer.extend(raw[boundary:])
                    else:
                        self._stdout.extend(raw)
                else:
                    self._trailer.extend(raw)
                self._result['raw_stdout_hex'] = self._stdout.hex()
                self._result['raw_trailer_hex'] = self._trailer.hex()
                if len(self._stdout) > self.MAX_STDOUT or len(self._trailer) > 2:
                    raise ValueError('status daemon response exceeds byte bound')
                return None
            if len(self._trailer) != 2 or self._trailer[0] != 0:
                raise ValueError('status daemon reply missing two-byte exit trailer')
            exit_code = self._trailer[1]
            self._result['exit_code'] = exit_code
            parsed = parse_mavlink_status(bytes(self._stdout), exit_code)
            self._record('parsed_status_eof', parsed=parsed, exit_code=exit_code,
                         at_ns=self._check())
            self._owner()
            self._check()
            self._close()
            self._result['parsed'] = parsed
            self._result['transport_complete'] = self._done = True
            return copy.deepcopy(parsed)
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise StatusProbeRefusal(self._result) from exc
        finally:
            self._lock.release()
