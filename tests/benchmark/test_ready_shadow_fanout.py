import copy
import io
import json
import threading

import pytest

from tools.benchmark.disarmed_sensor_provenance import CaptureWriter, validate_event
from tools.benchmark.ready_shadow_fanout import ReadyShadowFanout


class Consumer:
    def __init__(self, mode=None):
        self.rows = []
        self.failure = None
        self.mode = mode

    def on_record(self, row, payload):
        self.rows.append(copy.deepcopy(row))
        if self.mode == "raise":
            raise ValueError("consumer refused")
        if self.mode == "silent":
            self.failure = "hidden failure"
        if self.mode == "mutate":
            row["gyro_flu"][0] = 900

    def proof(self):
        return {"rows": len(self.rows)}


class IdleRefusalConsumer(Consumer):
    def tick_idle(self, _wall_monotonic_ns):
        self.failure = "ValueError('pending input exceeded wall wait')"
        return False


def row(seq=0, kind="imu"):
    event = dict(kind=kind, arrival_monotonic_ns=100 + seq * 10, observed_sim_ns=1000)
    if kind == "heartbeat":
        event.update(system_id=9, base_mode=29, custom_mode=0)
    else:
        event["sample_ns"] = 1000 + seq * 1000
        if kind == "imu":
            event.update(gyro_flu=[1.0, 2.0, 3.0], accel_flu=[0.0, 0.0, 9.81])
        else:
            event.update(width=160, height=120)
    return dict(
        validate_event(event), source_sequence=seq, writer_begin_monotonic_ns=101 + seq * 10, recorded_monotonic_ns=102 + seq * 10
    )


def setup(tmp_path, **kwargs):
    now = [1000]
    readiness = kwargs.pop("readiness", Consumer())
    shadow = kwargs.pop("shadow", Consumer())
    fan = ReadyShadowFanout(tmp_path, readiness, shadow, clock=lambda: now[0], **kwargs)
    return fan, readiness, shadow, now


def test_both_receive_exact_independent_rows(tmp_path):
    f, r, s, _ = setup(tmp_path)
    first = row()
    f.on_record(first, None)
    assert r.rows == s.rows == [first]
    assert f.proof() == {"rows": 1}
    assert f.pre_step(lambda: None, lambda: None)
    out = f.finish()
    assert out["committed"] == 1 and out["failure"] is None
    events = [json.loads(x) for x in (tmp_path / "source-fanout.jsonl").read_text().splitlines()]
    assert events[-1]["dispositions"] == {"shadow": "returned", "readiness": "returned"}


def test_shadow_idle_refusal_latches_fanout_and_blocks_force(tmp_path):
    f, _, _, _ = setup(tmp_path, shadow=IdleRefusalConsumer())
    assert f.on_idle(1_250_000_001) is False
    force = []
    assert not f.pre_step(lambda: force.append(1), lambda: None)
    assert force == []
    result = f.finish()
    assert "source idle" in result["failure"]
    event = json.loads((tmp_path / "source-fanout.jsonl").read_text().splitlines()[-1])
    assert event["event"] == "source_idle_refusal"


@pytest.mark.parametrize(
    "side,mode", [("shadow", "raise"), ("shadow", "silent"), ("readiness", "raise"), ("readiness", "silent")]
)
def test_partial_delivery_latches_and_blocks_force(tmp_path, side, mode):
    f, r, s, _ = setup(tmp_path, **{side: Consumer(mode)})
    f.on_record(row(), None)
    assert f.failure
    assert len(r.rows) == (0 if side == "shadow" else 1)
    assert len(s.rows) == 1
    force = []
    assert not f.pre_step(lambda: force.append(1), lambda: None)
    assert force == []
    f.on_record(row(1), None)
    assert len(s.rows) == 1 and f.finish()["skipped"] == 1


def test_mutation_rejected_without_cross_consumer_leak(tmp_path):
    f, r, s, _ = setup(tmp_path, shadow=Consumer("mutate"))
    original = row()
    f.on_record(original, None)
    assert f.failure and r.rows == [] and original["gyro_flu"][0] == 1


@pytest.mark.parametrize("fault", ["duplicate", "gap", "bool", "future", "truth", "derived", "arrival", "clock"])
def test_bad_source_refused(tmp_path, fault):
    f, _, s, now = setup(tmp_path)
    f.on_record(row(), None)
    bad = row(1)
    if fault == "duplicate":
        bad = row()
    if fault == "gap":
        bad["source_sequence"] = 2
    if fault == "bool":
        bad["source_sequence"] = True
    if fault == "future":
        bad["recorded_monotonic_ns"] = 1001
    if fault == "truth":
        bad["gazebo_pose"] = [0, 0, 0]
    if fault == "derived":
        bad["gyro_frd"] = [9, 9, 9]
    if fault == "arrival":
        bad["arrival_monotonic_ns"] = 99
    if fault == "clock":
        now[0] = 999
    f.on_record(bad, None)
    assert f.failure and len(s.rows) == 1
    f.finish()


