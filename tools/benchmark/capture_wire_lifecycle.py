"""Serial capture scheduling for a supplied, owned observed session.

No I/O factories or live activation. finish restores through the sole polling
owner, joins it and closes the socket. Source validation stays in the session.
"""
from __future__ import annotations

import time
from threading import Lock, Thread, current_thread

from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
from tools.benchmark.owned_daemon_connection import _error


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

    def request_stop(self, reason=None):
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


def bind_capture_wire(fixture, journal, result, session, original_post, *, total_deadline_ns):
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
            driver.request_stop(driver.failure)
            raise
    try:
        driver = CaptureWireDriver(session, result, total_deadline_ns=total_deadline_ns)
        if not callable(original_post):
            raise ValueError('original PostUpdate callback required')
        journal.cleanup('capture wire', driver.finish, priority=15)
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
