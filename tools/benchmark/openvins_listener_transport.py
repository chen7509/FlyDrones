"""Read-only adapter for pinned PX4 daemon wire semantics, not a live grant.

Only private ordinary fixtures have exercised this adapter. No MAVLink sender,
parameter/stream mutation, reconnect, process launch or background timer exists.
Caller must poll on silence and externally bound filesystem/journal blocking.
"""
from __future__ import annotations

import copy
from threading import Lock

from tools.benchmark.openvins_segmented_journal import event_log, record_failure, require_capacity
from tools.benchmark.openvins_timesync_bootstrap import parse_snapshot
from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
from tools.benchmark.openvins_timesync_maintenance import _TimesyncMaintenance
from tools.benchmark.owned_daemon_connection import (
    ConnectionRefusal,
    LinuxBackend,
    _error,
    connect_owned_daemon,
    validate_owner,
)


def listener_command(mode, count):
    if type(mode) is not str or type(count) is not int:
        raise ValueError('literal listener mode/count required')
    if mode == 'snapshot' and count == 1:
        return b'listener timesync_status -n 1\0'
    if mode == 'stream' and 2 <= count <= 4096:
        return f'listener timesync_status -i 0 -n {count}\0'.encode()
    raise ValueError('only bounded read-only TIMESYNC listener allowed')


class ReplyEnvelope:
    MAX_TOTAL = 4*1024*1024+2

    def __init__(self):
        self.total = 0
        self.trailer = b''
        self.failed = None
        self.closed = False

    def _fail(self, reason):
        self.failed = reason
        raise ValueError(reason)

    def feed(self, data):
        if self.failed or self.closed:
            self._fail('daemon envelope failed or closed')
        if type(data) is not bytes or len(data) > 4096:
            self._fail('invalid daemon response chunk')
        self.total += len(data)
        if self.total > self.MAX_TOTAL:
            self._fail('daemon response exceeds byte bound')
        stdout = b''
        if not self.trailer:
            index = data.find(b'\0')
            if index < 0:
                return data
            stdout, data = data[:index], data[index:]
        self.trailer += data
        if len(self.trailer) > 2:
            self._fail('data after daemon exit trailer')
        if len(self.trailer) == 2 and self.trailer != b'\0\0':
            self._fail('daemon nonzero exit')
        return stdout

    def finish(self):
        if self.failed or self.closed or self.trailer != b'\0\0':
            self._fail('daemon missing trailer or invalid EOF')
        self.closed = True
        return 0


class ListenerRefusal(ValueError):
    def __init__(self, evidence):
        self.evidence = copy.deepcopy(evidence)
        super().__init__(evidence['error'])


