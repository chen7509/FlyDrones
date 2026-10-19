"""Independent PostUpdate clock evidence, with no transport or live authority.

The caller binds the callback to an owned TestFixture and supplies its guard.
This module does not prove that binding or PX4's consumption of its clock topic.
Journal callbacks require outer supervision; they cannot be preempted here.
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from datetime import timedelta
from threading import Lock, RLock, local

from tools.benchmark.owned_daemon_connection import _error


@dataclass(frozen=True)
class ClockObservation:
    iteration: int
    sim_ns: int
    callback_ns: int
    journal_return_ns: int


@dataclass(frozen=True)
class ClockSelection:
    observation: ClockObservation
    received_ns: int
    selected_ns: int


class JournaledSimulationClock:
    STEP_NS = 1_000_000
    FRESHNESS_NS = 2_000_000_000
    MAX_SAMPLES = 25_000

    def __init__(self, session_id, now, journal, start_ns, guard):
        if (type(session_id) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', session_id) is None
                or not all(callable(f) for f in (now, journal, guard))
                or type(start_ns) is not int or not 0 <= start_ns < 2**64):
            raise ValueError('explicit simulation session/clock/journal/guard required')
        self._session = session_id
        self._now, self._journal, self._guard = now, journal, guard
        self._start = self._last_now = start_ns
        self._state, self._writer = RLock(), Lock()
        self._clock_context = local()
        self._checking = False
        self._latest = self._pending_ns = self._failure = None
        self._observations, self._attempts = [], []

    @property
    def session_id(self):
        return self._session

    @property
    def progress(self):
        with self._state:
            return dict(session_id=self._session, failure=self._failure,
                        latest_callback_ns=None if self._latest is None else self._latest.callback_ns,
                        committed_samples=len(self._observations), pending_callback_ns=self._pending_ns,
                        runtime_source_proven=False, network_authorized=False, fusion_qualified=False)

    @property
    def evidence(self):
        with self._state:
            return dict(session_id=self._session, observations=[asdict(x) for x in self._observations],
                        attempts=copy.deepcopy(self._attempts), failure=self._failure,
                        pending_callback_ns=self._pending_ns, runtime_source_proven=False,
                        px4_clock_consumption_proven=False, network_authorized=False, fusion_qualified=False)

    def _open(self):
        if self._failure is not None:
            raise ValueError('simulation clock failure latched: ' + self._failure)

    def _fail(self, exc):
        with self._state:
            if self._failure is None:
                self._failure = 'simulation clock refusal'
                self._failure = _error(exc)

    def _read_clock(self):
        # Per-thread recursion guard: independent reader/writer threads may
        # sample the same monotonic clock concurrently, but it cannot call back
        # into this lane recursively, including at journal-return observation.
        if getattr(self._clock_context, 'active', False):
            exc = ValueError('reentrant simulation observation clock')
            self._fail(exc)
            raise exc
        self._clock_context.active = True
        try:
            return self._now()
        finally:
            self._clock_context.active = False

    def _clock_locked(self):
        self._open()
        value = self._read_clock()
        self._open()
        if type(value) is not int or not self._last_now <= value < 2**64:
            raise ValueError('invalid or regressed simulation observation wall clock')
        self._last_now = value
        return value

    def _check_locked(self):
        self._open()
        if self._checking:
            self._fail(ValueError('reentrant clock/guard check'))
            self._open()
        self._checking = True
        try:
            self._clock_locked()
            if self._guard() is not None:
                raise ValueError('simulation session guard must return None')
            self._open()
            now = self._clock_locked()
            for origin in (self._latest.callback_ns if self._latest else None, self._pending_ns):
                if origin is not None and now - origin >= self.FRESHNESS_NS:
                    raise ValueError('simulation clock source freshness expired')
            return now
        finally:
            self._checking = False

    def check(self):
        try:
            with self._state:
                self._check_locked()
        except BaseException as exc:
            self._fail(exc)
            raise

    @staticmethod
    def _duration(value):
        if type(value) is not timedelta:
            raise ValueError('exact timedelta required for installed UpdateInfo profile')
        return ((value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds) * 1000

    def post_update(self, info, ecm=None):
        """A single writer; no ECM/pose/sensor data enters this clock lane."""
        if not self._writer.acquire(blocking=False):
            exc = ValueError('concurrent simulation clock writer')
            self._fail(exc)
            raise exc
        attempt = None
        try:
            # Read before waiting for _state: guard/journal/reader contention
            # must not move the callback's observed arrival later.
            callback_ns = self._read_clock()
            with self._state:
                self._open()
                if (type(callback_ns) is not int or not self._start <= callback_ns < 2**64
                        or (self._latest and callback_ns < self._latest.callback_ns)):
                    raise ValueError('invalid callback entry clock')
                self._pending_ns = callback_ns
                now = self._check_locked()
                if callback_ns > now:
                    raise ValueError('callback entry clock is in the future')
                if len(self._observations) >= self.MAX_SAMPLES:
                    raise ValueError('simulation clock sample limit')
                iteration, sim_time, dt, paused = info.iterations, info.sim_time, info.dt, info.paused
                sim_ns, dt_ns = self._duration(sim_time), self._duration(dt)
                if (type(iteration) is not int or iteration != len(self._observations) + 1
                        or type(paused) is not bool or paused
                        or dt_ns != self.STEP_NS or sim_ns != iteration * self.STEP_NS):
                    raise ValueError('simulation profile gap/pause/reset/type mismatch')
                attempt = dict(kind='clock_observation_attempt', session_id=self._session,
                               iteration=iteration, sim_ns=sim_ns, dt_ns=dt_ns,
                               paused=paused, callback_ns=callback_ns)
                self._attempts.append(attempt)
            # Publish only after a successful return. Readers may still obtain
            # the last committed sample while this journal callback is pending.
            result = self._journal(copy.deepcopy(attempt))
            with self._state:
                returned = self._clock_locked()
                attempt['journal_return_ns'] = returned
                if result is not None:
                    raise ValueError('clock journal must return None')
                self._check_locked()
                observation = ClockObservation(iteration, sim_ns, callback_ns, returned)
                self._observations.append(observation)
                self._latest = observation
                attempt['accepted'] = True
                self._pending_ns = None
        except BaseException as exc:
            self._fail(exc)
            with self._state:
                if attempt is not None:
                    attempt['accepted'] = False
                    attempt['error'] = self._failure
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._writer.release()

    def snapshot(self, received_ns):
        """Select current reply-preparation time, not time at packet receipt.

        Selection does not refresh the sample or consume a TIMESYNC identity.
        A caller must recheck this lane before its later side effect.
        """
        try:
            with self._state:
                now = self._check_locked()
                if type(received_ns) is not int or not self._start <= received_ns <= now:
                    raise ValueError('invalid packet receipt clock')
                if now - received_ns >= self.FRESHNESS_NS:
                    raise ValueError('packet receipt freshness expired')
                if self._latest is None:
                    raise ValueError('no committed simulation observation')
                return ClockSelection(self._latest, received_ns, now)
        except BaseException as exc:
            self._fail(exc)
            raise

    def validate_selection(self, selection):
        """Recheck the selected sample, not merely a newer committed sample."""
        try:
            with self._state:
                now = self._check_locked()
                if type(selection) is not ClockSelection or type(selection.observation) is not ClockObservation:
                    raise ValueError('invalid clock selection type')
                sample = selection.observation
                if (type(sample.iteration) is not int or not 1 <= sample.iteration <= len(self._observations)
                        or self._observations[sample.iteration - 1] is not sample):
                    raise ValueError('selected observation belongs to another clock lane')
                if (type(selection.received_ns) is not int or type(selection.selected_ns) is not int
                        or not self._start <= selection.received_ns <= selection.selected_ns <= now
                        or selection.selected_ns < sample.journal_return_ns):
                    raise ValueError('invalid clock selection timestamp ordering')
                if now - sample.callback_ns >= self.FRESHNESS_NS or now - selection.received_ns >= self.FRESHNESS_NS:
                    raise ValueError('selected clock or packet freshness expired')
        except BaseException as exc:
            self._fail(exc)
            raise
