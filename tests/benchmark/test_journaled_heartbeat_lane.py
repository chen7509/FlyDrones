import copy
import io
import json
import threading

import pytest

from tools.benchmark.journaled_heartbeat_lane import JournaledHeartbeatFanout
from tools.benchmark.readiness_anchor import JournaledReadiness


class Shadow:
    failure = None

    def __init__(self):
        self.rows = []

    def on_record(self, row, payload):
        self.rows.append(copy.deepcopy(row))


def event(arrival=10_000_000_000):
    return dict(
        kind="heartbeat", arrival_monotonic_ns=arrival, observed_sim_ns=1_000_000_000, system_id=9, base_mode=29, custom_mode=0
    )


def queued(e, seq=0):
    return dict(
        e,
        source_sequence=seq,
        writer_begin_monotonic_ns=e["arrival_monotonic_ns"],
        recorded_monotonic_ns=e["arrival_monotonic_ns"],
    )


def setup(tmp_path, stream=None):
    now = [10_000_000_000]
    r = JournaledReadiness(clock=lambda: now[0])
    s = Shadow()
    f = JournaledHeartbeatFanout(tmp_path, r, s, clock=lambda: now[0], heartbeat_stream=stream)
    return f, r, s, now


def sensors(r, stamp):
    for kind in ["imu", "rgb", "info"]:
        r.on_record(dict(kind=kind, arrival_monotonic_ns=stamp, recorded_monotonic_ns=stamp), None)


def test_observe_then_reconcile_without_regressing_latest(tmp_path):
    f, r, s, now = setup(tmp_path)
    first = event()
    f.observe_heartbeat(first)
    now[0] += 100
    second = event(now[0])
    f.observe_heartbeat(second)
    f.on_record(queued(first), None)
    assert r.records["heartbeat"]["arrival_monotonic_ns"] == second["arrival_monotonic_ns"]
    f.on_record(queued(second, 1), None)
    out = f.finish()
    assert out["heartbeat"]["observed"] == out["heartbeat"]["reconciled"] == 2
    assert out["failure"] is None and len(s.rows) == 2
    log = [json.loads(x) for x in (tmp_path / "heartbeat-observations.jsonl").read_text().splitlines()]
    assert [x["event"] for x in log] == [
        "heartbeat_observed",
        "heartbeat_observed",
        "heartbeat_reconciled",
        "heartbeat_reconciled",
    ]


def test_blocked_native_new_heartbeat_does_not_need_native_lock(tmp_path):
    f, r, s, now = setup(tmp_path)
    old = event()
    f.observe_heartbeat(old)
    entered, release = threading.Event(), threading.Event()
    first_done, go = threading.Event(), threading.Event()
    second = []

    def block(row, payload):
        entered.set()
        assert release.wait(2)

    def worker():
        f.on_record(queued(old), None)
        first_done.set()
        assert go.wait(2)
        f.on_record(queued(second[0], 1), None)

    t = threading.Thread(target=worker)
    t.start()
    assert first_done.wait(1)
    s.on_record = block
    # Start a heartbeat reconciliation in the native route while a newer observation arrives.
    now[0] += 1_900_000_000
    e = event(now[0])
    f.observe_heartbeat(e)
    second.append(e)
    go.set()
    assert entered.wait(1)
    now[0] += 150_000_000
    new = event(now[0])
    f.observe_heartbeat(new)
    sensors(r, now[0])
    assert f.proof() is not None and f.pre_step(lambda: None, lambda: None)
    now[0] += 2_000_000_001
    assert not f.pre_step(lambda: pytest.fail("force after native deadline"), lambda: None)
    release.set()
    t.join(2)
    assert not t.is_alive() and f.failure
    f.finish()


@pytest.mark.parametrize(
    "fault", ["armed", "wrong_id", "bool", "future", "overflow", "duplicate", "regress", "sim_regress", "extra"]
)
def test_invalid_observation_latches(tmp_path, fault):
    f, r, s, now = setup(tmp_path)
    first = event()
    f.observe_heartbeat(first)
    f.on_record(queued(first), None)
    now[0] += 10
    e = event(now[0])
    if fault == "armed":
        e["base_mode"] = 157
    if fault == "wrong_id":
        e["system_id"] = 8
    if fault == "bool":
        e["arrival_monotonic_ns"] = True
    if fault == "future":
        e["arrival_monotonic_ns"] += 1
    if fault == "overflow":
        e["observed_sim_ns"] = 2**64
    if fault == "duplicate":
        e = first
    if fault == "regress":
        now[0] -= 11
    if fault == "sim_regress":
        e["observed_sim_ns"] = 0
    if fault == "extra":
        e["truth_pose"] = [0, 0, 0]
    with pytest.raises(ValueError):
        f.observe_heartbeat(e)
    assert not f.pre_step(lambda: pytest.fail("force"), lambda: None)
    f.finish()


@pytest.mark.parametrize("fault", ["missing", "changed", "reordered", "duplicate"])
def test_reconciliation_must_match_ordered_observations(tmp_path, fault):
    f, r, s, now = setup(tmp_path)
    e = event()
    if fault != "missing":
        f.observe_heartbeat(e)
    if fault == "changed":
        e["custom_mode"] = 1
    if fault == "reordered":
        now[0] += 1
        e = event(now[0])
        f.observe_heartbeat(e)
    f.on_record(queued(e), None)
    if fault == "duplicate":
        f.on_record(queued(e, 1), None)
    assert f.failure
    f.finish()


