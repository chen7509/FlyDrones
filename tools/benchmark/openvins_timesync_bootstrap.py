"""Offline first-snapshot/stream composition, never proof of actual PX4 ownership.

Epoch/listener tokens are comparison tags supplied by an external harness. They
do not prove process freshness, exclusive responders or a transmitted reply.
Caller must bound I/O and poll check(); no background or blocking-call watchdog.
"""
from __future__ import annotations

import copy
import hashlib
import re
from contextlib import contextmanager
from threading import Lock

from tools.benchmark.openvins_segmented_journal import SegmentedEvents, event_log, record_failure, require_capacity
from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
from tools.benchmark.openvins_timesync_observer import SerialTimesyncObserver


def parse_snapshot(raw: bytes, exit_code: int) -> dict:
    if type(raw) is not bytes or len(raw) > 1024:
        raise ValueError('invalid snapshot bytes')
    if type(exit_code) is not int or exit_code != 0:
        raise ValueError('snapshot nonzero or unknown exit')
    result = dict(raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                  instance_basis='pinned default subscription, not MAVLink channel')
    if raw == b'never published\n':
        return dict(result, kind='empty', status=None)
    header = b'\nTOPIC: timesync_status\n'
    if not raw.startswith(header):
        raise ValueError('ambiguous or unknown snapshot format')
    # Only the exact upstream implicit header is adapted. The original bytes/hash
    # remain distinct from the parser's temporary explicit-subscription header.
    parser = TimesyncListenerDecoder(0, 1, 0)
    rows = parser.feed(b'\nTOPIC: timesync_status instance 0 #1\n' + raw[len(header):], 0)
    parser.finish(0, 0)
    if len(rows) != 1:
        raise ValueError('snapshot record count')
    return dict(result, kind='single', status=rows[0])


def _token(value) -> bool:
    return type(value) is str and 1 <= len(value) <= 128 and re.fullmatch(r'[A-Za-z0-9_.:-]+', value) is not None


