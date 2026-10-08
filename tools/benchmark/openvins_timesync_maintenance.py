"""Internal cold-filter continuation over raw listener bytes, no transport.

Created only by ColdTimesyncBootstrap.take_continuation. Journals/epochs and
explicit now_ns calls are caller observations, not ownership/authentication.
No socket, background watchdog, stream command or live qualification is added.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from threading import Lock

from tools.benchmark.openvins_segmented_journal import SegmentedEvents, event_log, record_failure, require_capacity
from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
from tools.benchmark.owned_daemon_connection import _error


class _TimesyncMaintenance:
    MAX_EVENTS = 65536

    def __init__(self, observer, last_status, last_observed, listener, epoch,
                 now_ns, deadline_ns, journal, source_failure, *, retention=None):
        self._observer = observer
        self._baseline, self._last_observed = copy.deepcopy(last_status), copy.deepcopy(last_observed)
        self._listener, self._epoch = listener, epoch
        self._handoff = self._now = self._last_progress = now_ns
        self._deadline, self._journal, self._source_failure = deadline_ns, journal, source_failure
        self._decoder = TimesyncListenerDecoder(0, 4096, now_ns, output_profile='px4-d6f12ad-multi-v1')
        self._lock = Lock()
        self._phase, self._failure = 'replay_pending', None
        self._seen = self._correlated = 0
        self._events = event_log(retention, 'maintenance')
        self._cancel_journal_error = None
        self._pending_at_cancel = False
        self._transport_claimed = False
        self._record('continuation_received', baseline=self._baseline, observer=self._last_observed,
                     deadline_ns=deadline_ns, counts_as_new_sample=False)

    @property
    def events(self):
        return copy.deepcopy(self._events)

    @property
    def progress(self):
        failure = self._failure or self._source_failure()
        healthy = (failure is None and self._phase == 'ready' and self._correlated > 0
                   and self._last_observed['accepted'])
        return dict(phase=self._phase, failure=failure, listener_token=self._listener,
                    handoff_ns=self._handoff, deadline_ns=self._deadline,
                    transport_claimed=self._transport_claimed,
                    raw_records_seen=self._seen, maintenance_correlated_samples=self._correlated,
                    maintenance_last_progress_ns=self._last_progress,
                    modeled_accepted_samples=self._last_observed['modeled_accepted_samples'],
                    estimated_offset_us=self._last_observed['estimated_offset_us'],
                    maintenance_healthy=healthy,
                    pending_reply=self._phase == 'pending' or self._pending_at_cancel,
                    incomplete_frame_bytes=self._decoder.incomplete_frame_bytes,
                    listener_clean_exit=False, cancel_journal_error=self._cancel_journal_error,
                    live_convergence_qualified=False, network_authorized=False, fusion_qualified=False)

    def _fail(self, reason):
        if self._failure is None:
            self._failure = reason
        raise ValueError(self._failure)

    def _check(self, now_ns, epoch_token):
        failure = self._failure or self._source_failure()
        if failure is not None:
            self._fail('maintenance failure latched: ' + failure)
        if self._phase == 'cancelled':
            self._fail('maintenance cancelled')
        if type(epoch_token) is not str or epoch_token != self._epoch:
            self._fail('maintenance epoch changed')
        if type(now_ns) is not int or not self._now <= now_ns < 2**64:
            self._fail('maintenance clock invalid/regressed')
        self._now = now_ns
        if now_ns >= self._deadline:
            self._fail('maintenance deadline')
        if now_ns - self._last_progress >= 2_000_000_000:
            self._fail('maintenance progress timeout')
        self._observer.check(now_ns)
        self._decoder.check(now_ns)

    def _record(self, kind, *, closing=False, **values):
        require_capacity(self._events, len(self._events), self.MAX_EVENTS)
        event = dict(kind=kind, phase=self._phase, now_ns=self._now,
                     epoch_token=self._epoch, listener_token=self._listener, **copy.deepcopy(values))
        self._events.append(copy.deepcopy(event))
        if self._journal(copy.deepcopy(event)) is not None:
            self._fail('maintenance journal must return None')
        if not closing and (self._failure is not None or self._source_failure() is not None):
            self._fail('failure during maintenance journal')

    @contextmanager
    def _step(self, now_ns, epoch_token):
        if not self._lock.acquire(blocking=False):
            self._fail('concurrent maintenance transition')
        try:
            self._check(now_ns, epoch_token)
            yield
            if self._failure is not None or self._source_failure() is not None:
                self._fail('maintenance dependency failed during transition')
        except BaseException as exc:
            if self._failure is None:
                self._failure = 'maintenance transition: ' + type(exc).__name__
            if isinstance(self._events, SegmentedEvents) or len(self._events) <= self.MAX_EVENTS:
                record_failure(self._events, dict(kind='refusal', phase=self._phase,
                                                 now_ns=self._now, reason=self._failure))
            raise
        finally:
            self._lock.release()

    def check(self, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            return self.progress

    def _claim_transport(self, now_ns):
        """Consume the single listener attachment, including a failed open."""
        with self._step(now_ns, self._epoch):
            if self._transport_claimed or self._phase != 'replay_pending':
                self._fail('maintenance listener transport already claimed or progressed')
            self._record('listener_transport_claim')
            self._transport_claimed = True

    def reserve_reply(self, request_ns, response_ns, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            if self._phase != 'ready':
                self._fail('maintenance reply blocked by phase')
            predicted = copy.deepcopy(self._observer)
            predicted.reserve_reply(request_ns, response_ns, now_ns)
            intent = dict(request_ns=request_ns, response_ns=response_ns, transmission_proven=False,
                          network_authorized=False, fusion_qualified=False)
            self._record('reply_intent', intent=intent)
            self._observer, self._phase = predicted, 'pending'
            return intent

    def feed_stream(self, data, listener_token, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            if type(listener_token) is not str or listener_token != self._listener:
                self._fail('maintenance listener changed')
            if type(data) is not bytes or len(data) > self._decoder.MAX_CHUNK:
                self._fail('invalid maintenance chunk')
            self._record('raw_chunk', raw_hex=data.hex())
            if data and self._phase not in ('replay_pending', 'pending'):
                self._fail('unsolicited maintenance bytes')
            rows = self._decoder.feed(data, now_ns)
            if rows and self._decoder.incomplete_frame_bytes:
                self._fail('bytes after reserved maintenance record')
            for row in rows:
                normalized = dict(row, ordinal=self._baseline['ordinal'] + row['ordinal'] - 1)
                if self._phase == 'replay_pending':
                    if normalized != self._baseline:
                        self._fail('maintenance boundary snapshot mismatch')
                    self._record('boundary_snapshot', raw_status=row, observer_input=normalized,
                                 counts_as_new_sample=False)
                else:
                    if self._phase != 'pending':
                        self._fail('maintenance status without pending reply')
                    predicted = copy.deepcopy(self._observer)
                    observed = predicted.observe_status(normalized, now_ns)
                    self._record('maintenance_status', raw_status=row, observer_input=normalized, observer=observed)
                    self._observer, self._last_observed = predicted, observed
                    self._correlated += 1
                self._seen += 1
                self._phase, self._last_progress = 'ready', now_ns
                if self._seen >= 4096:
                    self._fail('maintenance listener exhausted; rollover forbidden')
            return self.progress

    def cancel(self, reason, *, now_ns, epoch_token):
        """Retain cancellation intent, not proof that a daemon/socket has stopped."""
        if not self._lock.acquire(blocking=False):
            self._fail('concurrent maintenance cancellation')
        try:
            if type(reason) is not str or not 1 <= len(reason) <= 256:
                self._fail('invalid cancellation reason')
            if self._phase == 'cancelled':
                return dict(self.progress, cancellation_requested=True)
            # Cleanup remains recordable after a latched failure or deadline.
            try:
                self._check(now_ns, epoch_token)
            except ValueError as exc:
                if self._failure is None:
                    self._failure = _error(exc)
            pending = self._phase == 'pending'
            self._pending_at_cancel = pending
            try:
                self._record('cancellation_requested', reason=reason, pending_reply=pending,
                             incomplete_frame_bytes=self._decoder.incomplete_frame_bytes,
                             listener_clean_exit=False, closing=True)
            except BaseException as exc:
                self._cancel_journal_error = _error(exc)
                if self._failure is None:
                    self._failure = self._cancel_journal_error
                if not isinstance(exc, Exception):
                    raise
            finally:
                self._phase = 'cancelled'
            return dict(self.progress, pending_reply=pending, cancellation_requested=True)
        finally:
            self._lock.release()
