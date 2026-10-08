"""Offline TIMESYNC rate-transaction model for pinned PX4 d6f12ad.

No wire adapter is supplied. Callers must bound I/O and independently establish
freshness, channel identity and exclusive ownership. Events are in memory only;
successful readback is not proof of actual transmission/accepted filter rate.
"""

from __future__ import annotations

import copy
import struct
from collections.abc import Callable
from threading import Lock
from typing import Protocol


def _f32(value: int | float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def restorable_interval(value: int) -> int:
    """Accept only positive int32 intervals surviving wire and PX4 conversions."""
    if type(value) is not int or not 0 < value < 2**31:
        raise ValueError("ambiguous or invalid interval")
    wire = _f32(value)
    if wire != value:
        raise ValueError("interval loses wire precision")
    rate = _f32(1_000_000.0 / wire)
    restored = _f32(1_000_000.0 / rate)
    if not 0 < restored < 2**31 or int(restored) != value:
        raise ValueError("interval does not roundtrip pinned PX4")
    return value


class IntervalTransport(Protocol):
    """Future bounded/correlated adapter contract, not an implemented transport."""

    def read_interval(self, message_id: int) -> list[dict]: ...
    def set_interval(self, message_id: int, interval_us: int) -> bool: ...


class TimesyncIntervalTransaction:
    """One apply/body/restore attempt. Live authority always remains false.

    A callable body must return literal True after its own modeled checks. The
    helper cannot interrupt blocking transport/body calls or survive process
    death. A future live harness must supply those guarantees outside this class.
    """

    MESSAGE_ID = 111
    CANDIDATE_US = 10000

    def __init__(self, transport: IntervalTransport):
        self._transport = transport
        self._used = False
        self._lock = Lock()
        self.last_result: dict | None = None

    def _read(self) -> int:
        rows = self._transport.read_interval(self.MESSAGE_ID)
        if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            raise ValueError("interval response count or shape")
        row = rows[0]
        if set(row) != {"message_id", "interval_us"}:
            raise ValueError("interval response keys")
        if type(row["message_id"]) is not int or row["message_id"] != self.MESSAGE_ID:
            raise ValueError("interval response message identity")
        return restorable_interval(row["interval_us"])

    def run(self, body: Callable[[], bool]) -> dict:
        with self._lock:
            if self._used:
                raise ValueError("single-use interval transaction")
            self._used = True
        result = {
            "baseline_us": None, "candidate_us": self.CANDIDATE_US,
            "final_us": None, "mutation_attempted": False,
            "restore_attempted": False, "primary_failure": None,
            "restore_failures": [], "events": [],
            "modeled_transaction_pass": False, "network_authorized": False,
            "live_rate_qualified": False, "fusion_qualified": False,
        }
        interruption: BaseException | None = None

        def failure(phase: str, exc: BaseException, *, restore: bool = False):
            nonlocal interruption
            # Diagnostics must not call untrusted exception formatting outside
            # a guard: __str__ may itself raise and otherwise skip restoration.
            try:
                message = str(exc)
            except BaseException:
                message = "<unprintable exception>"
            detail = f"{phase}:{type(exc).__name__}:{message}"
            if restore:
                result["restore_failures"].append(detail)
            else:
                result["primary_failure"] = detail
            result["events"].append({"phase": phase, "error": detail})
            if not isinstance(exc, Exception) and interruption is None:
                interruption = exc

        phase = "baseline"
        try:
            if not callable(body):
                raise ValueError("body must be callable")
            candidate = restorable_interval(self.CANDIDATE_US)
            baseline = self._read()
            result["baseline_us"] = baseline
            result["events"].append({"phase": phase, "interval_us": baseline})
            if baseline != candidate:
                phase = "apply"
                # A throwing/lost ACK can still follow a committed remote write.
                result["mutation_attempted"] = True
                result["events"].append({"phase": phase, "attempt_us": candidate})
                if self._transport.set_interval(self.MESSAGE_ID, candidate) is not True:
                    raise ValueError("accepted ACK missing")
                phase = "apply_readback"
                observed = self._read()
                result["events"].append({"phase": phase, "interval_us": observed})
                if observed != candidate:
                    raise ValueError("candidate readback mismatch")
            phase = "body"
            if body() is not True:
                raise ValueError("body did not pass")
            result["events"].append({"phase": phase, "passed": True})
        except BaseException as exc:
            failure(phase, exc)

        baseline = result["baseline_us"]
        if result["mutation_attempted"]:
            result["restore_attempted"] = True
            try:
                result["events"].append({"phase": "restore", "attempt_us": baseline})
                if self._transport.set_interval(self.MESSAGE_ID, baseline) is not True:
                    raise ValueError("accepted ACK missing")
            except BaseException as exc:
                failure("restore", exc, restore=True)
            # Independent evidence, including after write/ACK exceptions.
            try:
                observed = self._read()
                result["events"].append({"phase": "restore_readback", "interval_us": observed})
                if observed != baseline:
                    raise ValueError("baseline readback mismatch")
            except BaseException as exc:
                failure("restore_readback", exc, restore=True)
        if baseline is not None:
            try:
                result["final_us"] = self._read()
                result["events"].append({"phase": "final", "interval_us": result["final_us"]})
                if result["final_us"] != baseline:
                    raise ValueError("final baseline mismatch")
            except BaseException as exc:
                failure("final", exc, restore=True)
        result["modeled_transaction_pass"] = (
            result["primary_failure"] is None and not result["restore_failures"]
        )
        self.last_result = result
        if interruption is not None:
            raise interruption
        return result


class IntervalExchange:
    """Bounded nonblocking phases for a caller-owned, single receive loop.

    send_command(operation, value) must verify its own actual byte-count and
    return None; it may not receive recursively. guard(stopping) must verify
    unchanged owner/descriptor/peer and unarmed state, returning None. This
    helper cannot interrupt callbacks or supply those transport guarantees.
    feed accepts only normalized codec replies with original receive time.
    The owner must keep servicing heartbeats and forbid ordinary work on stop.
    No nonce/authentication, actual runtime integration or live grant is implied.
    """

    def __init__(self, send_command, guard, now, start_ns):
        if any(not callable(c) for c in (send_command, guard, now)):
            raise ValueError('explicit exchange callbacks required')
        if type(start_ns) is not int or not 0 <= start_ns < 2**64 - 310_000_000_000:
            raise ValueError('invalid exchange start')
        self._send, self._guard, self._now = send_command, guard, now
        self._last = start_ns
        self._deadline = start_ns + 8_000_000_000
        self._cleanup = None
        self._phase = 'baseline'
        self._pending = None
        self._lock = Lock()
        self._result = dict(baseline_us=None, candidate_us=10000, final_us=None,
                            mutation_attempted=False, restore_attempted=False,
                            primary_failure=None, restore_failures=[], terminal_failure=None,
                            terminal_pending=None, events=[],
                            modeled_transaction_pass=False, network_authorized=False,
                            live_rate_qualified=False, fusion_qualified=False)

    @property
    def evidence(self):
        return copy.deepcopy(dict(self._result, phase=self._phase, pending=self._pending,
                                  cleanup_deadline_ns=self._cleanup))

    @staticmethod
    def _error(exc):
        try:
            return f'{type(exc).__name__}:{exc}'
        except BaseException:
            return '<unprintable exchange failure>'

    def _event(self, kind, **values):
        # The single transaction has at most six effects, not an unbounded log.
        if len(self._result['events']) >= 96:
            self._phase = 'done'
            self._result['modeled_transaction_pass'] = False
            raise ValueError('exchange event capacity')
        self._result['events'].append(dict(kind=kind, phase=self._phase, at_ns=self._last, **values))

    def _time(self):
        value = self._now()
        if type(value) is not int or not self._last <= value < 2**64:
            raise ValueError('exchange clock regression/type')
        self._last = value
        return value

    def _terminal(self, reason):
        if self._result['terminal_failure'] is not None:
            return
        self._result['terminal_failure'] = reason
        self._result['terminal_pending'] = copy.deepcopy(self._pending)
        if self._result['primary_failure'] is None:
            self._result['primary_failure'] = reason
        else:
            self._result['restore_failures'].append(reason)
        self._pending = None
        self._phase = 'done'
        self._result['modeled_transaction_pass'] = False

    def _enter_stop(self):
        if self._cleanup is None:
            self._cleanup = self._last + 10_000_000_000

    def _fail(self, reason):
        phase = self._phase
        self._event('failure', reason=reason, pending=copy.deepcopy(self._pending))
        self._enter_stop()
        self._pending = None
        if phase in ('restore', 'restore_readback', 'final'):
            self._result['restore_failures'].append(reason)
            self._phase = {'restore': 'restore_readback', 'restore_readback': 'final', 'final': 'done'}[phase]
        else:
            if self._result['primary_failure'] is None:
                self._result['primary_failure'] = reason
            self._phase = ('restore' if self._result['mutation_attempted'] else
                           'final' if self._result['baseline_us'] is not None else 'done')

    def _check_deadline(self):
        if self._cleanup is not None and self._last >= self._cleanup:
            self._terminal('cleanup deadline')
            return False
        if self._cleanup is None and self._last >= self._deadline:
            self._fail('startup deadline')
            return False
        if self._pending and self._last >= self._pending['deadline_ns']:
            self._fail('operation timeout')
            return False
        return True

    def _run(self, callback, *, terminal_input=False):
        if not self._lock.acquire(blocking=False):
            self._terminal('concurrent or reentrant exchange call')
            raise ValueError('concurrent or reentrant exchange call')
        try:
            if self._phase == 'done':
                if terminal_input:
                    self._terminal('unexpected input after terminal exchange')
                return
            try:
                self._time()
                if self._guard(self._cleanup is not None) is not None:
                    raise ValueError('identity/safety guard must return None')
                self._time()
            except BaseException as exc:
                self._terminal(self._error(exc))
                if not isinstance(exc, Exception):
                    raise
                return
            if self._phase == 'done':
                return  # A reentrant callback may have already latched failure.
            callback()
        finally:
            self._lock.release()

    def stop(self, reason):
        """Latch primary failure; repeated STOPPING cannot renew or retry."""
        def action():
            if self._cleanup is not None:
                return
            self._enter_stop()
            self._result['primary_failure'] = str(reason) if type(reason) is str else 'external stop'
            self._event('stop', reason=self._result['primary_failure'], pending=copy.deepcopy(self._pending))
            if self._phase not in ('restore', 'restore_readback', 'final'):
                self._pending = None
                self._phase = ('restore' if self._result['mutation_attempted'] else
                               'final' if self._result['baseline_us'] is not None else 'done')
        self._run(action)

    def poll(self):
        """Advance at most one command effect; never receive or run body here."""
        def action():
            if not self._check_deadline() or self._phase == 'body':
                return
            if self._pending:
                p = self._pending
                if p['ack'] is None or (p['command'] == 510 and p['interval_us'] is None):
                    return
                value = p['interval_us']
                self._pending = None
                phase = self._phase
                if phase == 'baseline':
                    self._result['baseline_us'] = value
                    self._phase = 'body' if value == 10000 else 'apply'
                elif phase == 'apply':
                    self._phase = 'apply_readback'
                elif phase == 'apply_readback':
                    if value != 10000:
                        self._fail('candidate readback mismatch')
                        return
                    self._phase = 'body'
                elif phase == 'restore':
                    self._phase = 'restore_readback'
                else:
                    if phase == 'final':
                        self._result['final_us'] = value
                    if value != self._result['baseline_us']:
                        self._fail('baseline readback mismatch')
                        return
                    self._phase = 'final' if phase == 'restore_readback' else 'done'
                    if self._phase == 'done':
                        self._result['modeled_transaction_pass'] = (
                            self._result['primary_failure'] is None and not self._result['restore_failures'])
                return
            operation = 'set' if self._phase in ('apply', 'restore') else 'get'
            value = (10000 if self._phase == 'apply' else self._result['baseline_us']) if operation == 'set' else None
            try:
                if self._guard(self._cleanup is not None) is not None:
                    raise ValueError('identity/safety guard must return None')
                self._time()
            except BaseException as exc:
                self._terminal('guard:' + self._error(exc))
                if not isinstance(exc, Exception):
                    raise
                return
            if self._phase == 'done' or not self._check_deadline():
                return
            limit = self._cleanup if self._cleanup is not None else self._deadline
            self._pending = dict(command=511 if operation == 'set' else 510, sent_ns=self._last,
                                 deadline_ns=min(limit, self._last + 2_000_000_000), ack=None, interval_us=None)
            if self._phase == 'apply':
                self._result['mutation_attempted'] = True
            if self._phase == 'restore':
                self._result['restore_attempted'] = True
            self._event('send_attempt', operation=operation, value=value)
            try:
                returned = self._send(operation, value)
                self._event('send_return', return_is_none=returned is None)
                if returned is not None:
                    raise ValueError('send callback must return None after checking bytes')
            except BaseException as exc:
                if self._phase != 'done':
                    self._fail('send:' + self._error(exc))
                if not isinstance(exc, Exception):
                    raise
                return
            try:
                self._time()
            except BaseException as exc:
                self._terminal(self._error(exc))
                if not isinstance(exc, Exception):
                    raise
                return
            if self._phase != 'done':
                self._check_deadline()
        self._run(action)

    def feed(self, row, received_ns):
        def action():
            if not self._check_deadline():
                return
            p = self._pending
            try:
                if (p is None or type(received_ns) is not int
                        or not p['sent_ns'] <= received_ns <= self._last
                        or received_ns >= p['deadline_ns']):
                    raise ValueError('unsolicited/stale/future response')
                if type(row) is not dict:
                    raise ValueError('response schema')
                if row.get('kind') == 'ack':
                    if (set(row) != {'kind', 'command', 'result'} or type(row['command']) is not int
                            or type(row['result']) is not int or row['command'] != p['command']):
                        raise ValueError('ACK command/schema mismatch')
                    if p['ack'] is not None:
                        raise ValueError('duplicate ACK')
                    p['ack'] = row['result']
                    if row['result'] != 0:
                        raise ValueError('command not accepted')
                elif row.get('kind') == 'interval':
                    if (set(row) != {'kind', 'message_id', 'interval_us'} or p['command'] != 510
                            or type(row['message_id']) is not int or row['message_id'] != 111):
                        raise ValueError('interval identity/schema mismatch')
                    if p['interval_us'] is not None:
                        raise ValueError('duplicate interval')
                    p['interval_us'] = restorable_interval(row['interval_us'])
                else:
                    raise ValueError('unexpected response kind')
                self._event('response', received_ns=received_ns, row=copy.deepcopy(row))
            except ValueError as exc:
                self._fail(self._error(exc))
        self._run(action, terminal_input=True)

    def body_complete(self, passed):
        def action():
            if not self._check_deadline():
                return
            if self._phase != 'body' or passed is not True:
                self._fail('body completion refused')
                return
            self._event('body_completed')
            self._phase = 'restore' if self._result['mutation_attempted'] else 'final'
        self._run(action, terminal_input=True)
