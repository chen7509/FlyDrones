"""Opt-in, fail-closed byte journal for the ROS EGO benchmark bridge.

It records what this bridge passes to publish_raw and receives from its raw
subscription. The socket observation's PX4/camera source is still unattested.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path

MAX_NS = 2**63 - 1
TOPIC = {
    "clock": "/clock",
    "odometry": "/benchmark/ego/odom",
    "trigger": "/traj_start_trigger",
    "camera_pose": "/benchmark/ego/camera_pose",
    "depth": "/benchmark/ego/depth",
    "position_command": "/benchmark/ego/position_cmd",
}


def _natural(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_NS:
        raise ValueError(f"invalid {label}")
    return value


def _payload(value: object) -> bytes:
    if type(value) is not bytes or not value:
        raise ValueError("expected nonempty ROS serialized bytes")
    return value


class BridgeCDRJournal:
    """Serialized bridge actions; publication return is not DDS consumption."""

    def __init__(self, stream, *, run_id: str, session_id: str, serializer,
                 pid: int | None = None, clock=None):
        if (type(run_id) is not str or not run_id or type(session_id) is not str
                or not session_id or not callable(serializer)):
            raise ValueError("run, session and serializer required")
        self.stream = stream
        self.run_id = run_id
        self.session_id = session_id
        self.serializer = serializer
        self.pid = os.getpid() if pid is None else _natural(pid, "pid")
        if self.pid == 0:
            raise ValueError("invalid pid")
        self.clock = time.monotonic_ns if clock is None else clock
        self.lock = threading.Lock()
        self.failed = False
        self.closed = False
        self.reset_started = False
        self.sequence = 0
        self.message_sequence = 0
        self.last_clock_ns = -1
        self.pending_command = None
        with self.lock:
            self._append("session_open")

    @classmethod
    def open_new(cls, path: Path, *, run_id: str, session_id: str, serializer):
        """Open exclusively; a previous or partial journal is never replaced."""
        stream = Path(path).open("x", encoding="utf-8", newline="\n")
        try:
            return cls(stream, run_id=run_id, session_id=session_id,
                       serializer=serializer)
        except BaseException:
            stream.close()
            raise

    def _healthy(self) -> None:
        if self.failed or self.closed:
            raise RuntimeError("bridge journal failed or closed")

    def require_healthy(self) -> None:
        with self.lock:
            self._healthy()

    def _append(self, phase: str, *, kind: str | None = None,
                message_sequence: int | None = None, sample_ns: int | None = None,
                payload: bytes | None = None, extra: dict | None = None) -> None:
        try:
            now = _natural(self.clock(), "steady clock")
            if now < self.last_clock_ns:
                raise ValueError("steady clock regressed")
            record = {
                "schema": "flydrones-ego-bridge-cdr-v1",
                "run_id": self.run_id,
                "session": self.session_id,
                "pid": self.pid,
                "sequence": self.sequence + 1,
                "message_sequence": message_sequence,
                "phase": phase,
                "kind": kind,
                "topic": TOPIC[kind] if kind is not None else None,
                "sample_ns": sample_ns,
                "event_steady_ns": now,
                "message_sha256": hashlib.sha256(payload).hexdigest() if payload else None,
                "message_bytes": len(payload) if payload else None,
                "message_cdr_b64": (base64.b64encode(payload).decode("ascii")
                                    if payload and phase in ("publish_intent",
                                                             "command_received") else None),
                "source": "unattested_ego_server" if kind == "position_command"
                          else "unattested_socket" if kind else None,
                "source_profile_sha256": None,
                "truth_used": "unknown",
            }
            if extra:
                record.update(extra)
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            if self.stream.write(line) != len(line):
                raise OSError("short bridge journal write")
            self.stream.flush()
            self.sequence += 1
            self.last_clock_ns = now
        except BaseException:
            self.failed = True
            raise

    def _mark_failed(self, reason: str, *, kind: str | None = None,
                     message_sequence: int | None = None,
                     sample_ns: int | None = None, payload: bytes | None = None) -> None:
        try:
            if not self.failed:
                self._append("failure", kind=kind, message_sequence=message_sequence,
                             sample_ns=sample_ns, payload=payload,
                             extra={"reason": reason})
        except Exception:
            pass
        self.failed = True

    def fail(self, reason: str) -> None:
        with self.lock:
            self._mark_failed(reason)

    def start_reset(self, seed: int) -> None:
        with self.lock:
            self._healthy()
            try:
                _natural(seed, "reset seed")
                if self.reset_started:
                    raise ValueError("second reset in bridge journal session")
                self._append("reset", extra={"seed": seed})
                self.reset_started = True
            except Exception:
                self._mark_failed("reset_failed")
                raise

    def publish(self, kind: str, message, sample_ns: int, publisher) -> None:
        with self.lock:
            self._healthy()
            if not self.reset_started:
                self._mark_failed("publish_before_reset")
                raise ValueError("publish before bridge reset")
            try:
                if kind not in TOPIC or kind == "position_command":
                    raise ValueError("invalid bridge publication kind")
                sample_ns = _natural(sample_ns, "sample time")
                raw = _payload(self.serializer(message))
                self.message_sequence += 1
                message_sequence = self.message_sequence
                self._append("publish_intent", kind=kind,
                             message_sequence=message_sequence, sample_ns=sample_ns,
                             payload=raw)
            except Exception:
                self._mark_failed("serialization_or_intent_failed")
                raise
            try:
                publisher(raw)
            except Exception:
                try:
                    self._append("publish_failed", kind=kind,
                                 message_sequence=message_sequence, sample_ns=sample_ns,
                                 payload=raw)
                finally:
                    self.failed = True
                raise
            self._append("publish_returned", kind=kind,
                         message_sequence=message_sequence, sample_ns=sample_ns,
                         payload=raw)

    def receive_command(self, raw: bytes) -> int:
        with self.lock:
            self._healthy()
            try:
                if not self.reset_started or self.pending_command is not None:
                    raise ValueError("command without reset or pending command decode")
                raw = _payload(raw)
                self.message_sequence += 1
                message_sequence = self.message_sequence
                self._append("command_received", kind="position_command",
                             message_sequence=message_sequence, payload=raw)
                self.pending_command = message_sequence
                return message_sequence
            except Exception:
                self._mark_failed("command_receive_failed")
                raise

    def command_decoded(self, message_sequence: int, *, stamp_ns: int,
                        trajectory_id: int, ready: bool) -> None:
        with self.lock:
            self._healthy()
            try:
                if message_sequence != self.pending_command or type(ready) is not bool:
                    raise ValueError("command decode sequence or ready flag invalid")
                stamp_ns = _natural(stamp_ns, "command stamp")
                trajectory_id = _natural(trajectory_id, "trajectory id")
                self._append("command_decoded", kind="position_command",
                             message_sequence=message_sequence, sample_ns=stamp_ns,
                             extra={"trajectory_id": trajectory_id, "ready": ready})
                self.pending_command = None
            except Exception:
                self._mark_failed("command_decode_failed")
                raise

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            try:
                if not self.failed:
                    self._append("closed")
                self.stream.close()
            except BaseException:
                self.failed = True
                raise
            finally:
                self.closed = True
