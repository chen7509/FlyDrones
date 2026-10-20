"""Opt-in shared wire retention; ordinary local files, no fsync/hostile-ABA claim.

One lifecycle writer owns the store. Only sealed members have verified hashes;
active/failed members and unpersisted terminal records are explicitly separate.
This is storage evidence, never authority to transmit, fuse or fly.
"""
from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from tools.benchmark.owned_daemon_connection import _error


class SegmentedWireJournal:
    PROFILE = 'capture-wire-segmented-v1'
    EVENTS_PER_SEGMENT = 8192
    MAX_SEGMENTS = 64
    MAX_BYTES = 512 * 1024 * 1024
    CHANNELS = frozenset({'wire', 'receiver', 'owned', 'cold', 'maintenance', 'selection',
                          'listener-0', 'listener-1', 'listener-2', 'listener-3'})

    def __init__(self, directory):
        self._directory = Path(directory).absolute()
        self._directory.mkdir(parents=False, exist_ok=False)
        self._lock = RLock()
        self._busy = self._closed = False
        self._failure = None
        self._phase = 'bootstrap'
        self._records = self._bytes = 0
        self._counts = {}
        self._segments, self._unsealed = [], []
        self._file = self._active = self._digest = None
        self._invalid_active = False
        self._failed_record = None
        self._unpersisted_failures = {}

    @property
    def failure(self):
        return self._failure

    def _fail(self, reason):
        if self._failure is None:
            self._failure = reason

    def _require_open(self):
        if self._closed:
            raise ValueError('segmented journal closed')
        if self._failure is not None:
            raise ValueError('segmented journal failed: ' + self._failure)

    @contextmanager
    def _operation(self):
        if not self._lock.acquire(blocking=False):
            self._fail('concurrent segmented journal operation')
            raise ValueError(self._failure)
        try:
            if self._busy:
                self._fail('reentrant segmented journal operation')
                raise ValueError(self._failure)
            self._busy = True
            try:
                self._require_open()
                yield
            except BaseException as exc:
                if not self._closed:
                    self._fail(_error(exc))
                raise
            finally:
                self._busy = False
        finally:
            self._lock.release()

    def channel(self, name):
        with self._operation():
            if type(name) is not str or name not in self.CHANNELS or name in self._counts:
                raise ValueError('unique declared lifecycle channel required')
            self._counts[name] = 0
            return SegmentedEvents(self, name)

    def phase(self, name):
        with self._lock:
            phases = ('bootstrap', 'maintenance', 'stopping')
            if name not in phases or phases.index(name) < phases.index(self._phase) or self._closed:
                self._fail('invalid/regressed retention phase')
                raise ValueError(self._failure)
            self._phase = name  # No I/O/callback; cleanup may mark a failed store.

    def require_capacity(self, count=1):
        with self._lock:
            self._require_open()
            if type(count) is not int or count < 1 or self._records + count > self.MAX_SEGMENTS * self.EVENTS_PER_SEGMENT:
                self._fail('segmented event capacity exhausted')
                raise ValueError(self._failure)
            if self._bytes >= self.MAX_BYTES:
                self._fail('segmented byte capacity exhausted')
                raise ValueError(self._failure)

    @staticmethod
    def _encode(value):
        return (json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')

    def _append(self, source, event):
        with self._operation():
            self.require_capacity()
            if type(event) is not dict:
                raise ValueError('journal event must be a dictionary')
            row = dict(index=self._records, source=source, source_index=self._counts[source],
                       phase=self._phase, event=copy.deepcopy(event))
            raw = self._encode(row)
            self._failed_record = row  # One bounded in-flight record also covers byte rejection.
            if self._bytes + len(raw) > self.MAX_BYTES:
                raise ValueError('segmented byte capacity exhausted before write')
            if self._file is None:
                number = len(self._segments) + len(self._unsealed)
                if number >= self.MAX_SEGMENTS:
                    raise ValueError('segmented member capacity exhausted')
                name = f'segment-{number:04d}.jsonl'
                self._file = (self._directory / name).open('xb')
                self._active = dict(name=name, first_index=self._records, last_index=None, records=0, bytes=0)
                self._digest = hashlib.sha256()
                self._invalid_active = False
            try:
                written = self._file.write(raw)
                if type(written) is not int or written != len(raw):
                    raise ValueError('segmented short write')
            except BaseException:
                self._invalid_active = True
                raise
            self._digest.update(raw)
            self._active.update(last_index=self._records, records=self._active['records'] + 1,
                                bytes=self._active['bytes'] + len(raw))
            self._records += 1
            self._bytes += len(raw)
            self._counts[source] += 1
            self._failed_record = None
            self._require_open()  # Catch refusal from a reentrant writer hook.
            if self._active['records'] == self.EVENTS_PER_SEGMENT:
                self._seal()
                self._require_open()

    def _seal(self):
        if self._file is None:
            return
        writer, self._file = self._file, None
        member = dict(self._active, sha256=self._digest.hexdigest())
        errors, interrupted = [], None
        for operation in (writer.flush, writer.close):
            try:
                operation()
            except BaseException as exc:
                errors.append(_error(exc))
                if not isinstance(exc, Exception) and interrupted is None:
                    interrupted = exc
        try:
            digest, length = hashlib.sha256(), 0
            with (self._directory / member['name']).open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
                    length += len(chunk)
            if length != member['bytes'] or digest.hexdigest() != member['sha256']:
                raise ValueError('segmented closed member hash/length mismatch')
        except BaseException as exc:
            errors.append(_error(exc))
            if not isinstance(exc, Exception) and interrupted is None:
                interrupted = exc
        if self._invalid_active:
            errors.append('member contains failed or partial write')
        if errors:
            self._unsealed.append(dict(member, errors=errors))
            self._fail(errors[0])
        else:
            self._segments.append(member)
        self._active = self._digest = None
        if interrupted is not None:
            raise interrupted

    @property
    def evidence(self):
        with self._lock:
            active = None if self._active is None else dict(self._active, expected_sha256=self._digest.hexdigest(),
                                                          sealed=False, hash_verified=False)
            return copy.deepcopy(dict(
                profile=self.PROFILE, directory=str(self._directory), phase=self._phase,
                limits=dict(segments=self.MAX_SEGMENTS, events_per_segment=self.EVENTS_PER_SEGMENT, bytes=self.MAX_BYTES),
                closed=self._closed, failure=self._failure, records=self._records, bytes=self._bytes,
                channels=self._counts, segments=self._segments, active=active, unsealed=self._unsealed,
                failed_record=self._failed_record, unpersisted_failures=self._unpersisted_failures,
                complete_retention=(self._closed and not self._busy and self._failure is None
                                    and not self._unpersisted_failures),
                fsync_proven=False, network_authorized=False, fusion_qualified=False))

    def close(self):
        with self._lock:
            if self._busy:
                self._fail('close during segmented journal operation')
                raise ValueError(self._failure)
            if self._closed:
                return self.evidence
            self._busy = True
            interruption = None
            try:
                try:
                    self._seal()
                except BaseException as exc:
                    self._fail(_error(exc))
                    if not isinstance(exc, Exception):
                        interruption = exc
                self._closed = True
                try:
                    # This file is a member index, not proof of its own future
                    # successful close. Only the returned final evidence can
                    # report completed retention after all close calls returned.
                    raw = self._encode(dict(self.evidence, manifest_scope='member_index_not_completion_grant'))
                    with (self._directory / 'manifest.json').open('xb') as target:
                        if target.write(raw) != len(raw):
                            raise ValueError('manifest short write')
                        target.flush()
                except BaseException as exc:
                    self._fail(_error(exc))
                    if not isinstance(exc, Exception) and interruption is None:
                        interruption = exc
            finally:
                self._busy = False
            if interruption is not None:
                raise interruption
            return self.evidence


class SegmentedEvents:
    """A reference, not a history list. Shared quota applies to every channel."""
    def __init__(self, store, name):
        self.store, self.name = store, name

    def __len__(self):
        return self.store._counts[self.name]

    def append(self, event):
        self.store._append(self.name, event)

    def record_failure(self, event):
        try:
            self.append(event)
        except BaseException:
            # One bounded terminal slot per declared channel, never a hidden
            # extra segment or success after a storage failure.
            if self.name not in self.store._unpersisted_failures:
                self.store._unpersisted_failures[self.name] = copy.deepcopy(event)

    def __deepcopy__(self, memo):
        return dict(profile=self.store.PROFILE, channel=self.name, records=len(self), journal=self.store.evidence)


def event_log(retention, name):
    if retention is None:
        return []
    if type(retention) is not SegmentedWireJournal:
        raise ValueError('explicit segmented lifecycle store required')
    return retention.channel(name)


def require_capacity(events, used, maximum, count=1):
    if isinstance(events, SegmentedEvents):
        events.store.require_capacity(count)
    elif used + count > maximum:
        raise ValueError('journal event limit/capacity')


def record_failure(events, event):
    if isinstance(events, SegmentedEvents):
        events.record_failure(event)
    else:
        events.append(event)
