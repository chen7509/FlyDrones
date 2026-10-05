import io
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.benchmark.test_native_reference_probe import state
from tools.benchmark.native_reference_probe import ReferenceRecorder, post_motion
from tools.benchmark.native_runtime_refusal import RuntimeRefusal


class Probe:
    def __init__(self):
        self.last, self.failed, self.calls = 0, False, []

    def pre(self, ecm, ns, dt):
        self.calls.append(ns)
        if ns != self.last + dt:
            self.failed = True
            raise RuntimeError("native pre sequence")

    def post(self, ecm, ns):
        self.last = ns
        return state(ns)

    def status(self):
        return dict(failed=self.failed, pending=False, last_ns=self.last)


def setup(tmp_path):
    p = Probe()
    r = ReferenceRecorder(tmp_path, [], p)
    m = SimpleNamespace(policy=SimpleNamespace(anchor_ns=None, support_steps=0, active_steps=0), calls=[])
    m.pre_update = lambda info, ecm: m.calls.append(int(info.sim_time.total_seconds() * 1000))
    m.post_update = lambda *a: None
    proof = {"records": {}}
    f = RuntimeRefusal(tmp_path, r, m, lambda: proof)
    return p, r, m, f


def step(r, m, f, i, paused=False):
    info = SimpleNamespace(sim_time=timedelta(milliseconds=i), dt=timedelta(milliseconds=1), paused=paused)
    f.pre_motion(info, None)
    post_motion(r, m, info, None)


def test_actual_native_call_error_and_later_callbacks_gate(tmp_path):
    p, r, m, f = setup(tmp_path)
    for i in range(1, 8):
        step(r, m, f, i)
    m.policy.anchor_ns = 207_000_000
    for i in range(8, 11):
        step(r, m, f, i)
    out = f.finish()
    assert p.failed and p.calls[-1] == 10_000_000
    assert m.calls == list(range(1, 9))
    assert out["trigger"]["actual_ns"] == 9_000_000 and out["blocked_after_trigger"] == 1
    assert out["exception"] == "RuntimeError('native pre sequence')" and not out["failure"]
    assert r.errors and not r.finish()["complete"]


@pytest.mark.parametrize("fault", ["no_ready", "late_anchor", "prior_force", "paused", "clock", "lost_ready"])
def test_invalid_trigger_conditions_fail_closed(tmp_path, fault):
    p, r, m, f = setup(tmp_path)
    if fault != "no_ready":
        m.policy.anchor_ns = 200_000_000
    if fault == "late_anchor":
        m.policy.anchor_ns = 1_000_000
    if fault == "prior_force":
        m.policy.support_steps = 1
    if fault == "lost_ready":
        f.readiness = lambda: None
    step(r, m, f, 8000 if fault == "no_ready" else 2 if fault == "clock" else 1, paused=fault == "paused")
    assert r.errors and not m.calls and not f.finish()["trigger"]
    r.finish()


@pytest.mark.parametrize("fault", ["short", "flush", "close"])
def test_fault_journal_errors_retained(tmp_path, fault):
    p, r, m, f = setup(tmp_path)
    f.stream.close()

    class Bad(io.StringIO):
        def write(self, value):
            return len(value) - 1 if fault == "short" else super().write(value)

        def flush(self):
            if fault == "flush":
                raise OSError("flush")

        def close(self):
            if fault == "close":
                raise OSError("close")
            super().close()

    f.stream = Bad()
    m.policy.anchor_ns = 200_000_000
    for i in range(1, 11):
        step(r, m, f, i)
    assert f.finish()["failure"] and r.errors
    assert 9 not in m.calls and 10 not in m.calls
    r.finish()


def test_missing_trigger_not_qualified(tmp_path):
    _, r, _, f = setup(tmp_path)
    assert f.finish()["failure"] and r.errors
    r.finish()


def test_native_unexpected_acceptance_is_failure(tmp_path):
    p, r, m, f = setup(tmp_path)
    p.pre = lambda *a: None
    m.policy.anchor_ns = 200_000_000
    for i in range(1, 11):
        step(r, m, f, i)
    assert f.finish()["failure"] and 9 not in m.calls and r.errors
    r.finish()


def test_fault_cli_only_explicit_reference_configuration():
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    base = ["--output", "x", "--reference-fault-profile", "native-pre-epoch-v1"]
    with pytest.raises(SystemExit):
        parse_capture_args(base)
    args = base + [
        "--reference-module",
        "x.so",
        "--reference-sha256",
        "a" * 64,
        "--motion-profile",
        "supported-ready-v1",
        "--physics-trace-profile",
        "substep-ready-v1",
    ]
    assert parse_capture_args(args).reference_fault_profile == "native-pre-epoch-v1"
    with pytest.raises(SystemExit):
        parse_capture_args([x.replace("native-pre-epoch-v1", "bad") for x in args])


def test_real_journal_preserves_capture_failure_and_continues_cleanup(tmp_path):
    import json

    from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

    calls = []
    result = dict(status="started", errors=[])
    with CaptureJournal(tmp_path, result) as j:
        j.cleanup("owned PX4", lambda: calls.append("stop"), priority=20)
        j.cleanup("ULog", lambda: calls.append("ulog"), priority=100)

        def fail():
            raise OSError("diagnostic close")

        j.cleanup("reference", fail, priority=74)
        raise RuntimeError("native pre sequence")
    saved = json.loads((tmp_path / "result.json").read_text())
    assert calls == ["stop", "ulog"] and saved["status"] == "capture_failed"
    assert len(saved["errors"]) == 2