@pytest.mark.parametrize("fault", [None, "missing", "changed", "outside"])
def test_rgb_closed_exact_bytes_and_local_path(tmp_path, fault):
    f, r, s, _ = setup(tmp_path)
    pixels = b"a" * 57600
    directory = tmp_path / "rgb-frames"
    directory.mkdir()
    frame = directory / "1000.ppm"
    if fault != "missing":
        frame.write_bytes(b"P6\n160 120\n255\n" + pixels)
    if fault == "changed":
        frame.write_bytes(b"partial")
    if fault == "outside":
        # portable path guard test without Windows symlink privileges
        f.output = tmp_path / "other"
    f.on_record(row(kind="rgb"), pixels)
    assert bool(f.failure) == (fault is not None)
    assert len(s.rows) == int(fault is None)
    f.finish()


def test_inflight_deadline_and_wrong_thread_never_commit(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Blocking(Consumer):
        def on_record(self, record, payload):
            entered.set()
            assert release.wait(2)
            super().on_record(record, payload)

    f, r, _, now = setup(tmp_path, shadow=Blocking())
    thread = threading.Thread(target=lambda: f.on_record(row(), None))
    thread.start()
    assert entered.wait(1)
    assert f.pre_step(lambda: None, lambda: None)  # previous readiness only; no invented native success
    now[0] += 2_000_000_001
    assert not f.pre_step(lambda: pytest.fail("late force"), lambda: None)
    release.set()
    thread.join(2)
    assert not thread.is_alive() and r.rows == [] and f.failure
    f.finish()


def test_other_thread_and_source_loss_gate(tmp_path):
    f, _, _, _ = setup(tmp_path)
    f.on_record(row(), None)
    t = threading.Thread(target=lambda: f.on_record(row(1), None))
    t.start()
    t.join(1)
    assert f.failure
    assert not f.pre_step(lambda: pytest.fail("force"), lambda: None)
    f.finish()


@pytest.mark.parametrize("operation", ["write", "flush", "close"])
def test_journal_errors_reject_and_finish_preserves_reason(tmp_path, operation):
    class Bad(io.StringIO):
        def write(self, value):
            return 0 if operation == "write" else super().write(value)

        def flush(self):
            if operation == "flush":
                raise OSError("flush")

        def close(self):
            if operation == "close":
                raise OSError("close")
            super().close()

    f, _, _, _ = setup(tmp_path, stream=Bad())
    f.on_record(row(), None)
    out = f.finish()
    assert out["failure"] and out["fusion_eligible"] is False


def test_writer_assigns_sequence_before_journal_and_delivery(tmp_path):
    seen = []
    writer = CaptureWriter(tmp_path, sequence_records=True, on_record=lambda r, p: seen.append(r))
    writer.submit(
        dict(
            kind="imu", sample_ns=1000, arrival_monotonic_ns=100, observed_sim_ns=1000, gyro_flu=[0, 0, 0], accel_flu=[0, 0, 9.81]
        )
    )
    writer.finish()
    stored = json.loads((tmp_path / "events.jsonl").read_text())
    assert stored["source_sequence"] == 0 and stored == seen[0]


def test_source_health_failure_stops_action(tmp_path):
    f, _, _, _ = setup(tmp_path)

    def lost():
        raise TimeoutError("source silence")

    assert not f.pre_step(lambda: pytest.fail("force"), lost)
    assert "source silence" in f.finish()["failure"]


def test_failure_latch_serialized_after_already_running_step(tmp_path):
    f, _, _, _ = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    done = []

    def step():
        entered.set()
        assert release.wait(2)
        done.append("old_step_completed")

    t = threading.Thread(target=lambda: f.pre_step(step, lambda: None))
    t.start()
    assert entered.wait(1)
    rejected = threading.Thread(target=lambda: f.on_record(dict(row(), source_sequence=2), None))
    rejected.start()
    assert f.failure is None  # latch waits, cannot retroactively cancel a running action
    release.set()
    t.join(1)
    rejected.join(1)
    assert done == ["old_step_completed"] and f.failure
    assert not f.pre_step(lambda: done.append("bad"), lambda: None)
    f.finish()


def test_explicit_online_profile_requires_complete_configuration():
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = [
        "--output",
        "x",
        "--source-fanout-profile",
        "ready-shadow-v1",
        "--shadow-binary",
        "native",
        "--shadow-config",
        "config",
        "--reference-module",
        "ref.so",
        "--reference-sha256",
        "a" * 64,
        "--motion-profile",
        "supported-ready-v1",
        "--physics-trace-profile",
        "substep-ready-v1",
    ]
    assert parse_capture_args(args).source_fanout_profile == "ready-shadow-v1"
    for key in ["--source-fanout-profile", "--shadow-binary", "--reference-module", "--physics-trace-profile"]:
        reduced = args.copy()
        index = reduced.index(key)
        del reduced[index : index + 2]
        with pytest.raises(SystemExit):
            parse_capture_args(reduced)
    with pytest.raises(SystemExit):
        parse_capture_args(args + ["--reference-fault-profile", "native-pre-epoch-v1"])


def test_terminal_journal_failure_is_latched_before_lock_handoff(tmp_path):
    class FailTerminal(io.StringIO):
        def write(self, value):
            if json.loads(value)["event"] == "source_delivery":
                raise OSError("terminal receipt failed")
            return super().write(value)

    f, _, _, _ = setup(tmp_path, stream=FailTerminal())
    interleaving = []

    class HandoffLock:
        def __init__(self):
            self.inner = threading.RLock()
            self.once = False

        def __enter__(self):
            self.inner.acquire()
            return self

        def __exit__(self, exc_type, exc, tb):
            self.inner.release()
            if exc_type is not None and not self.once:
                self.once = True
                # Deterministically schedule a queued gate user at the first exception release.
                interleaving.append(f.pre_step(lambda: interleaving.append(f.proof()), lambda: None))

    f.lock = HandoffLock()
    f.on_record(row(), None)
    assert f.failure and not any(isinstance(x, dict) for x in interleaving)
    assert True not in interleaving
    f.finish()


@pytest.mark.parametrize("fault", ["future", "changed_rgb"])
def test_rejected_source_keeps_original_hash(tmp_path, fault):
    from tools.benchmark.ready_shadow_fanout import digest

    f, _, _, _ = setup(tmp_path)
    rejected, payload = row(), None
    if fault == "future":
        rejected["recorded_monotonic_ns"] = 1001
    else:
        rejected, payload = row(kind="rgb"), b"x" * 57600
        (tmp_path / "rgb-frames").mkdir()
        (tmp_path / "rgb-frames/1000.ppm").write_bytes(b"changed")
    expected = digest(rejected)
    f.on_record(rejected, payload)
    result = f.finish()
    assert result["failure"] and result["last_disposition"]["source_sha256"] == expected
    assert result["last_disposition"]["dispositions"] == {"shadow": "not_attempted", "readiness": "not_attempted"}


def test_concurrent_refusal_has_separate_identity(tmp_path):
    from tools.benchmark.ready_shadow_fanout import digest

    entered, release = threading.Event(), threading.Event()

    class Blocking(Consumer):
        def on_record(self, record, payload):
            entered.set()
            assert release.wait(2)

    f, _, _, _ = setup(tmp_path, shadow=Blocking())
    original, concurrent = row(), row(1)
    t = threading.Thread(target=lambda: f.on_record(original, None))
    t.start()
    assert entered.wait(1)
    f.on_record(concurrent, None)
    release.set()
    t.join(1)
    result = f.finish()
    assert result["last_disposition"]["source_sha256"] == digest(original)
    assert result["refusals"][0]["source_sha256"] == digest(concurrent)
    assert result["refusals"][0]["dispositions"] == {"shadow": "not_attempted", "readiness": "not_attempted"}


@pytest.mark.parametrize("fault", [None, "path_escape", "hash", "file_bytes"])
def test_camera_info_file_and_path_guard(tmp_path, fault):
    import hashlib

    from tools.benchmark.openvins_causal_input import raw_profile

    f, _, shadow, _ = setup(tmp_path)
    payload = b"fixed protobuf bytes"
    event = dict(
        kind="info", sample_ns=1000, arrival_monotonic_ns=100, observed_sim_ns=1000, camera_info=raw_profile()["camera_info"]
    )
    prepared = dict(
        validate_event(event),
        source_sequence=0,
        writer_begin_monotonic_ns=101,
        recorded_monotonic_ns=102,
        payload_path="camera-info-messages/1000.pb",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    folder = tmp_path / "camera-info-messages"
    folder.mkdir()
    (folder / "1000.pb").write_bytes(payload if fault != "file_bytes" else b"changed")
    if fault == "path_escape":
        prepared["payload_path"] = "../outside.pb"
    if fault == "hash":
        prepared["payload_sha256"] = "0" * 64
    f.on_record(prepared, payload)
    assert bool(f.failure) == (fault is not None)
    assert len(shadow.rows) == int(fault is None)
    f.finish()
