"""Explicit development-only invalid-call study; never edits physical or sensor state."""

from __future__ import annotations

import json
import time

from flydrones.benchmark.gateway import sim_duration_ns
from tools.benchmark.native_reference_probe import pre_motion


def expected_status(status, *, failed, last_ns):
    if (
        not isinstance(status, dict)
        or status.get("failed") is not failed
        or status.get("pending") is not False
        or type(status.get("last_ns")) is not int
        or status["last_ns"] != last_ns
    ):
        raise ValueError("runtime refusal native status mismatch")


class RuntimeRefusal:
    def __init__(self, output, reference, motion, readiness):
        self.stream = (output / "native-runtime-refusal.jsonl").open("x")
        self.reference, self.motion, self.readiness = reference, motion, readiness
        self.native = reference.probe
        self.trigger = self.exception = self.failure = None
        self.requested = False
        self.blocked_after_trigger = 0
        self.blocked_first_ns = self.blocked_last_ns = None
        reference.probe = self

    def _write(self, row):
        encoded = json.dumps(dict(row, wall_ns=time.monotonic_ns()), allow_nan=False) + "\n"
        if self.stream.write(encoded) != len(encoded):
            raise OSError("short runtime refusal journal write")
        self.stream.flush()

    def _fail(self, exc):
        self.failure = self.failure or repr(exc)
        self.reference._fail(exc)

    def pre_motion(self, info, ecm):
        try:
            ns, dt = sim_duration_ns(info.sim_time), sim_duration_ns(info.dt)
            if self.reference.errors or self.reference.failure:
                if self.trigger is not None:
                    self.blocked_after_trigger += 1
                    self.blocked_first_ns = self.blocked_first_ns or ns
                    self.blocked_last_ns = ns
                return
            if info.paused or dt != 1_000_000 or ns != (self.reference.pre_count + 1) * dt:
                raise ValueError("runtime refusal callback sequence/paused")
            if ns >= 8_000_000_000:
                raise ValueError("runtime refusal readiness deadline")
            policy = self.motion.policy
            if policy.support_steps or policy.active_steps:
                raise ValueError("runtime refusal prior force")
            if policy.anchor_ns is not None:
                proof = self.readiness()
                if proof is None or ns >= policy.anchor_ns:
                    raise ValueError("runtime refusal missing readiness/expired anchor")
                if (ns // dt) % 10 == 9:
                    if self.trigger is not None:
                        raise ValueError("duplicate runtime refusal trigger")
                    before = self.native.status()
                    expected_status(before, failed=False, last_ns=ns - dt)
                    self.trigger = dict(
                        actual_ns=ns,
                        submitted_ns=ns + dt,
                        anchor_ns=policy.anchor_ns,
                        proof=proof,
                        native_before=before,
                    )
                    self._write(dict(event="trigger_intent", **self.trigger))
                    self.requested = True
            pre_motion(self.reference, self.motion, info, ecm)
        except Exception as exc:
            self._fail(exc)

    def pre(self, ecm, ns, dt):
        if not self.requested:
            return self.native.pre(ecm, ns, dt)
        self.requested = False
        try:
            self.native.pre(ecm, ns + dt, dt)
        except Exception as exc:
            self.exception = repr(exc)
            try:
                after = self.native.status()
                self._write(dict(event="native_exception", exception=self.exception, native_after=after))
                expected_status(after, failed=True, last_ns=ns - dt)
            except Exception as log_exc:
                self._fail(log_exc)
            raise
        self._fail(RuntimeError("native unexpectedly accepted invalid epoch"))
        raise RuntimeError("native unexpectedly accepted invalid epoch")

    def post(self, ecm, ns):
        return self.native.post(ecm, ns)

    def status(self):
        return self.native.status()

    def finish(self):
        close_errors = []
        try:
            status = self.native.status()
            if not self.trigger or self.exception != "RuntimeError('native pre sequence')" or not status["failed"]:
                raise ValueError("runtime refusal expected native failure missing")
            expected_status(self.trigger["native_before"], failed=False, last_ns=self.trigger["actual_ns"] - 1_000_000)
            expected_status(status, failed=True, last_ns=self.trigger["actual_ns"] - 1_000_000)
            if self.blocked_after_trigger < 1 or self.motion.policy.support_steps or self.motion.policy.active_steps:
                raise ValueError("runtime refusal missing subsequent gate/zero force")
        except Exception as exc:
            self._fail(exc)
        for name, op in (("flush", self.stream.flush), ("close", self.stream.close)):
            try:
                op()
            except Exception as exc:
                close_errors.append(dict(operation=name, reason=repr(exc)))
                self._fail(exc)
        return dict(
            profile="native-pre-epoch-v1",
            trigger=self.trigger,
            exception=self.exception,
            failure=self.failure,
            blocked_after_trigger=self.blocked_after_trigger,
            blocked_first_ns=self.blocked_first_ns,
            blocked_last_ns=self.blocked_last_ns,
            close_errors=close_errors,
            cleanup_qualified=False,
            eligible_for_px4_fusion=False,
        )