@pytest.mark.parametrize("cause", ["hidden_shadow", "sensor_stale", "heartbeat_stale", "pending_observation"])
def test_freshness_and_hidden_failure_not_bypassed(tmp_path, cause):
    f, r, s, now = setup(tmp_path)
    e = event()
    f.observe_heartbeat(e)
    if cause != "pending_observation":
        f.on_record(queued(e), None)
    sensors(r, now[0])
    if cause == "hidden_shadow":
        s.failure = "native failed"
    else:
        now[0] += 2_000_000_001
        if cause == "sensor_stale":
            f.observe_heartbeat(event(now[0]))
        if cause == "heartbeat_stale":
            sensors(r, now[0])

    def action():
        if f.proof() is None:
            raise ValueError("not ready")

    assert not f.pre_step(action, lambda: None)
    f.finish()


class BadStream(io.StringIO):
    fail = None

    def write(self, text):
        if self.fail == "short":
            return len(text) - 1
        return super().write(text)

    def flush(self):
        if self.fail == "flush":
            raise OSError("flush")
        super().flush()

    def close(self):
        if self.fail == "close":
            raise OSError("close")
        super().close()


@pytest.mark.parametrize("fault", ["short", "flush", "close"])
def test_log_failure_refuses(tmp_path, fault):
    stream = BadStream()
    f, r, s, now = setup(tmp_path, stream)
    stream.fail = fault
    if fault != "close":
        with pytest.raises(ValueError):
            f.observe_heartbeat(event())
        assert r.records == {}
    out = f.finish()
    assert out["failure"] and out["heartbeat"]["failure"]


def test_capacity_and_unreconciled_finish(tmp_path):
    f, r, s, now = setup(tmp_path)
    for _ in range(32):
        f.observe_heartbeat(event(now[0]))
        now[0] += 1
    with pytest.raises(ValueError):
        f.observe_heartbeat(event(now[0]))
    out = f.finish()
    assert out["failure"] and len(out["heartbeat"]["pending"]) == 32


def test_submit_exact_original_and_writer_failure(tmp_path):
    f, r, s, now = setup(tmp_path)

    class Writer:
        def submit(self, row):
            assert row == event()
            raise OSError("queue failed")

    with pytest.raises(ValueError):
        f.submit_heartbeat(event(), Writer())
    assert f.failure and not f.pre_step(lambda: pytest.fail("force"), lambda: None)
    f.finish()


def test_journal_blocking_cannot_commit_stale_arrival(tmp_path):
    stream = BadStream()
    f, r, s, now = setup(tmp_path, stream)
    stream.flush = lambda: now.__setitem__(0, now[0] + 2_000_000_001)
    with pytest.raises(ValueError):
        f.observe_heartbeat(event())
    assert r.records == {} and f.failure
    f.finish()


def test_failed_flush_latches_before_waiting_force(tmp_path):
    stream = BadStream()
    f, r, s, now = setup(tmp_path, stream)
    entered, release = threading.Event(), threading.Event()
    caught = []
    force = []

    def flush():
        entered.set()
        assert release.wait(2)
        raise OSError("flush refused")

    stream.flush = flush

    def observer():
        try:
            f.observe_heartbeat(event())
        except ValueError:
            caught.append(True)

    t = threading.Thread(target=observer)
    t.start()
    assert entered.wait(1)
    step = threading.Thread(target=lambda: f.pre_step(lambda: force.append(True), lambda: None))
    step.start()
    release.set()
    t.join(2)
    step.join(2)
    assert caught and not force and f.failure
    f.finish()


def test_constructor_failure_closes_base_journal(tmp_path):
    (tmp_path / "heartbeat-observations.jsonl").write_text("existing")
    with pytest.raises(FileExistsError):
        setup(tmp_path)
    # Windows deletion would fail if its constructor leaked the stream.
    (tmp_path / "source-fanout.jsonl").unlink()


def test_new_profile_parses_only_complete_configuration():
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = [
        "--output",
        "unused",
        "--source-fanout-profile",
        "ready-shadow-heartbeat-v1",
        "--shadow-binary",
        "native",
        "--shadow-config",
        "config",
        "--reference-module",
        "ref",
        "--reference-sha256",
        "a" * 64,
        "--motion-profile",
        "supported-ready-v1",
        "--physics-trace-profile",
        "substep-ready-v1",
    ]
    assert parse_capture_args(args).source_fanout_profile == "ready-shadow-heartbeat-v1"
    with pytest.raises(SystemExit):
        parse_capture_args(args + ["--reference-fault-profile", "native-pre-epoch-v1"])
    with pytest.raises(SystemExit):
        parse_capture_args(args[:4])


def test_capture_receiver_dispatch_keeps_original_event(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import dispatch_heartbeat

    f, r, s, now = setup(tmp_path)

    class Writer:
        def __init__(self):
            self.rows = []

        def submit(self, row):
            self.rows.append(copy.deepcopy(row))

    writer = Writer()
    original = event()
    dispatch_heartbeat(original, writer, f)
    assert writer.rows == [original] and f.observed == 1 and r.records["heartbeat"]
    f.on_record(queued(original), None)
    f.finish()
    dispatch_heartbeat(original, writer, None)
    assert writer.rows == [original, original]


def test_reconciliation_flush_retains_expired_observation(tmp_path):
    stream = BadStream()
    f, r, s, now = setup(tmp_path, stream)
    original = event()
    f.observe_heartbeat(original)
    now[0] += 1_900_000_000
    stream.flush = lambda: now.__setitem__(0, now[0] + 200_000_000)
    f.on_record(queued(original), None)
    assert f.failure
    assert f.reconciled == 0 and len(f.observations) == 1
    assert not f.pre_step(lambda: pytest.fail("force after expired reconciliation"), lambda: None)
    out = f.finish()
    assert out["heartbeat"]["pending"][0]["original"] == original
