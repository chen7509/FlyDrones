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
        self._bootstrap = ColdTimesyncBootstrap(
            session_id, self._epoch, start_ns, lambda event: self._record("bootstrap", event), stream_records=stream_records
        )
        self._clock()

    @property
    def progress(self):
        result = self._bootstrap.progress
        complete = self._done and self._fault is None
        result.update(
            failure=self._fault or result["failure"], transport_bootstrap_complete=complete, modeled_bootstrap_ready=complete
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
        if now >= self._deadline:
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
        if self._bootstrap.progress["phase"] != "done":
            self._bootstrap.check(now_ns=now, epoch_token=self._epoch)
        return now

    def _record(self, source, event, command_index=None):
        if self._regular_events >= self.MAX_EVENTS:
            raise ValueError("owned bootstrap event limit")
        envelope = dict(source=source, command_index=command_index, event=copy.deepcopy(event), at_ns=self._clock())
        self._regular_events += 1
        self._events.append(copy.deepcopy(envelope))
        if self._journal(copy.deepcopy(envelope)) is not None:
            raise ValueError("owned bootstrap journal must return None")
        self._clock()

    def _abort(self, error):
        first = self._fault is None
        if first:
            self._fault = _error(error)
        if self._current is not None:
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
        if self._done and not allow_completed:
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
            result = self._bootstrap.reserve_reply(request_ns, response_ns, now_ns=self._check(), epoch_token=self._epoch)
        return result

    def check(self, *, allow_completed=False):
        """Check existing ownership/deadlines without opening or reading a command."""
        with self._step(allow_completed=allow_completed):
            pass
        return self.progress

    def _open(self, role):
        index = len(self._transports)
        if index >= 3 or role != ("empty", "first", "stream")[index]:
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
                "stream" if role == "stream" else "snapshot",
                self._count if role == "stream" else 1,
                self._start,
                self._deadline,
                lambda event: self._record("transport", event, index),
                backend=self._backend,
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
                if role is not None:
                    self._open(role)
            if self._current is not None:
                output = self._current.poll()
                now = self._check()
                if self._role == "stream" and output["stdout"]:
                    self._bootstrap.feed_stream(output["stdout"], self._listener_token, now_ns=now, epoch_token=self._epoch)
                    if output["records"]:
                        self._stream_frame_ns = now
                if output["terminal"] is not None:
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
        if not self._done and self._fault is None:
            self._abort(ValueError("owned bootstrap aborted before completion"))
