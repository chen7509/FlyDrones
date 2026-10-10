"""Fresh owned PX4 log/status joint gate; no cold TIMESYNC side effects."""

from __future__ import annotations

import copy
import hashlib
import os
import stat
from pathlib import Path

from tools.benchmark.owned_daemon_connection import LinuxBackend, _error, validate_owner
from tools.benchmark.px4_mavlink_startup_status import parse_mavlink_status
from tools.benchmark.px4_owned_startup_probe import OwnedMavlinkStatusProbe


class StartupPhaseRefusal(ValueError):
    def __init__(self, evidence):
        self.evidence = copy.deepcopy(evidence)
        super().__init__(evidence['error'])


class StartupPhaseGate:
    """Require a fresh PX4-owned log marker and exact owned status reply.

    The caller must create ``log_path`` exclusively before spawning PX4 and
    provide that zero-length file's dev/inode as ``initial_log``. Only the
    caller may construct the cold session after ``transition`` succeeds.
    """

    MAX_LOG = 1_048_576
    MAX_EVENTS = 65_536
    SUCCESS = b'Startup script returned successfully'
    FAILURE = b'Startup script returned with return value:'

    def __init__(self, process, expected, log_path, initial_log, spawn_ns, deadline_ns,
                 journal, source_guard, *, backend=None):
        self._process = process
        self._expected = copy.deepcopy(expected)
        self._path = Path(log_path)
        self._baseline = copy.deepcopy(initial_log)
        self._backend = backend or LinuxBackend()
        self._journal, self._source_guard = journal, source_guard
        self._phase = 'startup'
        self._failure = None
        self._events = []
        self._consumed = b''
        self._pending = b''
        self._lines = 0
        self._marker_line = self._marker_at = None
        self._status = None
        self._evidence = dict(phase='startup', error=None, authority=False,
                              fusion_qualified=False, startup_ready_monotonic_ns=None,
                              log=None, status=None, events=self._events,
                              refusal_journal_error=None)
        try:
            validate_owner(self._expected)
            if type(getattr(process, 'pid', None)) is not int or process.pid != self._expected['pid']:
                raise ValueError('startup owner PID mismatch')
            if (type(initial_log) is not dict or initial_log.keys() != {'device', 'inode', 'size'}
                    or any(type(initial_log[key]) is not int or initial_log[key] < 0
                           for key in ('device', 'inode'))
                    or type(initial_log['size']) is not int or initial_log['size'] != 0):
                raise ValueError('zero-length pre-spawn log identity required')
            if not self._path.is_absolute() or not callable(journal) or not callable(source_guard):
                raise ValueError('absolute log and guards required')
            if (type(spawn_ns) is not int or type(deadline_ns) is not int
                    or not 0 <= spawn_ns < deadline_ns < 2**64
                    or deadline_ns - spawn_ns > 60_000_000_000):
                raise ValueError('finite spawn-anchored startup cap required')
            self._last_clock = spawn_ns
            self._deadline = deadline_ns
            self._check()
            self._record('startup_phase_started', spawn_ns=spawn_ns,
                         deadline_ns=deadline_ns, owner=self._expected,
                         initial_log=self._baseline)
            self._check()
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                raise
            raise StartupPhaseRefusal(self._evidence) from exc

    @property
    def progress(self):
        return dict(phase=self._phase, failure=self._failure,
                    log_ready=self._marker_at is not None, status_ready=self._status is not None,
                    authority=False, fusion_qualified=False)

    @property
    def evidence(self):
        return copy.deepcopy(self._evidence)

    def _record(self, kind, **fields):
        if len(self._events) >= self.MAX_EVENTS:
            raise ValueError('startup journal capacity exceeded')
        row = dict(kind=kind, **fields)
        self._events.append(copy.deepcopy(row))
        if self._journal(copy.deepcopy(row)) is not None:
            raise ValueError('startup journal must return None')

    def _fail(self, exc):
        if self._failure is not None:
            return
        self._failure = _error(exc)
        self._phase = 'failed'
        self._evidence['phase'] = 'failed'
        self._evidence['error'] = self._failure
        row = dict(kind='startup_refusal', error=self._failure)
        if len(self._events) < self.MAX_EVENTS:
            self._events.append(copy.deepcopy(row))
        try:
            if self._journal(copy.deepcopy(row)) is not None:
                raise ValueError('startup refusal journal must return None')
        except BaseException as journal_exc:
            self._evidence['refusal_journal_error'] = _error(journal_exc)

    def _check(self, *, ready=False):
        allowed = ('startup', 'ready') if ready else ('startup',)
        if self._failure is not None or self._phase not in allowed:
            raise ValueError('startup phase failed or already transitioned')
        now = self._backend.clock()
        if type(now) is not int or not self._last_clock <= now < 2**64:
            raise ValueError('startup clock regression')
        self._last_clock = now
        deadline = self._deadline
        if self._phase == 'ready':
            ready_ns = self._evidence['startup_ready_monotonic_ns']
            if type(ready_ns) is not int or ready_ns >= 2**64 - 8_000_000_000:
                raise ValueError('invalid cold transition timestamp')
            deadline = ready_ns + 8_000_000_000
        if now >= deadline:
            raise TimeoutError('startup phase deadline expired')
        owner = self._backend.observe(self._process)
        validate_owner(owner)
        if owner != self._expected:
            raise ValueError('startup owner changed')
        if self._source_guard() is not None:
            raise ValueError('startup source guard must return None')
        return now

    def _read_log(self):
        path_stat = self._path.lstat()
        if not stat.S_ISREG(path_stat.st_mode):
            raise ValueError('startup log is not regular')
        identity = (self._baseline['device'], self._baseline['inode'])
        if (path_stat.st_dev, path_stat.st_ino) != identity:
            raise ValueError('startup log path identity changed')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(self._path, flags), 'rb') as source:
            file_stat = os.fstat(source.fileno())
            if (file_stat.st_dev, file_stat.st_ino) != identity:
                raise ValueError('startup log descriptor identity changed')
            if file_stat.st_size < len(self._consumed) or file_stat.st_size > self.MAX_LOG:
                raise ValueError('startup log truncated or too large')
            raw = source.read(self.MAX_LOG + 1)
        after = self._path.lstat()
        if (after.st_dev, after.st_ino) != identity or len(raw) > self.MAX_LOG:
            raise ValueError('startup log replaced or too large during read')
        if not raw.startswith(self._consumed):
            raise ValueError('startup log prefix changed')
        return raw

    def poll_log(self, *, after_transition=False):
        try:
            if after_transition and self._phase != 'ready':
                raise ValueError('startup post-transition recheck requires ready phase')
            self._check(ready=after_transition)
            raw = self._read_log()
            new = raw[len(self._consumed):]
            self._evidence['log'] = dict(path=str(self._path), device=self._baseline['device'],
                                         inode=self._baseline['inode'], bytes_read=len(raw),
                                         sha256=hashlib.sha256(raw).hexdigest(),
                                         marker_line=self._marker_line,
                                         marker_observed_ns=self._marker_at)
            if new:
                self._consumed = raw
                self._pending += new
                observed_at = self._check(ready=after_transition)
                self._record('startup_log_bytes', at_ns=observed_at, bytes_read=len(raw),
                             sha256=hashlib.sha256(raw).hexdigest(), appended_hex=new.hex())
                self._check(ready=after_transition)
                while b'\n' in self._pending:
                    line, self._pending = self._pending.split(b'\n', 1)
                    self._lines += 1
                    if self.FAILURE in line:
                        raise ValueError('PX4 startup failure marker')
                    if self.SUCCESS in line and self._marker_at is None:
                        self._marker_at = self._check(ready=after_transition)
                        self._marker_line = self._lines
            self._evidence['log']['marker_line'] = self._marker_line
            self._evidence['log']['marker_observed_ns'] = self._marker_at
            self._check(ready=after_transition)
            return self.progress
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                raise
            raise StartupPhaseRefusal(self._evidence) from exc

    def accept_status(self, probe):
        try:
            self._check()
            if (type(probe) is not OwnedMavlinkStatusProbe
                    or probe._expected != self._expected
                    or probe._process.pid != self._expected['pid']):
                raise ValueError('status probe ownership does not match startup')
            evidence = probe.evidence
            if (evidence['transport_complete'] is not True or evidence['error'] is not None
                    or evidence['connection_evidence']['connection_peer_matched'] is not True
                    or evidence['authority'] is not False
                    or evidence['fusion_qualified'] is not False):
                raise ValueError('status probe incomplete or unauthorized')
            parsed = parse_mavlink_status(bytes.fromhex(evidence['raw_stdout_hex']),
                                          evidence['exit_code'])
            if parsed != evidence['parsed']:
                raise ValueError('status parser/probe result mismatch')
            now = self._check()
            self._record('startup_status', at_ns=now, phase=parsed['phase'],
                         raw_stdout_hex=evidence['raw_stdout_hex'],
                         raw_trailer_hex=evidence['raw_trailer_hex'], exit_code=evidence['exit_code'])
            self._check()
            if parsed['phase'] == 'ready':
                self._status = evidence
                self._evidence['status'] = copy.deepcopy(evidence)
            return self.progress
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                raise
            raise StartupPhaseRefusal(self._evidence) from exc

    def transition(self):
        if self._failure is not None:
            raise StartupPhaseRefusal(self._evidence)
        if self._marker_at is None or self._status is None:
            raise StartupPhaseRefusal(dict(error='startup not ready'))
        self.poll_log()  # Recheck identity, appended failures, source and deadline.
        try:
            self._record('startup_ready', intent_ns=self._check(), marker_observed_ns=self._marker_at,
                         status_exit_code=self._status['exit_code'])
            ready_ns = self._check()
            self._phase = 'ready'
            self._evidence['phase'] = 'ready'
            self._evidence['startup_ready_monotonic_ns'] = ready_ns
            return self.evidence
        except BaseException as exc:
            self._fail(exc)
            if not isinstance(exc, Exception):
                raise
            raise StartupPhaseRefusal(self._evidence) from exc
