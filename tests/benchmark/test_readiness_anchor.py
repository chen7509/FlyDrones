import io

import pytest

from tools.benchmark.capture_disarmed_sensors import parse_capture_args
from tools.benchmark.disarmed_sensor_provenance import CaptureWriter
from tools.benchmark.readiness_anchor import AnchoredPolicy, JournaledReadiness


def row(kind, stamp=100):
    r = dict(kind=kind, arrival_monotonic_ns=stamp, recorded_monotonic_ns=stamp + 1, observed_sim_ns=1000000)
    if kind == "heartbeat":
        r.update(system_id=9, base_mode=29, custom_mode=0)
    return r


def ready(clock):
    gate = JournaledReadiness(clock=lambda: clock[0])
    for k in ["imu", "rgb", "info", "heartbeat"]:
        gate.on_record(row(k), None)
    return gate


def test_journaled_freshness_and_source_completeness():
    now = [102]
    gate = JournaledReadiness(clock=lambda: now[0])
    assert gate.proof() is None
    for k in ["imu", "rgb", "info"]:
        gate.on_record(row(k), None)
    assert gate.proof() is None
    gate.on_record(row("heartbeat"), None)
    assert gate.proof()["records"]["heartbeat"]["base_mode"] == 29
    now[0] = 2000000101
    assert gate.proof() is None


@pytest.mark.parametrize("fault", ["future", "bool", "armed", "identity", "reversed", "huge"])
def test_bad_receipt_latches(fault):
    gate = JournaledReadiness(clock=lambda: 102)
    r = row("heartbeat")
    if fault == "future":
        r["recorded_monotonic_ns"] = 103
    if fault == "bool":
        r["arrival_monotonic_ns"] = True
    if fault == "armed":
        r["base_mode"] = 128
    if fault == "identity":
        r["system_id"] = 8
    if fault == "reversed":
        r["recorded_monotonic_ns"] = 99
    if fault == "huge":
        r["recorded_monotonic_ns"] = 2**100
    with pytest.raises(ValueError):
        gate.on_record(r, None)
    with pytest.raises(ValueError):
        gate.proof()


def test_delayed_anchor_immutable_and_complete_waveform():
    now = [102]
    gate = ready(now)
    available = [False]
    saved = []
    p = AnchoredPolicy(lambda: gate.proof() if available[0] else None, saved.append)
    forces = []
    for i in range(1, 25001):
        ns = i * 1000000
        if i == 2500:
            available[0] = True
        f = p.step(ns, 1000000, unarmed_wall_ns=None, wall_ns=102)
        if any(f):
            forces.append((ns, f))
    assert len(saved) == 1 and p.anchor_ns == 2700000000
    assert forces[0][0] == p.anchor_ns
    lateral = [(t, f[1]) for t, f in forces if f[1]]
    assert len(lateral) == 1600 and lateral[0][0] == 5700000000 and lateral[-1][0] == 7299000000
    assert sum(v for t, v in lateral) == 0
    assert p.finish()["full_profile_requested"]


def test_deadline_and_persist_failure():
    p = AnchoredPolicy(lambda: None, lambda x: None)
    for i in range(1, 8000):
        assert p.step(i * 1000000, 1000000, unarmed_wall_ns=None, wall_ns=102) == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="deadline"):
        p.step(8000000000, 1000000, unarmed_wall_ns=None, wall_ns=102)

    def fail(x):
        raise OSError("anchor disk failure")

    p = AnchoredPolicy(lambda: ready([102]).proof(), fail)
    with pytest.raises(ValueError):
        p.step(1000000, 1000000, unarmed_wall_ns=None, wall_ns=102)
    assert p.anchor_ns is None and p.support_steps == 0


def test_after_anchor_staleness_and_rewind_refuse():
    for fault in ["lost", "rewind"]:
        data = [ready([102]).proof()]
        p = AnchoredPolicy(lambda data=data: data[0], lambda x: None)
        p.step(1000000, 1000000, unarmed_wall_ns=None, wall_ns=102)
        if fault == "lost":
            data[0] = None
        with pytest.raises(ValueError):
            p.step(1000000 if fault == "rewind" else 2000000, 1000000, unarmed_wall_ns=None, wall_ns=102)


@pytest.mark.parametrize("fault", ["short", "flush"])
def test_recorder_does_not_grant_readiness_before_successful_journal(tmp_path, fault):
    calls = []
    writer = CaptureWriter(tmp_path, start_worker=False, on_record=lambda *a: calls.append(a))
    writer.stream.close()

    class Bad(io.StringIO):
        def write(self, s):
            return len(s) - 1 if fault == "short" else super().write(s)

        def flush(self):
            if fault == "flush":
                raise OSError("flush failure")

    writer.stream = Bad()
    with pytest.raises(OSError):
        writer._write_event(row("heartbeat"), None)
    assert not calls
    writer.stream.close()


def test_ready_cli_only_explicit_sensor_mode():
    args = ["--output", "x", "--motion-profile", "supported-ready-v1", "--physics-trace-profile", "substep-ready-v1"]
    assert parse_capture_args(args).shadow_binary is None
    with pytest.raises(SystemExit):
        parse_capture_args(args[:-1] + ["substep-supported-v1"])
    with pytest.raises(SystemExit):
        parse_capture_args(args + ["--shadow-binary", "x", "--shadow-config", "y"])
