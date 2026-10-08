"""Compose real wire codec and owned listener checks; no UDP/PX4 authority."""

from __future__ import annotations

import copy
from threading import Lock, RLock

from tools.benchmark.openvins_owned_bootstrap import OwnedBootstrap
from tools.benchmark.openvins_timesync_wire import TimesyncWireResponder
from tools.benchmark.owned_daemon_connection import LinuxBackend, _error


class OwnedWireBootstrap:
    def __init__(self, process, expected, path, remote_clock, start_ns, journal, send_sink, *, backend=None,
                 heartbeat_sink=None):
        if not callable(journal) or not callable(send_sink) or heartbeat_sink is not None and not callable(heartbeat_sink):
            raise ValueError("explicit journal and sink required")
        self._journal, self._sink = journal, send_sink
        self._backend = backend or LinuxBackend()
        self._lock = Lock()
        self._state_lock = RLock()
        self._failure = None
        self._cleanup_errors = []
        self._complete = self._closed = False
        self._replies = 0
        self._owned = self._wire = None
        try:
            self._owned = OwnedBootstrap(process, expected, path, remote_clock.session_id, start_ns,
                                         lambda event: self._record("owned", event), backend=self._backend)
            self._wire = TimesyncWireResponder(remote_clock, self._owned.reserve_reply, self._send,
                                              lambda event: self._record("wire", event), self._backend.clock, start_ns,
                                              heartbeat_sink=heartbeat_sink)
        except BaseException as exc:
            self._abort(exc)
            raise

    def _record(self, source, event):
        return self._journal(dict(source=source, event=copy.deepcopy(event)))

    @property
    def progress(self):
        value = {} if self._owned is None else self._owned.progress
        wire_failure = None if self._wire is None else self._wire.progress["failure"]
        failure = self._failure or value.get("failure") or wire_failure
        complete = self._complete and failure is None
        value.update(failure=failure, wire_bootstrap_complete=complete,
                     transport_bootstrap_complete=complete, modeled_bootstrap_ready=complete,
                     completed_reply_attempts=self._replies, network_authorized=False,
                     delivery_proven=False, live_convergence_qualified=False, fusion_qualified=False)
        return value

    @property
    def evidence(self):
        return dict(self.progress, owned=None if self._owned is None else self._owned.evidence,
                    wire=None if self._wire is None else self._wire.evidence,
                    cleanup_errors=copy.deepcopy(self._cleanup_errors))

    def _open(self):
        if self._failure is not None:
            raise ValueError("wire bootstrap failure latched: " + self._failure)
        if self._closed or self._complete:
            raise ValueError("wire bootstrap already completed or closed")

    def _healthy(self):
        self._open()
        self._wire.check()
        self._owned.check(allow_completed=True)

    def _send(self, raw, peer):
        # Do not call wire.check while inside wire.receive's operation lock.
        self._open()
        self._owned.check()
        self._open()
        return self._sink(raw, peer)

    def _abort(self, error):
        with self._state_lock:
            if self._failure is None:
                self._failure = "wire bootstrap refusal (formatting error)"
                self._failure = _error(error)
        if self._owned is not None:
            try:
                self._owned.close()
            except BaseException as exc:
                self._cleanup_errors.append(_error(exc))

    def _operation(self, action, commit):
        self._open()
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError("concurrent wire bootstrap operation"))
            raise ValueError("concurrent wire bootstrap operation")
        try:
            self._healthy()
            result = action()
            self._healthy()
            # Close/refusal and commit share a state lock. No callback runs
            # between the last open check and these local state assignments.
            with self._state_lock:
                self._open()
                commit(result)
            return result
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._lock.release()

    def receive(self, raw, peer, received_ns, observed_sim_ns):
        def commit(result):
            if result is not None:
                self._replies += 1
        return self._operation(lambda: self._wire.receive(raw, peer, received_ns, observed_sim_ns), commit)

    def poll(self):
        def commit(result):
            if result["transport_bootstrap_complete"] and (
                result["modeled_accepted_samples"] != 500 or self._replies != 500
            ):
                raise ValueError("composed status/reply count mismatch")
            if result["transport_bootstrap_complete"]:
                self._complete = True
        self._operation(self._owned.poll, commit)
        return self.progress

    def close(self):
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            if not self._complete:
                self._abort(ValueError("wire bootstrap closed before completion"))
