"""Join supplied datagram I/O, independent clock and owned wire checks.

No process/socket factory or live authority. The caller must bind the supplied
socket and clock callback to a verified lifecycle, and supervise blocking work.
The code can invoke the supplied socket: offline tests use injected objects only.
"""
from __future__ import annotations

import copy
import socket
from dataclasses import asdict
from threading import Lock, RLock

from tools.benchmark.openvins_datagram_receive import DatagramReceiver
from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.openvins_segmented_journal import event_log
from tools.benchmark.openvins_simulation_clock import JournaledSimulationClock
from tools.benchmark.openvins_timesync_interval import _RestorationWindow
from tools.benchmark.openvins_wire_bootstrap import OwnedWireBootstrap
from tools.benchmark.owned_daemon_connection import LinuxBackend, _error, validate_owner


class ObservedWireSession:
    MAX_SELECTIONS = 4096

    def __init__(self, process, expected, path, remote_clock, clock_lane, sock, start_ns,
                 journal, descriptor_guard, *, backend=None, heartbeat_sink=None, retention=None,
                 interval_transaction=False):
        if (type(remote_clock) is not RemoteMonotonicClock or type(clock_lane) is not JournaledSimulationClock
                or not callable(journal) or not callable(descriptor_guard)
                or type(start_ns) is not int or not 0 <= start_ns < 2**64 - 8_000_000_000
                or heartbeat_sink is not None and not callable(heartbeat_sink)):
            raise ValueError('actual clock types and explicit journal/descriptor guard required')
        validate_owner(expected)
        self._process, self._expected = process, copy.deepcopy(expected)
        self._lane, self._remote, self._sock = clock_lane, remote_clock, sock
        self._backend = backend or LinuxBackend()
        self._journal, self._descriptor_guard = journal, descriptor_guard
        self._heartbeat_sink = heartbeat_sink
        self._interval_enabled = interval_transaction
        self._start = self._last_now = start_ns
        self._deadline = start_ns + 8_000_000_000
        self._maintenance = None
        self._transitioning = self._closing = False
        self._lock, self._state = Lock(), RLock()
        self._failure = self._selection = self._receiver = self._core = None
        self._closed = self._complete = False
        self._retention = retention
        self._restoration = None
        self._restoring = self._restoration_bound = False
        self._restoration_init_error = None
        self._selections, self._cleanup_errors = event_log(retention, 'selection'), []
        self._refusal_journal_error = None
        self._signature = self._clock_signature()
        if clock_lane.session_id != self._signature[0]:
            raise ValueError('clock lane and remote session mismatch')
        self._flags = getattr(socket, 'MSG_DONTWAIT', None)
        if type(self._flags) not in (int, socket.MsgFlag) or self._flags <= 0:
            raise ValueError('MSG_DONTWAIT required for every send')
        self._flags = int(self._flags)
        try:
            self._core = OwnedWireBootstrap(process, expected, path, remote_clock, start_ns,
                                            lambda e: self._forward('core', e), self._send, backend=self._backend,
                                            heartbeat_sink=None if heartbeat_sink is None else self._dispatch_heartbeat,
                                            retention=retention, interval_transaction=interval_transaction,
                                            interval_send_sink=self._send_interval if interval_transaction else None)
            self._receiver = DatagramReceiver(sock, self._context, self._backend.clock, start_ns,
                                               lambda e: self._forward('receiver', e), retention=retention)
        except BaseException as exc:
            self._abort(exc)
            raise

    @property
    def progress(self):
        core = {} if self._core is None else self._core.progress
        receiver = {} if self._receiver is None else self._receiver.progress
        failure = (self._failure or core.get('failure') or receiver.get('failure')
                   or self._lane.progress['failure'] or self._remote.failure
                   or (None if self._retention is None else self._retention.failure))
        complete = self._complete and failure is None
        interval = None if self._core is None or self._core._wire is None else self._core._wire._interval
        state = None if interval is None else interval.progress
        finished = self._restoration_bound and state is not None and state['phase'] == 'done'
        restored = finished and self._restoration.failure is None and state['baseline_restoration_verified']
        return dict(core, failure=failure, observed_bootstrap_complete=complete,
                    restoration_finished=finished, restoration_verified=bool(restored),
                    modeled_bootstrap_ready=complete, transport_bootstrap_complete=complete,
                    network_authorized=False, delivery_proven=False, live_convergence_qualified=False,
                    runtime_source_proven=False, sender_process_proven=False, fusion_qualified=False)

    @property
    def evidence(self):
        return dict(self.progress, selections=copy.deepcopy(self._selections),
                    restoration=None if self._restoration is None else self._restoration.evidence,
                    restoration_init_error=self._restoration_init_error,
                    retention=None if self._retention is None else self._retention.evidence,
                    clock_signature=self._signature, clock=self._lane.evidence,
                    receiver=None if self._receiver is None else self._receiver.evidence,
                    core=None if self._core is None else self._core.evidence,
                    cleanup_errors=copy.deepcopy(self._cleanup_errors),
                    refusal_journal_error=self._refusal_journal_error)

    def _clock_signature(self):
        value = (self._remote.session_id, self._remote.sim_origin_ns, self._remote.remote_origin_ns)
        if type(value[0]) is not str or not value[0] or any(type(v) is not int or not 0 <= v < 2**63 for v in value[1:]):
            raise ValueError('invalid frozen remote clock configuration')
        return value

    def _open(self):
        failure = self.progress['failure']
        if failure is not None:
            raise ValueError('observed session failure latched: ' + failure)
        if self._closed or self._closing or (self._complete and self._maintenance is None and not self._transitioning):
            raise ValueError('observed session completed or closed')

    def _clock(self):
        self._open()
        now = self._backend.clock()
        self._open()
        if type(now) is not int or not self._last_now <= now < 2**64:
            raise ValueError('observed session wall clock invalid/regressed')
        self._last_now = now
        if now >= self._deadline:
            raise ValueError('observed session global deadline')
        return now

    def _context(self):
        """Called by receiver at read/check boundaries; no recursive receiver call."""
        if self._restoring:
            self._restoration_context()
            return
        self._clock()
        if self._descriptor_guard(self._sock) is not None:
            raise ValueError('descriptor guard must return None')
        self._open()
        actual = self._backend.observe(self._process)
        validate_owner(actual)
        if actual != self._expected:
            raise ValueError('observed session owned process changed')
        if self._clock_signature() != self._signature or self._lane.session_id != self._signature[0]:
            raise ValueError('observed clock session/origin changed')
        if self._selection is None:
            self._lane.check()
        else:
            self._lane.validate_selection(self._selection)
        now = self._clock()
        if self._selection is not None:
            selected = self._selection
            if selected.selected_ns > now or min(selected.received_ns, selected.observation.callback_ns) < self._start:
                raise ValueError('clock lane and receiver wall basis inconsistent')
            if (now - selected.received_ns >= 2_000_000_000
                    or now - selected.observation.callback_ns >= 2_000_000_000):
                raise ValueError('selected clock/packet expired at observed send boundary')
        self._open()

    def _forward(self, source, event):
        # Cleanup evidence can be written after failure/close intent. Only this
        # journal path is exempt; _open continues to refuse receive/send work.
        if not self._closing and not self._restoring:
            self._open()
        if self._journal(dict(source=source, event=copy.deepcopy(event))) is not None:
            raise ValueError('observed session journal must return None')
        if self._restoring:
            self._restoration.check(self._backend.clock())
        elif not self._closing:
            self._open()

    def _send(self, raw, peer):
        if self._selection is None:
            raise ValueError('send requires selected independent clock')
        self._receiver.check()
        self._final_boundary()
        # No callback or post-send check here: wire code must first retain the
        # actual return count, including a short write or a later source fault.
        return self._sock.sendto(raw, self._flags, peer)

    def _send_interval(self, raw, peer):
        # Commands need a fresh independent source, but no invented inbound
        # packet selection. Use the same socket/flags and ownership boundary.
        self._receiver.check()
        self._final_boundary()
        return self._sock.sendto(raw, self._flags, peer)

    def _dispatch_heartbeat(self, event):
        self._receiver.check()
        self._final_boundary()
        # Return directly so the core retains partial delivery before checking
        # whether the callback changed health or crossed a deadline.
        return self._heartbeat_sink(event)

    def _final_boundary(self):
        """Check ages after socket profile calls and any state-lock wait.

        Snapshot source health before the final clock read; no journal, guard,
        socket accessor or state-lock acquisition follows that clock read here.
        This is a point-in-time check, not atomic with external source changes
        or the subsequent OS send. No post-send exception may hide its count.
        """
        self._open()
        lane = self._lane.progress
        now = self._backend.clock()
        terminal = self._complete and self._maintenance is None and not self._transitioning
        if self._failure or lane['failure'] or self._remote.failure or self._closed or self._closing or terminal:
            raise ValueError('observed boundary dependency failed or closed')
        if self._clock_signature() != self._signature or lane['session_id'] != self._signature[0]:
            raise ValueError('observed clock session/origin changed')
        if type(now) is not int or not self._last_now <= now < 2**64:
            raise ValueError('observed boundary clock invalid/regressed')
        self._last_now = now
        if now >= self._deadline:
            raise ValueError('observed session global deadline')
        origins = [lane['latest_callback_ns'], lane['pending_callback_ns']]
        if self._selection is not None:
            origins.extend((self._selection.received_ns, self._selection.observation.callback_ns))
            if self._selection.selected_ns > now:
                raise ValueError('selected clock is in the future')
        for origin in origins:
            if origin is not None and (not self._start <= origin <= now or now - origin >= 2_000_000_000):
                raise ValueError('source/selected clock/packet expired at final boundary')

    def _abort(self, exc):
        with self._state:
            if self._failure is not None:
                return
            self._failure = 'observed session refusal'
            self._failure = _error(exc)
        if self._interval_enabled and self._core is not None and self._core._wire is not None:
            try:
                now = self._backend.clock()
                if type(now) is not int or now < self._last_now:
                    raise ValueError('first STOPPING clock invalid/regressed')
                self._last_now = now
                self._restoration = _RestorationWindow(self._core._wire._interval, now)
            except BaseException as clock_error:
                self._restoration_init_error = _error(clock_error)
        try:
            self._close_core(keep_retention=self._restoration is not None)
        except BaseException as cleanup:
            self._cleanup_errors.append(_error(cleanup))
        try:
            if self._journal(dict(source='refusal', event=dict(reason=self._failure))) is not None:
                raise ValueError('refusal journal must return None')
        except BaseException as secondary:
            self._refusal_journal_error = _error(secondary)

    def _operation(self, action, commit, *, transition=False):
        if (self._complete and self._maintenance is None and not self._transitioning
                and not transition and self.progress['failure'] is None):
            raise ValueError('observed session completed or closed')
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError('concurrent observed session operation'))
            raise ValueError('concurrent observed session operation')
        try:
            self._transitioning = transition
            self._open()
            self._receiver.check()
            result = action()
            self._receiver.check()
            with self._state:
                self._final_boundary()
                commit(result)
            return result
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._transitioning = False
            self._selection = None
            self._lock.release()

    def poll_datagram(self):
        def action():
            phases = ('ready', 'pending') if self._maintenance is not None else ('first_ready', 'stream_ready')
            if self._interval_enabled and self._maintenance is None:
                # Receive heartbeats while the daemon listener is waiting. The
                # reply reservation still forbids another TIMESYNC in pending.
                phases += ('empty_pending', 'first_pending', 'first_confirmed',
                           'replay_pending', 'stream_pending', 'finish_pending', 'done')
            if self._core.progress['phase'] not in phases:
                raise ValueError('datagram refused before listener readiness')
            if len(self._selections) >= self.MAX_SELECTIONS:
                raise ValueError('clock selection capacity')
            packet = self._receiver.poll()
            if packet is None:
                return None
            self._selection = self._lane.snapshot(packet.received_ns)
            selected = dict(session_id=self._signature[0], **asdict(self._selection))
            self._selections.append(copy.deepcopy(selected))
            self._forward('selection', selected)
            return self._core.receive(packet.data, packet.peer, packet.received_ns, self._selection.observation.sim_ns)
        return self._operation(action, lambda _: None)

    def poll_listener(self):
        def commit(result):
            if result['wire_bootstrap_complete']:
                self._complete = True
        self._operation(self._core.poll, commit)
        return self.progress

    def poll_interval(self):
        if not self._interval_enabled:
            raise ValueError('interval mode not enabled at construction')
        def commit(result):
            if result['wire_bootstrap_complete']:
                self._complete = True
        self._operation(self._core.poll_interval, commit)
        return self.progress

    def _restoration_context(self):
        """Identity checks only; failed estimator/source state is never cleared."""
        if not self._restoring or self._restoration is None or self._closed or self._closing:
            raise ValueError('restoration not active or session closed')
        now = self._backend.clock()
        self._restoration.check(now)
        if type(now) is not int or now < self._last_now:
            raise ValueError('restoration session clock regression')
        self._last_now = now
        if self._descriptor_guard(self._sock) is not None:
            raise ValueError('restoration descriptor guard must return None')
        actual = self._backend.observe(self._process)
        validate_owner(actual)
        if actual != self._expected:
            raise ValueError('restoration owner changed')
        if self._clock_signature() != self._signature or self._lane.session_id != self._signature[0]:
            raise ValueError('restoration session/origin changed')
        now = self._backend.clock()
        self._restoration.check(now)
        if type(now) is not int or now < self._last_now:
            raise ValueError('restoration session clock regression')
        self._last_now = now
        return now

    def _restoration_guard(self):
        self._restoration_context()

    def _send_restoration(self, raw, peer):
        if peer != self._receiver.PEER or type(peer) is not tuple:
            raise ValueError('restoration send peer changed')
        self._receiver._check_restoration(self._restoration)
        now = self._restoration_context()
        last = self._core._wire._last_unarmed
        if last is None or not 0 <= now - last < 2_000_000_000:
            raise ValueError('restoration send needs fresh unarmed observation')
        # Wire records the actual return before subsequent checks, as in normal I/O.
        return self._sock.sendto(raw, self._flags, peer)

    def begin_restoration(self, reason):
        """Explicit STOPPING; do not close the caller-owned descriptor here."""
        if not self._interval_enabled or self._closed or self._closing:
            raise ValueError('interval restoration unavailable or closed')
        if self._failure is not None and self._restoration is None:
            raise ValueError('first STOPPING has no valid restoration clock')
        if self._restoration is not None and self._restoration.failure is not None:
            raise ValueError('restoration already refused')
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError('concurrent restoration entry'))
            raise ValueError('concurrent restoration entry')
        try:
            if self._failure is None:
                self._abort(ValueError(reason if type(reason) is str else 'explicit stopping'))
            if self._restoration is None:
                raise ValueError('first STOPPING has no valid restoration clock')
            self._restoring = True
            self._restoration_context()
            if not self._restoration_bound:
                self._receiver._bind_restoration(self._restoration)
                self._core._wire._bind_restoration(self._restoration, self._restoration_guard,
                                                   self._send_restoration, self._failure)
                self._restoration_bound = True
            return self.progress
        except BaseException as exc:
            if self._restoration is not None:
                self._restoration.fail(_error(exc))
            self._cleanup_errors.append(_error(exc))
            raise
        finally:
            self._restoring = False
            self._lock.release()

    def poll_restoration(self):
        """One read and at most one restricted command effect per caller tick."""
        if not self._restoration_bound or self._closed or self._closing:
            raise ValueError('restoration not bound or session closed')
        if self._restoration.failure is not None:
            raise ValueError('restoration already refused')
        if not self._lock.acquire(blocking=False):
            self._restoration.fail('concurrent restoration poll')
            raise ValueError('concurrent restoration poll')
        self._restoring = True
        try:
            self._restoration_context()
            packet = self._receiver._poll_restoration(self._restoration)
            if packet is not None:
                self._core._wire._receive_restoration(packet.data, packet.peer, packet.received_ns)
            self._core._wire._poll_restoration()
            self._restoration_context()
            return self.progress
        except BaseException as exc:
            self._restoration.fail(_error(exc))
            self._cleanup_errors.append(_error(exc))
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._restoring = False
            self._lock.release()

    def begin_maintenance(self, deadline_ns):
        """One explicit startup-bounded transition of all existing receive layers."""
        def action():
            if not self._complete or self._maintenance is not None:
                raise ValueError('observed maintenance requires one completed bootstrap')
            context = self._core.begin_maintenance(deadline_ns)
            self._receiver._continue_with(context)
            return context

        def commit(context):
            if self._retention is not None:
                self._retention.phase('maintenance')
            self._maintenance = context
            self._deadline = context.progress['deadline_ns']

        return self._operation(action, commit, transition=True)

    def _close_core(self, *, keep_retention=False):
        if self._closing:
            return
        self._closing = True
        failures = []
        def attempt(action):
            try:
                action()
            except BaseException as exc:
                failures.append(exc)
                self._cleanup_errors.append(_error(exc))
        def stopping():
            if self._retention is not None and not self._retention.evidence['closed']:
                self._retention.phase('stopping')
        try:
            attempt(stopping)
            if self._core is not None:
                attempt(self._core.close)
            if self._retention is not None and not keep_retention:
                attempt(self._retention.close)
        finally:
            self._closing = False
        if failures:
            raise next((exc for exc in failures if not isinstance(exc, Exception)), failures[0])

    def close(self):
        with self._state:
            if self._closed or self._closing:
                return
            try:
                if not self._complete:
                    self._abort(ValueError('observed session closed before completion'))
                    if self._interval_enabled:
                        if self._restoration is not None and not self.progress['restoration_verified']:
                            self._cleanup_errors.append('interval restoration incomplete on close')
                        self._close_core()
                else:
                    self._close_core()
            finally:
                if self._restoration is not None:
                    self._restoration.closed = True
                self._closed = True
