"""Isolated native diagnostic adapter; no sensor or estimator output channel."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time

from flydrones.benchmark.gateway import sim_duration_ns
from tools.benchmark.disarmed_motion_probe import MotionPolicy
from tools.benchmark.physics_substep_trace import _state


def validate_module(module):
    if type(module.API_VERSION) is not int or module.API_VERSION != 1 or module.TESTING is not False:
        raise ValueError("unsupported/test native reference module")


def load_module(path, expected_sha):
    path = path.resolve(strict=True)
    data = path.read_bytes()
    if not path.is_file() or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("native reference binary hash mismatch")
    import gz.sim8  # noqa: F401 - register ECM before importing the shared type consumer

    spec = importlib.util.spec_from_file_location("_fly_native_reference", path)
    if spec is None or spec.loader is None:
        raise ValueError("native reference loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate_module(module)
    return module


def pre_motion(reference, motion, info, ecm):
    if info.paused:
        reference._fail(ValueError("paused native reference callback"))
        return
    if reference.pre(ecm, sim_duration_ns(info.sim_time), sim_duration_ns(info.dt)):
        motion.pre_update(info, ecm)


def post_motion(reference, motion, info, ecm):
    if reference.post(ecm, sim_duration_ns(info.sim_time)):
        motion.post_update(info, ecm)


class ReferenceRecorder:
    def __init__(self, output, errors, probe):
        self.stream = (output / "native-reference.jsonl").open("x")
        self.errors, self.probe = errors, probe
        self.failure, self.last_attempt = None, None
        self.pre_count = self.post_count = 0
        self.pending = None
        self.policy = MotionPolicy()

    def _fail(self, exc):
        self.failure = self.failure or repr(exc)
        if not any(e.startswith("native reference:") for e in self.errors):
            self.errors.append("native reference: " + self.failure)
        return False

    def pre(self, ecm, ns, dt):
        if self.errors or self.failure:
            return False
        self.last_attempt = dict(phase="pre", ns_repr=repr(ns), wall_ns=time.monotonic_ns())
        try:
            if type(ns) is not int or type(dt) is not int or dt != 1_000_000 or ns != (self.pre_count + 1) * dt:
                raise ValueError("native reference step sequence")
            if ns > 25_000_000_000 or self.pending is not None:
                raise ValueError("native reference missing post/terminal limit")
            self.probe.pre(ecm, ns, dt)
            self.pre_count += 1
            self.pending = ns
            return True
        except Exception as exc:
            return self._fail(exc)

    def post(self, ecm, ns):
        if self.errors or self.failure:
            return False
        self.last_attempt = dict(phase="post", ns_repr=repr(ns), wall_ns=time.monotonic_ns())
        try:
            if type(ns) is not int or self.pending != ns:
                raise ValueError("native reference post sequence")
            row = self.probe.post(ecm, ns)
            _state(row)
            if any(type(row[k]) is not int or row[k] != ns for k in ("pre_ns", "post_ns")):
                raise ValueError("native reference epoch mismatch")
            if row["canary_overwritten"] is not True:
                raise ValueError("native reference canary missing")
            row.update(wall_ns=time.monotonic_ns(), truth_for_abort_audit_only=True, eligible_for_px4_fusion=False)
            encoded = json.dumps(row, allow_nan=False) + "\n"
            if self.stream.write(encoded) != len(encoded):
                raise OSError("short native reference write")
            self.stream.flush()
            self.post_count += 1
            self.pending = None
            self.policy.observe(row["position"], row["velocity_world"], row["rpy"])
            return True
        except Exception as exc:
            return self._fail(exc)

    def finish(self):
        close_errors = []
        for name, op in (("flush", self.stream.flush), ("close", self.stream.close)):
            try:
                op()
            except Exception as exc:
                close_errors.append(dict(operation=name, reason=repr(exc)))
                self._fail(exc)
        status = None
        try:
            status = self.probe.status()
            if status["failed"] or status["pending"] or status["last_ns"] != 25_000_000_000:
                raise ValueError("incomplete native reference status")
            if self.pre_count != 25000 or self.post_count != 25000 or self.pending is not None:
                raise ValueError("incomplete native reference journal")
        except Exception as exc:
            self._fail(exc)
        return dict(
            pre_count=self.pre_count,
            post_count=self.post_count,
            failure=self.failure,
            last_attempt=self.last_attempt,
            native=status,
            close_errors=close_errors,
            complete=self.failure is None and not self.errors,
            eligible_for_px4_fusion=False,
        )