class ReadOnlyListener:
    MAX_EVENTS = 65536

    def __init__(self, process, expected, path, mode, count, start_ns, deadline_ns, journal, *, backend=None,
                 continuation=None, retention=None, retention_channel=None):
        self._backend = backend or LinuxBackend()
        self._process, self._expected = process, copy.deepcopy(expected)
        self._journal = journal
        self._connection = None
        self._closed = self._done = self._parsed_terminal = False
        self._cancelled = False
        self._continuation = continuation
        self._fault = None
        self._lock = Lock()
        self._regular_events = 0  # One independent terminal-refusal slot is separate.
        self._result = dict(transport_complete=False, network_authorized=False, fusion_qualified=False,
                            live_listener_qualified=False, events=event_log(retention, retention_channel),
                            error=None, close_error=None,
                            refusal_journal_error=None, return_journal_error=None, connection_evidence=None)
        self._offset = 0
        self._snapshot = b''
        self._envelope = ReplyEnvelope()
        self._decoder = None
        try:
            self._command = listener_command(mode, count)
            self._mode = mode
            validate_owner(self._expected)
            limit = 8_000_000_000
            if continuation is not None:
                if type(continuation) is not _TimesyncMaintenance:
                    raise ValueError('actual maintenance continuation required')
                context = continuation.progress
                if (mode != 'stream' or count != 4096 or context['failure'] is not None
                        or context['phase'] != 'replay_pending' or start_ns != context['handoff_ns']
                        or deadline_ns != context['deadline_ns']):
                    raise ValueError('maintenance listener context mismatch')
                limit = 300_000_000_000
            if (type(start_ns) is not int or type(deadline_ns) is not int
                    or not 0 <= start_ns < deadline_ns < 2**64
                    or deadline_ns-start_ns > limit or not callable(journal)):
                raise ValueError('bounded listener clock window/journal required')
            self._last_now = self._last_complete = start_ns
            self._deadline = deadline_ns
            entry = self._check(check_frame=False)
            if continuation is not None:
                continuation._claim_transport(entry)
            self._last_complete = entry
            if mode == 'stream':
                self._decoder = TimesyncListenerDecoder(0, count, entry, output_profile='px4-d6f12ad-multi-v1')
            self._connection, proof = connect_owned_daemon(
                process, self._expected, path, deadline_ns=min(deadline_ns, entry+2000000000),
                journal=lambda event: self._record('connection', observation=event), backend=self._backend)
            self._result['connection_evidence'] = proof
            self._connection.setblocking(False)
            self._check()
        except BaseException as exc:
            if isinstance(exc, ConnectionRefusal):
                self._result['connection_evidence'] = exc.evidence
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise ListenerRefusal(self._result) from exc

    @property
    def evidence(self):
        return copy.deepcopy(self._result)

    def _record(self, kind, *, allow_failed=False, **fields):
        require_capacity(self._result['events'], self._regular_events, self.MAX_EVENTS)
        event = dict(kind=kind, **fields)
        self._regular_events += 1
        self._result['events'].append(copy.deepcopy(event))
        if self._journal(copy.deepcopy(event)) is not None:
            raise ValueError('listener journal must return None')
        if self._fault and not allow_failed:
            raise ValueError('listener failure latched')

    def _reserve_events(self, count):
        # poll has a single owner: reserve evidence capacity before doing I/O.
        require_capacity(self._result['events'], self._regular_events, self.MAX_EVENTS, count)

    def _returned(self, kind, **fields):
        # A completed syscall remains evidence even when its return is late or
        # the subsequent clock observation fails. Never discard actual bytes.
        clock_error = None
        try:
            fields['returned_clock_ns'] = self._backend.clock()
        except BaseException as exc:
            fields['clock_error'] = _error(exc)
            clock_error = exc
        try:
            self._record(kind, **fields)
        except BaseException as journal_error:
            self._result['return_journal_error'] = _error(journal_error)
            if clock_error is not None and not isinstance(clock_error, Exception):
                raise clock_error from journal_error
            if clock_error is not None and isinstance(journal_error, Exception):
                raise clock_error from journal_error
            raise
        if clock_error is not None:
            raise clock_error
        self._accept_clock(fields['returned_clock_ns'])

    def _check(self, *, check_frame=True):
        return self._accept_clock(self._backend.clock(), check_frame=check_frame)

    def _accept_clock(self, now, *, check_frame=True):
        if self._fault:
            raise ValueError(self._fault)
        if type(now) is not int or not self._last_now <= now < 2**64:
            raise ValueError('listener local clock regression')
        self._last_now = now
        if now >= self._deadline:
            raise ValueError('listener global deadline timeout')
        if self._continuation is not None:
            context = self._continuation.progress
            if context['failure'] is not None or context['phase'] == 'cancelled':
                raise ValueError('maintenance continuation failed or cancelled')
        if check_frame and now-self._last_complete >= 2000000000:
            raise ValueError('listener complete-frame timeout')
        if self._decoder is not None and not self._parsed_terminal:
            self._decoder.check(now)
        return now

    def _owner(self):
        actual = self._backend.observe(self._process)
        validate_owner(actual)
        if actual != self._expected:
            raise ValueError('listener owner changed')
        peer = self._backend.peer(self._connection)
        if (type(peer) is not dict or peer.keys() != {'pid', 'uid', 'gid'}
                or any(type(peer[k]) is not int or peer[k] != self._expected[k] for k in ('pid', 'uid', 'gid'))):
            raise ValueError('listener peer changed')

    def _close_socket(self):
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
            self._close_socket()
        except BaseException:
            pass  # separately retained by _close_socket; do not mask primary
        if first:
            event = dict(kind='refusal', error=self._fault, close_error=self._result['close_error'])
            record_failure(self._result['events'], copy.deepcopy(event))
            try:
                if self._journal(copy.deepcopy(event)) is not None:
                    raise ValueError('refusal journal must return None')
            except BaseException as journal_exc:
                self._result['refusal_journal_error'] = _error(journal_exc)

    def close(self):
        if not self._done and not self._closed:
            self._abort(ValueError('listener aborted before completion'))

    def cancel(self, reason):
        """Maintenance-only partial subscription close; not a daemon-exit proof."""
        if self._continuation is None or type(reason) is not str or not 1 <= len(reason) <= 256:
            raise ValueError('maintenance context and bounded cancellation reason required')
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError('concurrent listener cancellation'))
            raise ListenerRefusal(self._result)
        interruption = None
        try:
            if self._cancelled:
                return self.evidence
            if self._done:
                raise ValueError('finite listener already completed, not cancelled')
            self._result['cancellation_requested'] = True
            try:
                self._reserve_events(2)
                self._record('cancellation_requested', reason=reason, allow_failed=True)
                self._owner()
                self._check()
            except BaseException as exc:
                self._abort(exc)
                if not isinstance(exc, Exception):
                    interruption = exc
            finally:
                try:
                    self._close_socket()
                except BaseException as exc:
                    self._abort(exc)
                    if not isinstance(exc, Exception) and interruption is None:
                        interruption = exc
                self._result.update(incomplete_frame_bytes=self._decoder.incomplete_frame_bytes,
                                    socket_close_returned=self._closed and self._result['close_error'] is None,
                                    daemon_exit_proven=False)
                try:
                    self._record('cancellation_result', allow_failed=True,
                                 incomplete_frame_bytes=self._result['incomplete_frame_bytes'],
                                 socket_close_returned=self._result['socket_close_returned'],
                                 close_error=self._result['close_error'], daemon_exit_proven=False)
                except BaseException as exc:
                    self._result['cancel_journal_error'] = _error(exc)
                    self._abort(exc)
                    if not isinstance(exc, Exception) and interruption is None:
                        interruption = exc
                self._cancelled = True
            if interruption is not None:
                raise interruption
            return self.evidence
        finally:
            self._lock.release()

    def poll(self):
        if self._cancelled:
            raise ValueError('listener cancelled')
        if self._done:
            raise ValueError('listener already completed')
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError('concurrent/reentrant listener poll'))
            raise ListenerRefusal(self._result)
        output = dict(stdout=b'', records=[], terminal=None)
        try:
            self._check()
            self._owner()
            if self._offset < len(self._command):
                remaining = self._command[self._offset:]
                self._reserve_events(2)
                self._record('send_attempt', offset=self._offset, raw_hex=remaining.hex(), at_ns=self._check())
                self._owner()
                self._check()
                try:
                    sent = self._connection.send(remaining)
                except BlockingIOError:
                    self._check()
                    return output
                self._returned('send_return', count=sent, offset=self._offset)
                self._check()
                if type(sent) is not int or not 0 < sent <= len(remaining):
                    raise ValueError('invalid or zero command send count')
                self._offset += sent
                if self._offset < len(self._command):
                    return output
            self._owner()
            self._check()
            self._reserve_events(1)
            try:
                raw = self._connection.recv(4096)
            except BlockingIOError:
                self._check()
                return output
            if type(raw) is not bytes or len(raw) > 4096:
                raise ValueError('invalid raw daemon read')
            self._returned('recv_return', raw_hex=raw.hex(), eof=not raw)
            now = self._check()
            self._owner()
            if raw:
                data = self._envelope.feed(raw)
                output['stdout'] = data
                if self._mode == 'snapshot':
                    self._snapshot += data
                    if len(self._snapshot) > 1024:
                        raise ValueError('snapshot byte limit')
                else:
                    output['records'] = self._decoder.feed(data, now)
                    if output['records']:
                        self._last_complete = now
                return output
            exit_code = self._envelope.finish()
            if self._mode == 'snapshot':
                terminal = dict(parse_snapshot(self._snapshot, exit_code), raw_hex=self._snapshot.hex())
            else:
                terminal = self._decoder.finish(now, exit_code)
            self._parsed_terminal = True
            self._record('parsed_eof', terminal=terminal, at_ns=now)
            self._owner()
            self._check()
            self._close_socket()
            self._result['transport_complete'] = self._done = True
            output['terminal'] = terminal
            return output
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise ListenerRefusal(self._result) from exc
        finally:
            self._lock.release()
