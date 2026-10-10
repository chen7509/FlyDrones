"""Serial capture scheduling for a supplied, owned observed session.

No I/O factories or live activation. finish restores through the sole polling
owner, joins it and closes the socket. Source validation stays in the session.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import time
from pathlib import Path
from threading import Lock, RLock, Thread, current_thread

from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
from tools.benchmark.owned_daemon_connection import LinuxBackend, _error


class CaptureWireDriver:
    def __init__(self, session, result, *, total_deadline_ns):
        if (type(session) is not ObservedWireSession or not session._interval_enabled
                or type(total_deadline_ns) is not int
                or not session._start < total_deadline_ns <= session._start + 300_000_000_000
                or type(result) is not dict or type(result.get('errors')) is not list):
            raise ValueError('owned interval session, result and original total deadline required')
        self.session, self.result = session, result
        self.deadline = total_deadline_ns
        self.phase = 'startup'
        self.failure = None
        self.closed = False
        self._stop_ns = None
        self._restoring = False
        self._serial = Lock()
        self._thread = None
        self._socket_closed = False
        self._stop_wall_ns = None
        self._health_lock = RLock()
        self._last_poll_ns = self._health_last_ns = session._start

    @property
    def progress(self):
        state = self.session.progress
        return dict(phase=self.phase, closed=self.closed,
                    failure=self.failure or state['failure'],
                    ready=(self.phase == 'maintenance' and not self.closed
                           and self.failure is None and state['failure'] is None
                           and state.get('maintenance_healthy', False)),
                    fusion_qualified=False, network_authorized=False)

    def _fail(self, exc):
        message = _error(exc)
        if self.failure is None:
            self.failure = message
        entry = 'capture wire: ' + message
        if entry not in self.result['errors']:
            self.result['errors'].append(entry)

    def health_ready(self):
        """Point-in-time pre-step gate; no receive, send or blocking join.

        An outstanding pair does not erase earlier health until its original
        deadline. A blocked reader cannot refresh this gate by historical success.
        The caller still checks its own sensor/native/fanout gates.
        """
        with self._health_lock:
            try:
                state = self.session.progress
                lane = self.session._lane.progress
                now = self.session._backend.clock()
                if (self.failure or state['failure'] or self.phase in ('stopping', 'closed')
                        or type(now) is not int or not self._health_last_ns <= now < self.deadline):
                    raise ValueError('capture pre-step failure/clock/closed')
                self._health_last_ns = now
                origins = [self._last_poll_ns, lane['latest_callback_ns'], lane['pending_callback_ns']]
                if self.phase == 'maintenance':
                    origins.append(state['maintenance_last_progress_ns'])
                elif now >= self.session._start + 8_000_000_000:
                    raise ValueError('capture pre-step startup deadline')
                if any(origin is not None and not 0 <= now - origin < 2_000_000_000 for origin in origins):
                    raise ValueError('capture pre-step reader/source/progress expired')
                return (self.phase == 'maintenance' and state['phase'] in ('ready', 'pending')
                        and state['maintenance_correlated_samples'] > 0
                        and state.get('maintenance_last_accepted') is True)
            except BaseException as exc:
                self._fail(exc)
                self.request_stop(self.failure)
                raise

    def request_stop(self, reason=None):
        with self._health_lock:
            self._request_stop_locked(reason)

    def _request_stop_locked(self, reason):
        if self.closed or self._stop_ns is not None:
            return
        self._stop_wall_ns = time.monotonic_ns()
        try:
            self._stop_ns = self.session._backend.clock()
        except BaseException as exc:
            self._fail(exc)
            self._stop_ns = -1  # Invalid clock forbids restoration, not cleanup.
            self.phase = 'stopping'
            if not isinstance(exc, Exception):
                raise
        if type(self._stop_ns) is not int or self._stop_ns < self.session._last_now:
            self._fail(ValueError('capture stopping clock invalid'))
        if reason is not None or not self.progress['ready']:
            self._fail(ValueError(reason or 'capture stopped before healthy maintenance'))
        self.phase = 'stopping'

    def _close(self):
        if self.closed:
            return
        interruptions = []
        actions = [self.session.close]
        if self._thread is None:
            actions.append(self._close_socket)
        for action in actions:
            try:
                action()
            except BaseException as exc:
                self._fail(exc)
                if not isinstance(exc, Exception):
                    interruptions.append(exc)
        # Some evidence owners latch ordinary close failures and return normally.
        # Propagate their terminal state before CaptureJournal decides success.
        try:
            failure = self.session.progress['failure']
            if failure:
                self._fail(ValueError('terminal session failure: ' + failure))
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                interruptions.append(exc)
        self.closed, self.phase = True, 'closed'
        if interruptions:
            raise interruptions[0]

    def _close_socket(self):
        if not self._socket_closed:
            self._socket_closed = True
            self.session._sock.close()

    def _stopping(self):
        try:
            now = self.session._backend.clock()
        except BaseException as exc:
            self._fail(exc)
            self._close()
            if not isinstance(exc, Exception):
                raise
            return
        if (type(now) is not int or type(self._stop_ns) is not int
                or not self._stop_ns <= now < self._stop_ns + 10_000_000_000):
            self._fail(ValueError('capture restoration deadline/clock'))
            self._close()
            return
        state = self.session.progress
        if state.get('interval_transaction_pass') or state.get('restoration_finished'):
            if state.get('restoration_finished') and not state.get('restoration_verified'):
                self._fail(ValueError('capture baseline restoration unverified'))
            self._close()
            return
        try:
            if not self._restoring:
                self.session.begin_restoration(self.failure or 'capture stopping')
                self._restoring = True
            state = self.session.poll_restoration()
            if state['restoration_finished']:
                if not state['restoration_verified']:
                    self._fail(ValueError('capture baseline restoration unverified'))
                self._close()
        except BaseException as exc:
            self._fail(exc)
            self._close()
            if not isinstance(exc, Exception):
                raise

    def _handoff(self):
        if self.phase == 'startup' and self.session.progress['observed_bootstrap_complete']:
            self.session.begin_maintenance(self.deadline)
            with self._health_lock:
                if self.phase == 'startup' and self.failure is None:
                    self.phase = 'maintenance'

    def tick(self):
        if self.closed:
            return self.progress
        if not self._serial.acquire(blocking=False):
            self._fail(ValueError('concurrent capture wire tick'))
            self.request_stop(self.failure)
            raise ValueError('concurrent capture wire tick')
        try:
            if self._thread is not None and current_thread() is not self._thread:
                raise ValueError('capture tick belongs to its managed reader')
            if self.phase == 'stopping':
                self._stopping()
                return self.progress
            try:
                self._handoff()
                if self.phase == 'stopping':
                    return self.progress
                self.session.poll_listener()
                if self.phase == 'stopping':
                    return self.progress
                self._handoff()
                state = self.session.progress
                phases = ('ready', 'pending') if self.phase == 'maintenance' else (
                    'empty_pending', 'first_ready', 'first_pending', 'first_confirmed',
                    'replay_pending', 'stream_pending', 'stream_ready', 'finish_pending', 'done')
                if (state['phase'] in phases
                        and self.session._lane.progress['committed_samples']):
                    self.session.poll_datagram()
                if self.phase == 'stopping':
                    return self.progress
                state = self.session.progress
                if (self.phase == 'startup' and self.session._lane.progress['committed_samples']
                        and (state['interval_phase'] == 'body'
                             or state['phase'] in ('first_ready', 'stream_ready', 'done'))):
                    self.session.poll_interval()
                self._handoff()
                with self._health_lock:
                    self._last_poll_ns = self.session._backend.clock()
            except BaseException as exc:
                self._fail(exc)
                self.request_stop(self.failure)
                if not isinstance(exc, Exception):
                    raise
            return self.progress
        finally:
            self._serial.release()

    def _run(self):
        while not self.closed:
            if (self._stop_wall_ns is not None
                    and time.monotonic_ns() >= self._stop_wall_ns + 10_000_000_000):
                self._fail(ValueError('capture cleanup wall deadline'))
                self._close()
                break
            try:
                self.tick()
            except BaseException as exc:
                self._fail(exc)
                self._close()
                break
            if not self.closed:
                time.sleep(.001)

    def start(self, *, thread_factory=Thread):
        """One receive owner. Factories allow tests to forbid real I/O."""
        if self._thread is not None or self.closed or self.phase != 'maintenance' and self.phase != 'startup':
            raise ValueError('capture reader already started or stopping')
        try:
            self._thread = thread_factory(target=self._run, name='capture-wire', daemon=True)
            self._thread.start()
        except BaseException as exc:
            self._fail(exc)
            # A failed start may still have started a custom factory's thread.
            if self._thread is None or not self._thread.is_alive():
                self._close()
                self._close_socket()
            raise

    def finish(self):
        """Stop, restore through the same owner, join, then close its descriptor.

        A join timeout is a failure; the live reader's descriptor stays owned.
        Blocking callbacks still require outer process supervision.
        """
        if self.closed and self._socket_closed:
            return
        self.request_stop()
        if self._thread is None:
            self._run()
            return
        remaining = (0 if self._stop_wall_ns is None else
                     max(0, (self._stop_wall_ns + 10_000_000_000 - time.monotonic_ns()) / 1e9))
        self._thread.join(timeout=remaining)
        if self._thread.is_alive():
            exc = RuntimeError('capture reader did not join before cleanup deadline')
            self._fail(exc)
            raise exc
        if not self.closed:
            self._fail(ValueError('capture reader exited without terminal cleanup'))
            self._close()
        try:
            self._close_socket()
        except BaseException as exc:
            self._fail(exc)
            raise


def bind_capture_wire(fixture, journal, result, session, original_post, *, total_deadline_ns,
                      register_cleanup=True, register_callback=True):
    """Register one clock callback and restoration before owned PX4 stop (20)."""
    driver = None
    def post(info, ecm):
        try:
            if driver.phase in ('stopping', 'closed'):
                raise ValueError('capture PostUpdate after stopping or closed')
            session._lane.post_update(info)
            original_post(info, ecm)
        except BaseException as exc:
            driver._fail(exc)
            try:
                driver.request_stop(driver.failure)
            except BaseException as stop_exc:
                driver._fail(stop_exc)
            # This callback runs on Gazebo's native worker. Propagating a Python
            # exception here can abort the process before CaptureJournal cleanup.
            # Keep the failure latched: pre-step health refuses further force and
            # the existing outer runner raises after its bounded stepping chunk.
    try:
        driver = CaptureWireDriver(session, result, total_deadline_ns=total_deadline_ns)
        if not callable(original_post):
            raise ValueError('original PostUpdate callback required')
        if register_cleanup:
            journal.cleanup('capture wire', driver.finish, priority=15)
        if register_callback:
            fixture.on_post_update(post)
    except BaseException as exc:
        if driver is not None:
            driver._fail(exc)
            driver._close()
        elif type(session) is ObservedWireSession:
            try:
                session.close()
            finally:
                session._sock.close()
        raise
    return driver


def socket_identity(sock):
    """Ordinary same-descriptor drift check; no PID authentication or ABA claim."""
    fd = sock.fileno()
    value = os.fstat(fd)
    if type(fd) is not int or fd < 0 or not stat.S_ISSOCK(value.st_mode):
        raise ValueError('capture datagram descriptor is not a socket')
    return dict(fd=fd, device=value.st_dev, inode=value.st_ino, mode=value.st_mode,
                net=os.readlink('/proc/self/ns/net'))


class CaptureWireOwner:
    """One selected socket, clock, retention store and later-owned PX4 session."""
    def __init__(self, journal, result, output, config, *, start_ns, total_deadline_ns,
                 source_guard, heartbeat_sink, socket_factory=socket.socket, backend=None,
                 descriptor_snapshot=socket_identity):
        from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
        from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal
        from tools.benchmark.openvins_simulation_clock import JournaledSimulationClock

        self.result, self.output, self.journal = result, Path(output), journal
        self.backend = backend or LinuxBackend()
        self.config, self.start_ns, self.deadline = dict(config), start_ns, total_deadline_ns
        self.snapshot, self.heartbeat_sink = descriptor_snapshot, heartbeat_sink
        self.driver = self.sock = self.store = self.clock_file = None
        self.startup_gate = self.startup_probe = self.startup_file = None
        self.startup_process = self.startup_expected = None
        self.startup_transition = None
        self.startup_transition_count = None
        self.startup_refusal = self.startup_probe_refusal = None
        self.startup_callback_registered = False
        self.source_guard = source_guard
        self.finished = False
        self.failure = None
        journal.cleanup('capture wire owner', self.finish, priority=15)
        try:
            self.sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.sock.bind(('127.0.0.1', 14548))
            self.sock.setblocking(False)
            self.descriptor = self.snapshot(self.sock)
            self.store = SegmentedWireJournal(self.output / 'wire-segments')
            self.clock_file = (self.output / 'wire-clock.jsonl').open('x', encoding='utf8')
            self.remote = RemoteMonotonicClock(config['session_id'], sim_origin_ns=config['sim_origin_ns'],
                                              remote_origin_ns=config['remote_origin_ns'])
            self.lane = JournaledSimulationClock(config['session_id'], self.backend.clock,
                                                 self._clock_record, start_ns, source_guard)
        except BaseException as exc:
            self._fail(exc)
            self.finish()
            raise

    def _fail(self, exc):
        self.failure = self.failure or _error(exc)
        entry = 'capture wire owner: ' + _error(exc)
        if entry not in self.result['errors']:
            self.result['errors'].append(entry)

    def _clock_record(self, row):
        encoded = json.dumps(row, allow_nan=False) + '\n'
        if self.clock_file.write(encoded) != len(encoded):
            raise OSError('short independent clock write')
        self.clock_file.flush()

    def _descriptor_guard(self, sock):
        if sock is not self.sock or self.snapshot(sock) != self.descriptor:
            raise ValueError('capture descriptor identity changed')

    def _startup_record(self, row):
        encoded = json.dumps(row, allow_nan=False) + '\n'
        if self.startup_file.write(encoded) != len(encoded):
            raise OSError('short startup evidence write')
        self.startup_file.flush()

    def begin_startup(self, process, fixture, original_post, *, log_path, initial_log, spawn_ns):
        """Register the clock before Finalize; defer every cold wire side effect."""
        if (self.config.get('schema') != 'capture-wire-startup-v2' or self.driver is not None
                or self.startup_gate is not None or self.finished or self.failure):
            raise ValueError('staged startup owner unavailable')
        from tools.benchmark.declared_runtime_snapshot import write_manifest
        from tools.benchmark.px4_startup_phase_gate import StartupPhaseGate

        try:
            self._descriptor_guard(self.sock)
            expected = self.backend.observe(process)
            if expected['net'] != self.descriptor['net']:
                raise ValueError('startup owner/descriptor network namespace mismatch')
            write_manifest(self.output / 'wire-owner.json', dict(
                owner=expected, descriptor=self.descriptor, configuration=self.config,
                start_ns=self.start_ns, total_deadline_ns=self.deadline,
                startup_spawn_ns=spawn_ns))
            self.startup_file = (self.output / 'wire-startup-events.jsonl').open('x', encoding='utf8')
            self.startup_gate = StartupPhaseGate(
                process, expected, log_path, initial_log, spawn_ns,
                spawn_ns + self.config['startup_max_wall_ns'], self._startup_record,
                self.source_guard, backend=self.backend)
            self.startup_process, self.startup_expected = process, expected
            if not callable(original_post):
                raise ValueError('original PostUpdate callback required')

            def post(info, ecm):
                try:
                    if self.failure or self.finished or (self.driver is not None
                            and self.driver.phase in ('stopping', 'closed')):
                        raise ValueError('capture PostUpdate after failure or close')
                    self.lane.post_update(info)
                    original_post(info, ecm)
                except BaseException as exc:
                    self._fail(exc)
                    if self.driver is not None:
                        self.driver._fail(exc)
                        try:
                            self.driver.request_stop(self.driver.failure)
                        except BaseException as stop_exc:
                            self._fail(stop_exc)
                    # Native callback exceptions cannot skip CaptureJournal cleanup.

            fixture.on_post_update(post)
            self.startup_callback_registered = True
        except BaseException as exc:
            if hasattr(exc, 'evidence'):
                self.startup_refusal = exc.evidence
            self._fail(exc)
            raise

    def advance_startup(self):
        """One bounded main-thread status step after a completed simulation chunk."""
        if self.failure or self.finished or self.startup_gate is None or not self.startup_callback_registered:
            raise ValueError('startup phase failed, absent or closed')
        if self.driver is not None:
            return self.driver.progress
        from tools.benchmark.px4_owned_startup_probe import OwnedMavlinkStatusProbe, StatusProbeRefusal
        from tools.benchmark.px4_startup_phase_gate import StartupPhaseRefusal

        try:
            if self.startup_transition is None:
                progress = self.startup_gate.poll_log()
                if progress['log_ready']:
                    if self.startup_probe is None:
                        path = Path('/tmp/px4-sock-8')
                        if path.is_socket():
                            now = self.backend.clock()
                            self.startup_probe = OwnedMavlinkStatusProbe(
                                self.startup_process, self.startup_expected, str(path), now,
                                min(now + 2_000_000_000,
                                    self.startup_gate._deadline), self._startup_record,
                                backend=self.backend)
                    if self.startup_probe is not None:
                        parsed = self.startup_probe.poll()
                        if parsed is not None:
                            self.startup_gate.accept_status(self.startup_probe)
                            self.startup_probe = None
                if self.startup_gate.progress['status_ready'] and self.startup_gate.progress['log_ready']:
                    self.startup_transition = self.startup_gate.transition()
                    self.startup_transition_count = self.lane.progress['committed_samples']
                return self.startup_gate.progress

            self.startup_gate.poll_log(after_transition=True)
            start_ns = self.startup_transition['startup_ready_monotonic_ns']
            lane = self.lane.progress
            now = self.backend.clock()
            if (lane['failure'] is not None or type(now) is not int
                    or not start_ns <= now < start_ns + 8_000_000_000):
                raise ValueError('post-transition clock failure or cold deadline')
            latest = lane['latest_callback_ns']
            if (lane['committed_samples'] <= self.startup_transition_count
                    or latest is None or latest < start_ns
                    or lane['pending_callback_ns'] is not None):
                if now - start_ns >= 2_000_000_000:
                    raise TimeoutError('post-transition source callback absent')
                return self.startup_gate.progress
            if now - latest >= 2_000_000_000:
                raise TimeoutError('post-transition source callback stale')
            if self.backend.observe(self.startup_process) != self.startup_expected:
                raise ValueError('post-transition PX4 owner changed')
            self._descriptor_guard(self.sock)
            session = ObservedWireSession(
                self.startup_process, self.startup_expected, '/tmp/px4-sock-8',
                self.remote, self.lane, self.sock, start_ns,
                lambda _: None, self._descriptor_guard, backend=self.backend,
                heartbeat_sink=self.heartbeat_sink, retention=self.store,
                interval_transaction=True)
            self.driver = bind_capture_wire(
                None, self.journal, self.result, session, lambda *_: None,
                total_deadline_ns=self.deadline, register_cleanup=False,
                register_callback=False)
            self.driver.start()
            return self.startup_gate.progress
        except BaseException as exc:
            if isinstance(exc, StatusProbeRefusal):
                self.startup_probe_refusal = exc.evidence
            elif isinstance(exc, StartupPhaseRefusal):
                self.startup_refusal = exc.evidence
            self._fail(exc)
            raise

    def bind(self, process, fixture, original_post):
        if self.config.get('schema') == 'capture-wire-startup-v2':
            raise ValueError('staged startup requires begin_startup before cold session')
        if self.driver is not None or self.finished or self.failure:
            raise ValueError('capture wire owner already bound, failed or closed')
        from tools.benchmark.declared_runtime_snapshot import write_manifest
        try:
            self._descriptor_guard(self.sock)
            expected = self.backend.observe(process)
            if expected['net'] != self.descriptor['net']:
                raise ValueError('capture owner/descriptor network namespace mismatch')
            write_manifest(self.output / 'wire-owner.json', dict(owner=expected, descriptor=self.descriptor,
                           configuration=self.config, start_ns=self.start_ns, total_deadline_ns=self.deadline))
            # Core channel logs and final session evidence retain the events;
            # the forwarding callback does not duplicate the bounded store.
            session = ObservedWireSession(process, expected, '/tmp/px4-sock-8', self.remote,
                                           self.lane, self.sock, self.start_ns, lambda _: None,
                                           self._descriptor_guard, backend=self.backend,
                                           heartbeat_sink=self.heartbeat_sink, retention=self.store,
                                           interval_transaction=True)
            self.driver = bind_capture_wire(fixture, self.journal, self.result, session, original_post,
                                            total_deadline_ns=self.deadline, register_cleanup=False)
            return self.driver
        except BaseException as exc:
            self._fail(exc)
            raise

    def health_ready(self):
        if self.failure or self.finished:
            raise ValueError('capture wire owner failed/closed')
        return False if self.driver is None else self.driver.health_ready()

    def finish(self):
        if self.finished:
            return
        failures = []
        if self.startup_probe is not None:
            try:
                self.startup_probe.close()
            except BaseException as exc:
                self._fail(exc)
                failures.append(exc)
        try:
            if self.driver is None:
                self._fail(ValueError('capture wire never bound'))
                if self.sock is not None:
                    self.sock.close()
            else:
                self.driver.finish()
        except BaseException as exc:
            self._fail(exc)
            failures.append(exc)
        if self.driver is not None and self.driver._thread is not None and self.driver._thread.is_alive():
            # Do not close or inspect journals still being written by the reader.
            raise RuntimeError('capture reader remains live; retention remains owned')
        for resource in (self.store, self.clock_file, self.startup_file):
            if resource is not None:
                try:
                    resource.close()
                except BaseException as exc:
                    self._fail(exc)
                    failures.append(exc)
        if self.store is not None and self.store.failure:
            self._fail(ValueError('terminal retention failure: ' + self.store.failure))
        evidence = dict(failure=self.failure, fusion_qualified=False, network_authorized=False,
                        driver=None if self.driver is None else self.driver.progress,
                        session=None if self.driver is None else self.driver.session.evidence,
                        startup=(self.startup_gate.evidence if self.startup_gate is not None
                                 else self.startup_refusal),
                        startup_probe=(self.startup_probe.evidence if self.startup_probe is not None
                                       else self.startup_probe_refusal))
        self.result['wire_lifecycle'] = evidence
        try:
            from tools.benchmark.declared_runtime_snapshot import write_manifest
            write_manifest(self.output / 'wire-lifecycle.json', evidence)
        except BaseException as exc:
            self._fail(exc)
            failures.append(exc)
        self.finished = True
        if failures:
            raise next((e for e in failures if not isinstance(e, Exception)), failures[0])