class ColdTimesyncBootstrap:
    READINESS_NS = 8_000_000_000
    PROGRESS_NS = 2_000_000_000
    MAX_EVENTS = 65536

    def __init__(self, session_id, epoch_token, start_ns, journal, *, stream_records=500, retention=None):
        if not _token(session_id) or not _token(epoch_token) or not callable(journal):
            raise ValueError('invalid bootstrap identity or journal')
        if type(start_ns) is not int or not 0 <= start_ns < 2**64:
            raise ValueError('invalid start clock')
        if type(stream_records) is not int or not 500 <= stream_records <= 4096:
            raise ValueError('invalid frozen stream count')
        self._epoch = epoch_token
        self._session = session_id
        self._start = self._now = self._last_progress = start_ns
        self._journal = journal
        self._expected = stream_records
        self._phase = 'empty_pending'
        self._fault = None
        self._retention = retention
        self._events = event_log(retention, 'cold')
        self._lock = Lock()
        self._observer = SerialTimesyncObserver(session_id, 0)
        self._first = self._last_observer = self._decoder = self._listener = None
        self._last_status = None
        self._continuation_taken = False
        self._seen = 0

    @property
    def events(self):
        return copy.deepcopy(self._events)

    @property
    def progress(self):
        count = 0 if self._last_observer is None else self._last_observer['modeled_accepted_samples']
        return dict(phase=self._phase, failure=self._fault, stream_records_seen=self._seen,
                    continuation_taken=self._continuation_taken,
                    modeled_accepted_samples=count, modeled_bootstrap_ready=self._phase == 'done' and self._fault is None,
                    live_convergence_qualified=False, network_authorized=False, fusion_qualified=False)

    def _fail(self, reason):
        if self._fault is None:
            self._fault = reason
        raise ValueError(reason)

    @contextmanager
    def _step(self, now_ns, epoch_token, *, transfer=False):
        if not self._lock.acquire(blocking=False):
            self._fail('concurrent bootstrap transition')
        had_fault = self._fault is not None
        try:
            if self._fault is not None:
                raise ValueError('bootstrap failure latched: ' + self._fault)
            if self._phase == 'done' and not transfer:
                self._fail('bootstrap already finished')
            if transfer and self._continuation_taken:
                self._fail('bootstrap continuation already taken')
            if type(epoch_token) is not str or epoch_token != self._epoch:
                self._fail('PX4 epoch comparison tag changed')
            if type(now_ns) is not int or not self._now <= now_ns < 2**64:
                self._fail('invalid or regressed local clock')
            self._now = now_ns
            if now_ns - self._start >= self.READINESS_NS:
                self._fail('readiness window expired')
            if now_ns - self._last_progress >= self.PROGRESS_NS:
                self._fail('bootstrap progress timeout')
            self._observer.check(now_ns)
            if self._decoder is not None and self._phase != 'done':
                self._decoder.check(now_ns)
            yield
        except BaseException as exc:
            if self._fault is None:
                self._fault = 'transition failure: ' + type(exc).__name__
            if not had_fault and (isinstance(self._events, SegmentedEvents) or len(self._events) <= self.MAX_EVENTS):
                record_failure(self._events, dict(kind='refusal', phase=self._phase, now_ns=self._now,
                                                 error_type=type(exc).__name__, reason=self._fault))
            raise
        finally:
            self._lock.release()

    def _require(self, phase):
        if self._phase != phase:
            self._fail('unexpected phase: ' + self._phase + ', expected ' + phase)

    def _record(self, kind, **values):
        require_capacity(self._events, len(self._events), self.MAX_EVENTS)
        event = dict(kind=kind, phase=self._phase, now_ns=self._now, epoch_token=self._epoch,
                     session_id=self._session, **copy.deepcopy(values))
        result = self._journal(copy.deepcopy(event))
        if self._fault is not None:
            raise ValueError('bootstrap failure latched during journal')
        if result is not None:
            self._fail('journal completion must return None')
        self._events.append(event)

    def _advance(self, phase):
        self._phase = phase
        self._last_progress = self._now

    def check(self, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            return self.progress

    def confirm_empty(self, raw, exit_code, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            self._require('empty_pending')
            result = parse_snapshot(raw, exit_code)
            if result['kind'] != 'empty':
                self._fail('pre-reply snapshot was not empty')
            self._record('empty_snapshot', raw_hex=raw.hex(), snapshot=result)
            self._advance('first_ready')
            return self.progress

    def reserve_reply(self, request_ns, response_ns, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            if self._phase not in ('first_ready', 'stream_ready'):
                self._fail('reply blocked by phase: ' + self._phase)
            predicted = copy.deepcopy(self._observer)
            predicted.reserve_reply(request_ns, response_ns, now_ns)
            intent = dict(request_ns=request_ns, response_ns=response_ns, transmission_proven=False,
                          network_authorized=False, fusion_qualified=False)
            self._record('reply_intent', intent=intent)
            self._observer = predicted
            self._advance('first_pending' if self._phase == 'first_ready' else 'stream_pending')
            return intent

    def confirm_first(self, raw, exit_code, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            self._require('first_pending')
            parsed = parse_snapshot(raw, exit_code)
            if parsed['kind'] != 'single':
                self._fail('first status missing')
            predicted = copy.deepcopy(self._observer)
            observed = predicted.observe_status(parsed['status'], now_ns)
            if not observed['accepted'] or observed['modeled_accepted_samples'] != 1:
                self._fail('first status did not produce one accepted sample')
            self._record('first_status', raw_hex=raw.hex(), snapshot=parsed, observer=observed)
            self._first = parsed['status']
            self._last_status = copy.deepcopy(parsed['status'])
            self._observer, self._last_observer = predicted, observed
            self._advance('first_confirmed')
            return self.progress

    def begin_stream(self, listener_token, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            self._require('first_confirmed')
            if not _token(listener_token):
                self._fail('invalid listener comparison tag')
            decoder = TimesyncListenerDecoder(0, self._expected, now_ns,
                                             output_profile='px4-d6f12ad-multi-v1')
            self._record('stream_start', listener_token=listener_token, expected_records=self._expected)
            self._listener, self._decoder = listener_token, decoder
            self._advance('replay_pending')
            return self.progress

    def _listener_match(self, listener_token):
        if type(listener_token) is not str or self._listener is None or listener_token != self._listener:
            self._fail('listener comparison tag changed or absent')

    def feed_stream(self, data, listener_token, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            self._listener_match(listener_token)
            if self._phase not in ('replay_pending', 'stream_pending', 'stream_ready', 'finish_pending'):
                self._fail('stream data in wrong phase')
            if type(data) is not bytes or len(data) > self._decoder.MAX_CHUNK:
                self._fail('invalid raw chunk')
            self._record('raw_chunk', listener_token=listener_token, raw_hex=data.hex())
            if data and self._phase in ('stream_ready', 'finish_pending'):
                self._fail('unsolicited bytes without pending reply')
            rows = self._decoder.feed(data, now_ns)
            if rows and self._decoder.incomplete_frame_bytes:
                self._fail('bytes after completed reserved record')
            for row in rows:
                if self._phase == 'replay_pending':
                    if row != self._first:
                        self._fail('initial latest replay differs from first status')
                    self._record('latest_replay', status=row, counts_as_new_sample=False)
                else:
                    self._require('stream_pending')
                    predicted = copy.deepcopy(self._observer)
                    observed = predicted.observe_status(row, now_ns)
                    self._record('stream_status', status=row, observer=observed)
                    self._observer, self._last_observer = predicted, observed
                    self._last_status = copy.deepcopy(row)
                self._seen += 1
                self._advance('finish_pending' if self._seen == self._expected else 'stream_ready')
            return self.progress

    def finish_stream(self, exit_code, listener_token, *, now_ns, epoch_token):
        with self._step(now_ns, epoch_token):
            self._listener_match(listener_token)
            self._require('finish_pending')
            terminal = self._decoder.finish(now_ns, exit_code)
            if self._last_observer is None or not self._last_observer['observed_model_converged']:
                self._fail('fewer than 500 accepted modeled samples')
            self._record('stream_finished', terminal=terminal, observer=self._last_observer)
            self._advance('done')
            return self.progress

    def take_continuation(self, listener_token, deadline_ns, journal, *, now_ns, epoch_token):
        """One-time internal filter handoff; no transport/clock qualification grant."""
        from tools.benchmark.openvins_timesync_maintenance import _TimesyncMaintenance

        with self._step(now_ns, epoch_token, transfer=True):
            self._require('done')
            if (not _token(listener_token) or listener_token == self._listener
                    or type(deadline_ns) is not int or not now_ns < deadline_ns <= self._start + 300_000_000_000
                    or not callable(journal) or self._last_status is None
                    or not self._last_observer['observed_model_converged']):
                self._fail('invalid continuation identity/deadline/journal or unconverged bootstrap')
            self._record('continuation_transfer_attempt', listener_token=listener_token, deadline_ns=deadline_ns)
            # Construction journals before this object gives up the observer.
            # A raised/reentrant journal leaves no usable continuation to return.
            continuation = _TimesyncMaintenance(
                self._observer, self._last_status, self._last_observer, listener_token,
                self._epoch, now_ns, deadline_ns, journal, lambda: self._fault, retention=self._retention)
            if self._fault is not None:
                raise ValueError('bootstrap failure during transfer journal')
            self._record('continuation_transferred', listener_token=listener_token, deadline_ns=deadline_ns)
            self._observer = None
            self._continuation_taken = True
            return continuation
