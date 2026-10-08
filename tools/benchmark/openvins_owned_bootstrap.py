"""Owned read-only listener composition; reply intents are not transmissions.

No PX4 launch, MAVLink sender, stream mutation or live/fusion authorization.
Synchronous process/journal operations need external bounded supervision.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import PurePosixPath
from threading import Lock

from tools.benchmark.openvins_listener_transport import ListenerRefusal, ReadOnlyListener
from tools.benchmark.openvins_timesync_bootstrap import ColdTimesyncBootstrap
from tools.benchmark.owned_daemon_connection import LinuxBackend, _error, validate_owner


class BootstrapRefusal(ValueError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(evidence["failure"])


class OwnedBootstrap:
    MAX_EVENTS = 65536

    def __init__(self, process, expected, path, session_id, start_ns, journal, *, stream_records=500, backend=None):
        validate_owner(expected)
        if type(process.pid) is not int or process.pid != expected["pid"]:
            raise ValueError("owned process PID mismatch")
        if (
            type(path) is not str
            or not path.startswith("/")
            or "\0" in path
            or ".." in PurePosixPath(path).parts
            or not 1 <= len(os.fsencode(path)) <= 107
        ):
            raise ValueError("explicit bounded socket path required")
        if type(start_ns) is not int or not 0 <= start_ns < 2**64 - 8000000000 or not callable(journal):
            raise ValueError("invalid start clock or journal")
        self._process, self._owner_expected, self._path = process, copy.deepcopy(expected), path
        self._backend, self._journal = backend or LinuxBackend(), journal
        self._start = self._last_now = start_ns
        self._deadline = start_ns + 8000000000
        self._epoch = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
        self._listener_token = self._epoch + "-stream"
        self._lock = Lock()
        self._fault = None
        self._done = False
        self._events = []
        self._regular_events = 0
        self._transports = []
        self._current = self._role = None
        self._construction_refusal = None
        self._cleanup_errors = []
        self._refusal_journal_error = None
        self._count = stream_records
        self._stream_frame_ns = None
        self._maintenance = None
        self._maintenance_closed = self._transitioning = self._cleaning = False
        self._bootstrap = ColdTimesyncBootstrap(
            session_id, self._epoch, start_ns, lambda event: self._record("bootstrap", event), stream_records=stream_records
        )
        self._clock()

    @property
    def progress(self):
        result = self._bootstrap.progress
        if self._maintenance is not None:
            result.update(self._maintenance.progress)
        complete = self._done and self._fault is None
        result.update(
            failure=self._fault or result["failure"], transport_bootstrap_complete=complete, modeled_bootstrap_ready=complete,
            bootstrap_completed=self._done, maintenance_closed=self._maintenance_closed,
            maintenance_healthy=(self._maintenance is not None and self._fault is None
                                 and not self._maintenance_closed and result.get('maintenance_healthy', False)),
        )
        return result

    @property
    def evidence(self):
        return dict(
            self.progress,
            events=copy.deepcopy(self._events),
            owner=copy.deepcopy(self._owner_expected),
            path=self._path,
            start_ns=self._start,
            deadline_ns=self._deadline,
            identity_tag_basis="owner hash, not cold-epoch proof",
            bootstrap_progress=self._bootstrap.progress,
            bootstrap_events=self._bootstrap.events,
            maintenance_progress=None if self._maintenance is None else self._maintenance.progress,
            maintenance_events=[] if self._maintenance is None else self._maintenance.events,
            transports=[transport.evidence for transport in self._transports],
            construction_refusal=copy.deepcopy(self._construction_refusal),
            cleanup_errors=copy.deepcopy(self._cleanup_errors),
            refusal_journal_error=self._refusal_journal_error,
        )

    def _clock(self):
        if self._fault:
            raise ValueError("owned bootstrap failure latched: " + self._fault)
        now = self._backend.clock()
        if type(now) is not int or not self._last_now <= now < 2**64:
            raise ValueError("owned bootstrap clock regression")
        self._last_now = now
        deadline = min(self._deadline, self._start + 8000000000) if self._transitioning else self._deadline
        if now >= deadline:
            raise ValueError("owned bootstrap global deadline")
        return now

    def _check(self):
        now = self._clock()
        actual = self._backend.observe(self._process)
        validate_owner(actual)
        if actual != self._owner_expected:
            raise ValueError("owned bootstrap owner changed")
        now = self._clock()
        if self._stream_frame_ns is not None and now - self._stream_frame_ns >= 2000000000:
            raise ValueError("owned bootstrap final complete-frame timeout")
        if self._maintenance is not None:
            self._maintenance.check(now_ns=now, epoch_token=self._epoch)
        elif self._bootstrap.progress["phase"] != "done":
            self._bootstrap.check(now_ns=now, epoch_token=self._epoch)
        return now

    def _record(self, source, event, command_index=None):
        if self._regular_events >= self.MAX_EVENTS:
            raise ValueError("owned bootstrap event limit")
        # Cleanup journals retain the last accepted time; they do not grant an
        # exception to owner/deadline checks for any ordinary operation or I/O.
        envelope = dict(source=source, command_index=command_index, event=copy.deepcopy(event),
                        at_ns=self._last_now if self._cleaning else self._clock())
        if self._cleaning:
            envelope['time_basis'] = 'last_checked_clock_during_cleanup'
        self._regular_events += 1
        self._events.append(copy.deepcopy(envelope))
        if self._journal(copy.deepcopy(envelope)) is not None:
            raise ValueError("owned bootstrap journal must return None")
        if not self._cleaning:
            self._clock()

    def _stop_maintenance(self, reason):
        if self._cleaning or self._maintenance_closed:
            return
        self._cleaning = True
        interruption = None
        try:
            # Cancel socket first: cancelling the context first would make even
            # the normal owned listener cleanup appear as a context failure.
            if self._current is not None and self._role == 'maintenance':
                try:
                    result = self._current.cancel(reason)
                    for key in ('error', 'close_error', 'cancel_journal_error'):
                        if result.get(key) is not None:
                            self._cleanup_errors.append(result[key])
                except BaseException as exc:
                    self._cleanup_errors.append(_error(exc))
                    if not isinstance(exc, Exception):
                        interruption = exc
            try:
                result = self._maintenance.cancel(reason, now_ns=self._last_now, epoch_token=self._epoch)
                if result['failure'] is not None:
                    self._cleanup_errors.append(result['failure'])
            except BaseException as exc:
                self._cleanup_errors.append(_error(exc))
                if not isinstance(exc, Exception) and interruption is None:
                    interruption = exc
            self._maintenance_closed = True
            if self._cleanup_errors and self._fault is None:
                self._fault = self._cleanup_errors[0]
        finally:
            self._cleaning = False
        if interruption is not None:
            raise interruption

    def _abort(self, error):
        first = self._fault is None
        if first:
            self._fault = _error(error)
        if self._maintenance is not None:
            try:
                self._stop_maintenance('owned maintenance refusal')
            except BaseException as exc:
                self._cleanup_errors.append(_error(exc))
        elif self._current is not None:
            try:
                self._current.close()
            except BaseException as exc:
                self._cleanup_errors.append(_error(exc))
        if first:
            event = dict(
                source="coordinator", command_index=None, event=dict(kind="refusal", reason=self._fault), at_ns=self._last_now
            )
            self._events.append(copy.deepcopy(event))
            try:
                if self._journal(copy.deepcopy(event)) is not None:
                    raise ValueError("refusal journal must return None")
            except BaseException as exc:
                self._refusal_journal_error = _error(exc)

    @contextmanager
    def _step(self, *, allow_completed=False):
        if self._maintenance_closed:
            raise ValueError('owned maintenance closed')
        if self._done and self._maintenance is None and not allow_completed:
            raise ValueError("owned bootstrap already completed")
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError("concurrent owned bootstrap operation"))
            raise BootstrapRefusal(self.evidence)
        try:
            self._check()
            yield
            self._check()
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise BootstrapRefusal(self.evidence) from exc
        finally:
            self._lock.release()

    def reserve_reply(self, request_ns, response_ns):
        with self._step():
            consumer = self._maintenance if self._maintenance is not None else self._bootstrap
            result = consumer.reserve_reply(request_ns, response_ns, now_ns=self._check(), epoch_token=self._epoch)
        return result

    def begin_maintenance(self, deadline_ns):
        """Transfer once within startup8s; does not open a command or send a reply."""
        self._transitioning = True
        try:
            with self._step(allow_completed=True):
                if not self._done or self._current is not None or self._maintenance is not None:
                    raise ValueError('owned maintenance requires completed, untransferred bootstrap')
                self._maintenance = self._bootstrap.take_continuation(
                    self._epoch + '-maintenance', deadline_ns,
                    lambda event: self._record('maintenance', event),
                    now_ns=self._check(), epoch_token=self._epoch)
                self._record('coordinator', dict(kind='maintenance_started', deadline_ns=deadline_ns))
                self._deadline = deadline_ns
            return self._maintenance
        finally:
            self._transitioning = False

    def check(self, *, allow_completed=False):
        """Check existing ownership/deadlines without opening or reading a command."""
        with self._step(allow_completed=allow_completed):
            pass
        return self.progress

    def _open(self, role):
        index = len(self._transports)
        if index >= 4 or role != ("empty", "first", "stream", "maintenance")[index]:
            raise ValueError("unexpected listener command order")
        if role == "stream":
            self._bootstrap.begin_stream(self._listener_token, now_ns=self._check(), epoch_token=self._epoch)
        self._record("coordinator", dict(kind="command_open", role=role), index)
        self._check()
        try:
            transport = ReadOnlyListener(
                self._process,
                self._owner_expected,
                self._path,
                "stream" if role in ('stream', 'maintenance') else "snapshot",
                4096 if role == 'maintenance' else self._count if role == "stream" else 1,
                self._maintenance.progress['handoff_ns'] if role == 'maintenance' else self._start,
                self._deadline,
                lambda event: self._record("transport", event, index),
                backend=self._backend,
                continuation=self._maintenance if role == 'maintenance' else None,
            )
        except ListenerRefusal as exc:
            self._construction_refusal = exc.evidence
            raise
        self._transports.append(transport)
        self._current, self._role = transport, role

    def poll(self):
        with self._step():
            if self._current is None:
                role = {"empty_pending": "empty", "first_pending": "first", "first_confirmed": "stream"}.get(
                    self._bootstrap.progress["phase"]
                )
                if self._maintenance is not None:
                    role = 'maintenance'
                if role is not None:
                    self._open(role)
            if self._current is not None:
                output = self._current.poll()
                now = self._check()
                if self._role in ('stream', 'maintenance') and output["stdout"]:
                    consumer = self._maintenance if self._role == 'maintenance' else self._bootstrap
                    token = consumer.progress['listener_token'] if self._role == 'maintenance' else self._listener_token
                    consumer.feed_stream(output["stdout"], token, now_ns=now, epoch_token=self._epoch)
                    if output["records"]:
                        self._stream_frame_ns = now
                if output["terminal"] is not None:
                    if self._role == 'maintenance':
                        raise ValueError('maintenance listener ended; rollover forbidden')
                    if self._role == "stream":
                        self._bootstrap.finish_stream(0, self._listener_token, now_ns=self._check(), epoch_token=self._epoch)
                    else:
                        raw = bytes.fromhex(output["terminal"]["raw_hex"])
                        confirm = self._bootstrap.confirm_empty if self._role == "empty" else self._bootstrap.confirm_first
                        confirm(raw, 0, now_ns=self._check(), epoch_token=self._epoch)
                    self._record("coordinator", dict(kind="command_finished", role=self._role), len(self._transports) - 1)
                    self._current = None
                    self._check()
        if self._bootstrap.progress["phase"] == "done":
            self._done = True
        return self.progress

    def close(self):
        if self._maintenance is not None:
            if not self._lock.acquire(blocking=False):
                self._abort(ValueError('concurrent owned maintenance close'))
                return
            try:
                if not self._maintenance_closed:
                    try:
                        self._check()
                    except BaseException as exc:
                        self._abort(exc)
                        if not isinstance(exc, Exception):
                            raise
                    self._stop_maintenance('owned maintenance close')
            finally:
                self._lock.release()
            return
        if not self._done and self._fault is None:
            self._abort(ValueError("owned bootstrap aborted before completion"))
