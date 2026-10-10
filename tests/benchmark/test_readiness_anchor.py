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
    for kind in ["imu", "rgb", "info"]:
        fresh = row(kind, now[0] - 1)
        gate.on_record(fresh, None)
    proof = gate.proof()
    assert proof is not None
    assert proof["freshness"]["heartbeat_wall_age_ns"] == 2_000_000_001
    assert proof["freshness"]["heartbeat_sim_age_ns"] == 0


def test_heartbeat_uses_simulation_age_while_high_rate_sources_use_wall_age():
    now = [10_000_000_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    for kind in ["imu", "rgb", "info", "heartbeat"]:
        initial = row(kind, now[0] - 1)
        if kind == "heartbeat":
            initial["observed_sim_ns"] = 3_679_000_000
        gate.on_record(initial, None)

    # Host time can exceed the heartbeat limit while slow lockstep simulation
    # has not advanced far enough to owe another 1 Hz heartbeat.
    now[0] += 2_000_000_001
    for kind in ["imu", "rgb", "info"]:
        fresh = row(kind, now[0] - 1)
        fresh["observed_sim_ns"] = 4_647_000_000
        gate.on_record(fresh, None)
    proof = gate.proof()
    assert proof["freshness"]["heartbeat_wall_age_ns"] == 2_000_000_002
    assert proof["freshness"]["heartbeat_sim_age_ns"] == 968_000_000

    # A real heartbeat silence while fresh IMU simulation time advances still
    # fails at the unchanged two-second bound.
    now[0] += 1
    imu = row("imu", now[0] - 1)
    imu["observed_sim_ns"] = 5_679_000_001
    gate.on_record(imu, None)
    assert gate.proof() is None


def test_stale_high_rate_source_is_not_hidden_by_simulation_heartbeat_clock():
    now = [10_000_000_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    for kind in ["imu", "rgb", "info", "heartbeat"]:
        gate.on_record(row(kind, now[0] - 1), None)
    now[0] += 2_000_000_001
    for kind in ["imu", "info"]:
        fresh = row(kind, now[0] - 1)
        fresh["observed_sim_ns"] = 1_500_000_000
        gate.on_record(fresh, None)
    assert gate.proof() is None


@pytest.mark.parametrize("fault", ["future", "regressed", "bool"])
def test_bad_heartbeat_simulation_clock_latches(fault):
    now = [10_000_000_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    gate.on_record(row("heartbeat", now[0] - 1), None)
    now[0] += 1
    later = row("heartbeat", now[0] - 1)
    later["observed_sim_ns"] = {"future": 2_000_000, "regressed": 999_999, "bool": True}[fault]
    if fault == "future":
        gate.on_record(later, None)
        imu = row("imu", now[0] - 1)
        imu["observed_sim_ns"] = 1_500_000
        gate.on_record(imu, None)
        for kind in ["rgb", "info"]:
            gate.on_record(row(kind, now[0] - 1), None)
        proof = gate.proof()
        assert proof["records"]["heartbeat"]["observed_sim_ns"] == 1_000_000
        assert proof["freshness"]["latest_heartbeat_ahead_ns"] == 500_000
        assert gate.snapshot()["failure"] is None
    else:
        with pytest.raises(ValueError, match="heartbeat simulation clock"):
            gate.on_record(later, None)


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


@pytest.mark.parametrize("entry", ["proof", "receipt", "invalid"])
def test_clock_high_water_refusal_is_latched(entry):
    now = [102]
    gate = ready(now)
    now[0] = 2_000_000_101
    assert gate.proof() is None
    now[0] = True if entry == "invalid" else 103
    with pytest.raises(ValueError):
        if entry == "receipt":
            gate.on_record(row("imu", 101), None)
        else:
            gate.proof()
    now[0] = 2_000_000_102
    with pytest.raises(ValueError):
        gate.proof()
    assert gate.snapshot()["failure"]


def test_anchored_policy_applies_motion_intent_before_first_force():
    from tools.benchmark.motion_intent_physical import MotionIntentAnchoredPolicy

    events = []

    def prepare(anchor_ns, proof):
        events.append(("intent", anchor_ns, proof))

    policy = MotionIntentAnchoredPolicy(
        lambda: {"ready": True},
        lambda row: events.append(("anchor", row)),
        prepare_motion=prepare,
    )
    for ns in range(1_000_000, 202_000_000, 1_000_000):
        force = policy.step(ns, 1_000_000, unarmed_wall_ns=1, wall_ns=2)

    assert events[0][0] == "anchor"
    assert events[1] == ("intent", 201_000_000, {"ready": True})
    assert force != [0.0, 0.0, 0.0]


def test_anchored_policy_refuses_failed_motion_intent():
    from tools.benchmark.motion_intent_physical import MotionIntentAnchoredPolicy

    def prepare(_anchor_ns, _proof):
        raise RuntimeError("native intent refusal")

    policy = MotionIntentAnchoredPolicy(
        lambda: {"ready": True}, lambda _row: None, prepare_motion=prepare
    )
    with pytest.raises(ValueError, match="intent refusal"):
        policy.step(1_000_000, 1_000_000, unarmed_wall_ns=1, wall_ns=2)
    assert policy.anchor_ns == 201_000_000 and policy.support_steps == 0
