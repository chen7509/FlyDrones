import copy
import io
import threading

import pytest

from tools.benchmark.disarmed_sensor_provenance import validate_event
from tools.benchmark.openvins_causal_input import raw_profile
from tools.benchmark.openvins_online_shadow import ShadowInput
from tools.benchmark.readiness_anchor import JournaledReadiness


def estimator_capture_args(tmp_path):
    return [
        "--output", str(tmp_path / "capture"),
        "--source-fanout-profile", "ready-shadow-heartbeat-estimator-v1",
        "--shadow-binary", str(tmp_path / "native"),
        "--shadow-config", str(tmp_path / "config"),
        "--reference-module", str(tmp_path / "reference"),
        "--reference-sha256", "a" * 64,
        "--motion-profile", "supported-ready-v1",
        "--physics-trace-profile", "substep-ready-v1",
    ]


def source_event(kind, sample_ns, arrival_ns):
    row = {
        "kind": kind,
        "sample_ns": sample_ns,
        "arrival_monotonic_ns": arrival_ns,
        "observed_sim_ns": sample_ns,
    }
    if kind == "imu":
        row.update(gyro_flu=[0.1, 0.2, 0.3], accel_flu=[0.0, 0.0, 9.81])
    elif kind == "rgb":
        row.update(width=160, height=120)
    elif kind == "info":
        row["camera_info"] = raw_profile()["camera_info"]
    return row


class AckNative:
    def __init__(self, *, fail_on=None):
        self.sequence = 0
        self.fail_on = fail_on

    def send(self, action, pixels=None):
        call = self.sequence + 1
        if call == self.fail_on:
            raise TimeoutError("native interrupted")
        kind = "C" if action["kind"] == "camera" else "I"
        ack = {
            "sequence": self.sequence,
            "kind": kind,
            "sample_ns": action["sample_ns"],
            "receive_ns": 1_000 + self.sequence * 10,
            "start_ns": 1_001 + self.sequence * 10,
            "end_ns": 1_002 + self.sequence * 10,
            "acknowledged_ns": 1_003 + self.sequence * 10,
            "source_arrival_ns": action["source_arrival_ns"],
            "internal_initialized": kind == "C",
            "public_initialized": False,
            "state_time_s": action["sample_ns"] / 1e9 if kind == "C" else -1.0,
        }
        self.sequence += 1
        return ack


def test_shadow_retains_exact_ack_batch_and_resets_per_source(tmp_path):
    shadow = ShadowInput(AckNative(), tmp_path, session_id="ack-batch", now=lambda: 10_000)
    pixels = b"\x80" * 57_600

    shadow.on_record(source_event("imu", 1_000_000, 100), None)
    assert [row["kind"] for row in shadow.delivery_acks] == ["I"]
    first = copy.deepcopy(shadow.delivery_acks)

    shadow.on_record(source_event("rgb", 1_000_000, 110), pixels)
    assert shadow.delivery_acks == []
    shadow.on_record(source_event("info", 1_000_000, 120), b"PB")
    assert shadow.delivery_acks == []
    shadow.on_record(source_event("imu", 4_000_000, 130), None)
    assert [row["kind"] for row in shadow.delivery_acks] == ["I", "C"]
    assert shadow.delivery_acks[-1]["sample_ns"] == 1_000_000
    assert first[0]["sequence"] == 0
    shadow.finish()


def test_shadow_retains_successful_prefix_of_failed_ack_batch(tmp_path):
    native = AckNative(fail_on=3)
    shadow = ShadowInput(native, tmp_path, session_id="partial-ack-batch", now=lambda: 10_000)
    pixels = b"\x80" * 57_600
    shadow.on_record(source_event("imu", 1_000_000, 100), None)
    shadow.on_record(source_event("rgb", 1_000_000, 110), pixels)
    shadow.on_record(source_event("info", 1_000_000, 120), b"PB")
    shadow.on_record(source_event("imu", 4_000_000, 130), None)
    assert [row["kind"] for row in shadow.delivery_acks] == ["I"]
    assert "native interrupted" in shadow.failure
    result = shadow.finish()
    assert result["last_delivery_acks"] == shadow.delivery_acks


def ack(*, sequence=4, sample_ns=2_400_000_000, acknowledged_ns=10_000_000_000,
        internal=True, public=False):
    return {
        "sequence": sequence,
        "kind": "C",
        "sample_ns": sample_ns,
        "receive_ns": acknowledged_ns - 30,
        "start_ns": acknowledged_ns - 20,
        "end_ns": acknowledged_ns - 10,
        "acknowledged_ns": acknowledged_ns,
        "source_arrival_ns": acknowledged_ns - 40,
        "dispatch_ns": acknowledged_ns - 35,
        "gray_first": 128,
        "internal_initialized": internal,
        "public_initialized": public,
        "initializer_time_s": sample_ns / 1e9 if internal else -1.0,
        "state_time_s": sample_ns / 1e9 if internal else -1.0,
        "last_regular_update_s": sample_ns / 1e9 if public else -1.0,
        "zupt_flag_latched": False,
        "has_moved_since_zupt": internal,
        "imu_state": [0.0, 0.0, 0.0, 1.0] + [0.0] * 12 if internal else None,
        "imu_covariance15": (
            [[1e-3 if row == column else 0.0 for column in range(15)] for row in range(15)]
            if internal else None
        ),
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }


def source_row(sequence=8, arrival=9_999_999_900, observed_sim=2_404_000_000,
               sample_ns=None, sim_age_at_callback_ns=None):
    sample_ns = observed_sim if sample_ns is None else sample_ns
    derived_age = observed_sim - sample_ns
    return {
        "kind": "imu",
        "source_sequence": sequence,
        "sample_ns": sample_ns,
        "arrival_monotonic_ns": arrival,
        "observed_sim_ns": observed_sim,
        "sim_age_at_callback_ns": (
            derived_age if sim_age_at_callback_ns is None else sim_age_at_callback_ns
        ),
        "gyro_flu": [0.1, 0.2, 0.3],
        "accel_flu": [0.0, 0.0, 9.81],
    }


def test_one_physics_step_sensor_lead_is_causal(tmp_path):
    gate, _, _ = setup_readiness(tmp_path)
    row = source_row(observed_sim=3_000_000, sample_ns=4_000_000)
    gate.observe_ack_batch([ack(sample_ns=4_000_000)], row)
    assert gate.proof()["estimator_internal"]["sample_ns"] == 4_000_000
    assert gate.finish()["failure"] is None


@pytest.mark.parametrize(
    "row",
    [
        source_row(observed_sim=3_000_000, sample_ns=4_000_001),
        source_row(
            observed_sim=3_000_000,
            sample_ns=4_000_000,
            sim_age_at_callback_ns=0,
        ),
    ],
)
def test_invalid_sensor_lead_or_derived_age_refuses(tmp_path, row):
    gate, _, _ = setup_readiness(tmp_path)
    with pytest.raises(ValueError, match="simulation clock"):
        gate.observe_ack_batch([ack(sample_ns=4_000_000)], row)
    assert gate.failure
    gate.finish()


def source_ready(base, now):
    for kind in ["imu", "rgb", "info"]:
        base.on_record(
            {
                "kind": kind,
                "arrival_monotonic_ns": now,
                "recorded_monotonic_ns": now,
                **({"observed_sim_ns": 1_000_000_000} if kind == "imu" else {}),
            },
            None,
        )
    base.on_record(
        {
            "kind": "heartbeat",
            "arrival_monotonic_ns": now,
            "recorded_monotonic_ns": now,
            "system_id": 9,
            "base_mode": 29,
            "observed_sim_ns": 1_000_000_000,
        },
        None,
    )


class BadJournal(io.StringIO):
    fault = None

    def write(self, value):
        if self.fault == "short":
            return len(value) - 1
        return super().write(value)

    def flush(self):
        if self.fault == "flush":
            raise OSError("flush")
        return super().flush()

    def close(self):
        if self.fault == "close":
            raise OSError("close")
        return super().close()


def setup_readiness(tmp_path, stream=None):
    from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness

    tmp_path.mkdir(parents=True, exist_ok=True)
    now = [10_000_000_000]
    base = JournaledReadiness(clock=lambda: now[0])
    gate = EstimatorAwareReadiness(tmp_path, base, clock=lambda: now[0], stream=stream)
    source_ready(base, now[0])
    return gate, base, now


def test_estimator_readiness_requires_causal_internal_camera_ack(tmp_path):
    gate, base, now = setup_readiness(tmp_path)
    assert gate.proof() is None
    gate.observe_ack_batch([ack(internal=False)], source_row())
    assert gate.proof() is None
    gate.observe_ack_batch(
        [ack(sequence=5, sample_ns=2_500_000_000)],
        source_row(sequence=9, observed_sim=2_504_000_000),
    )
    proof = gate.proof()
    assert proof["estimator_internal"]["sample_ns"] == 2_500_000_000
    assert proof["estimator_internal"]["source_sequence"] == 9
    assert proof["truth_used"] is False
    out = gate.finish()
    assert out["first_internal"] == out["latest_internal"]
    assert out["failure"] is None


def test_initializer_handoff_is_valid_but_never_grants_readiness(tmp_path):
    gate, _, _ = setup_readiness(tmp_path)
    pending = ack(sequence=600, sample_ns=2_300_000_000, internal=False)
    pending.update(initializer_time_s=1.304, state_time_s=1.304)

    gate.observe_ack_batch(
        [pending],
        source_row(sequence=649, observed_sim=2_304_000_000),
    )

    assert gate.proof() is None
    snapshot = gate.snapshot()
    assert snapshot["first_internal"] is None
    assert snapshot["latest_internal"] is None
    assert snapshot["failure"] is None
    assert gate.finish()["failure"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"initializer_time_s": -1.0, "state_time_s": 1.304},
        {"initializer_time_s": 1.304, "state_time_s": 1.305},
        {"initializer_time_s": 2.301, "state_time_s": 2.301},
        {"last_regular_update_s": 1.304},
        {"imu_state": [0.0] * 16},
        {"imu_covariance15": [[0.0] * 15 for _ in range(14)]},
        {"public_initialized": True},
        {"zupt_flag_latched": True},
        {"has_moved_since_zupt": True},
    ],
)
def test_malformed_initializer_handoff_latches_failure(tmp_path, mutation):
    gate, _, _ = setup_readiness(tmp_path)
    pending = ack(sequence=600, sample_ns=2_300_000_000, internal=False)
    pending.update(initializer_time_s=1.304, state_time_s=1.304)
    pending.update(mutation)

    with pytest.raises(ValueError):
        gate.observe_ack_batch(
            [pending],
            source_row(sequence=649, observed_sim=2_304_000_000),
        )
    assert gate.failure
    gate.finish()


def test_first_internal_is_immutable_and_latest_refreshes(tmp_path):
    gate, base, now = setup_readiness(tmp_path)
    first = ack(sequence=4, sample_ns=2_400_000_000)
    gate.observe_ack_batch([first], source_row(sequence=8))
    now[0] += 100_000_000
    second = ack(sequence=5, sample_ns=2_500_000_000, acknowledged_ns=now[0], public=True)
    gate.observe_ack_batch([second], source_row(sequence=9, arrival=now[0] - 100, observed_sim=2_504_000_000))
    snapshot = gate.snapshot()
    assert snapshot["first_internal"]["native_sequence"] == 4
    assert snapshot["latest_internal"]["native_sequence"] == 5
    assert snapshot["latest_internal"]["public_initialized"] is True
    gate.finish()


@pytest.mark.parametrize(
    "mutation",
    ["not_list", "not_dict", "kind", "bool_sequence", "clock", "state_time", "duplicate", "future", "extra"],
)
def test_invalid_estimator_evidence_latches_failure(tmp_path, mutation):
    gate, base, now = setup_readiness(tmp_path)
    value = ack()
    batch = [value]
    row = source_row()
    if mutation == "not_list":
        batch = value
    elif mutation == "not_dict":
        batch = [None]
    elif mutation == "kind":
        value["kind"] = "X"
    elif mutation == "bool_sequence":
        value["sequence"] = True
    elif mutation == "clock":
        value["start_ns"] = value["end_ns"] + 1
    elif mutation == "state_time":
        value["state_time_s"] += 0.01
    elif mutation == "duplicate":
        gate.observe_ack_batch([copy.deepcopy(value)], row)
    elif mutation == "future":
        value["acknowledged_ns"] = now[0] + 1
    elif mutation == "extra":
        value["truth_pose"] = [0, 0, 0]
    with pytest.raises(ValueError):
        gate.observe_ack_batch(batch, row)
    assert gate.failure
    with pytest.raises(ValueError):
        gate.proof()
    gate.finish()


def test_stale_estimator_readiness_and_journal_failures_refuse(tmp_path):
    gate, base, now = setup_readiness(tmp_path)
    gate.observe_ack_batch([ack()], source_row())
    now[0] += 2_000_000_001
    with pytest.raises(ValueError, match="stale"):
        gate.proof()
    assert gate.finish()["failure"]

    for fault in ["short", "flush", "close"]:
        stream = BadJournal()
        other, _, _ = setup_readiness(tmp_path / fault, stream)
        stream.fault = fault
        if fault == "close":
            other.observe_ack_batch([ack()], source_row())
            assert other.finish()["failure"]
        else:
            with pytest.raises(ValueError):
                other.observe_ack_batch([ack()], source_row())
            assert other.finish()["failure"]


def test_proof_serializes_with_blocked_estimator_journal(tmp_path):
    stream = BadJournal()
    gate, base, now = setup_readiness(tmp_path, stream)
    entered, release = threading.Event(), threading.Event()
    original_flush = stream.flush

    def blocked_flush():
        entered.set()
        assert release.wait(2)
        original_flush()

    stream.flush = blocked_flush
    observer = threading.Thread(target=lambda: gate.observe_ack_batch([ack()], source_row()))
    observer.start()
    assert entered.wait(1)
    result = []
    prover = threading.Thread(target=lambda: result.append(gate.proof()))
    prover.start()
    assert not result
    release.set()
    observer.join(2)
    prover.join(2)
    assert result and result[0]["estimator_internal"]["sample_ns"] == 2_400_000_000
    gate.finish()


class AckShadow:
    failure = None

    def __init__(self, batch):
        self.batch = batch
        self.delivery_acks = []

    def on_record(self, row, payload):
        self.delivery_acks = copy.deepcopy(self.batch)


def queued_sensor(sequence=0, now=10_000_000_000):
    row = validate_event(source_event("imu", 2_504_000_000, now - 100))
    row.update(
        source_sequence=sequence,
        writer_begin_monotonic_ns=now - 90,
        recorded_monotonic_ns=now - 80,
    )
    return row


def test_estimator_heartbeat_fanout_commits_ack_before_source_readiness(tmp_path):
    from tools.benchmark.estimator_aware_readiness import (
        EstimatorAwareReadiness,
        EstimatorJournaledHeartbeatFanout,
    )

    now = [10_000_000_000]
    base = JournaledReadiness(clock=lambda: now[0])
    for kind in ["rgb", "info"]:
        base.on_record(
            {"kind": kind, "arrival_monotonic_ns": now[0], "recorded_monotonic_ns": now[0]},
            None,
        )
    base.on_record(
        {
            "kind": "heartbeat",
            "arrival_monotonic_ns": now[0],
            "recorded_monotonic_ns": now[0],
            "system_id": 9,
            "base_mode": 29,
                "observed_sim_ns": 1_000_000_000,
        },
        None,
    )
    readiness = EstimatorAwareReadiness(tmp_path, base, clock=lambda: now[0])
    shadow = AckShadow([ack(sequence=4, sample_ns=2_500_000_000)])
    fanout = EstimatorJournaledHeartbeatFanout(
        tmp_path,
        readiness,
        shadow,
        clock=lambda: now[0],
        heartbeat_stream=io.StringIO(),
    )
    fanout.on_record(queued_sensor(), None)
    proof = fanout.proof()
    assert proof["estimator_internal"]["sample_ns"] == 2_500_000_000
    assert fanout.committed == 1 and base.records["imu"]["source_sequence"] == 0
    assert fanout.finish()["profile"] == "ready-shadow-heartbeat-estimator-v1"
    assert readiness.finish()["failure"] is None


def queued_heartbeat(sequence=0, now=10_000_000_000):
    return {
        "kind": "heartbeat",
        "arrival_monotonic_ns": now - 100,
        "observed_sim_ns": 1_507_000_000,
        "system_id": 9,
        "base_mode": 29,
        "custom_mode": 50_593_792,
        "source_sequence": sequence,
        "writer_begin_monotonic_ns": now - 90,
        "recorded_monotonic_ns": now - 80,
    }


def test_estimator_heartbeat_reconciles_without_estimator_sample(tmp_path):
    """Regression for immutable study-v11 source sequence 426."""
    from tools.benchmark.estimator_aware_readiness import (
        EstimatorAwareReadiness,
        EstimatorJournaledHeartbeatFanout,
    )

    now = [10_000_000_000]
    base = JournaledReadiness(clock=lambda: now[0])
    readiness = EstimatorAwareReadiness(tmp_path, base, clock=lambda: now[0])
    shadow = AckShadow([])
    heartbeat_stream = io.StringIO()
    fanout = EstimatorJournaledHeartbeatFanout(
        tmp_path,
        readiness,
        shadow,
        clock=lambda: now[0],
        heartbeat_stream=heartbeat_stream,
    )
    queued = queued_heartbeat(now=now[0])
    raw = {
        key: value
        for key, value in queued.items()
        if key not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}
    }
    fanout.observe_heartbeat(raw)
    fanout.on_record(queued, None)

    result = fanout.finish()
    assert result["failure"] is None
    assert result["heartbeat"]["observed"] == result["heartbeat"]["reconciled"] == 1
    assert result["committed"] == 1
    assert readiness.snapshot()["latest_internal"] is None
    assert readiness.finish()["failure"] is None


def test_estimator_heartbeat_refuses_native_ack_without_sample_attribution(tmp_path):
    from tools.benchmark.estimator_aware_readiness import (
        EstimatorAwareReadiness,
        EstimatorJournaledHeartbeatFanout,
    )

    now = [10_000_000_000]
    base = JournaledReadiness(clock=lambda: now[0])
    readiness = EstimatorAwareReadiness(tmp_path, base, clock=lambda: now[0])
    fanout = EstimatorJournaledHeartbeatFanout(
        tmp_path,
        readiness,
        AckShadow([ack()]),
        clock=lambda: now[0],
        heartbeat_stream=io.StringIO(),
    )
    queued = queued_heartbeat(now=now[0])
    raw = {
        key: value
        for key, value in queued.items()
        if key not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}
    }
    fanout.observe_heartbeat(raw)
    fanout.on_record(queued, None)

    assert fanout.failure and "heartbeat" in fanout.failure
    assert fanout.committed == 0
    assert base.records["heartbeat"]["arrival_monotonic_ns"] == raw["arrival_monotonic_ns"]
    fanout.finish()
    readiness.finish()


def test_invalid_ack_batch_fails_fanout_before_readiness_commit(tmp_path):
    from tools.benchmark.estimator_aware_readiness import (
        EstimatorAwareReadiness,
        EstimatorJournaledHeartbeatFanout,
    )

    now = [10_000_000_000]
    base = JournaledReadiness(clock=lambda: now[0])
    readiness = EstimatorAwareReadiness(tmp_path, base, clock=lambda: now[0])
    shadow = AckShadow([{**ack(), "truth_pose": [0, 0, 0]}])
    fanout = EstimatorJournaledHeartbeatFanout(
        tmp_path,
        readiness,
        shadow,
        clock=lambda: now[0],
        heartbeat_stream=io.StringIO(),
    )
    fanout.on_record(queued_sensor(), None)
    assert fanout.failure and "imu" not in base.records
    assert not fanout.pre_step(lambda: pytest.fail("force"), lambda: None)
    fanout.finish()
    readiness.finish()


def test_capture_profile_builds_estimator_readiness_and_fanout(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import (
        build_readiness,
        build_source_fanout,
        finish_readiness,
        parse_capture_args,
    )
    from tools.benchmark.estimator_aware_readiness import (
        EstimatorAwareReadiness,
        EstimatorJournaledHeartbeatFanout,
    )

    args = parse_capture_args(estimator_capture_args(tmp_path))
    base, readiness = build_readiness(tmp_path, args.source_fanout_profile, clock=lambda: 1_000)

    class Shadow:
        failure = None
        delivery_acks = []

        def on_record(self, row, payload):
            return None

    fanout = build_source_fanout(tmp_path, args.source_fanout_profile, readiness, Shadow())
    assert isinstance(readiness, EstimatorAwareReadiness)
    assert readiness.source_readiness is base
    assert isinstance(fanout, EstimatorJournaledHeartbeatFanout)
    fanout.finish()
    assert finish_readiness(readiness, args.source_fanout_profile)["failure"] is None


def test_capture_profile_preserves_execution_contract_and_worker_option(tmp_path):
    from tools.benchmark.capture_contract import execution_contract, worker_options
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = parse_capture_args(estimator_capture_args(tmp_path))
    declaration = execution_contract(args)
    assert declaration["profiles"]["source_fanout_profile"] == "ready-shadow-heartbeat-estimator-v1"
    options = worker_options(args)
    index = options.index("--source-fanout-profile")
    assert options[index + 1] == "ready-shadow-heartbeat-estimator-v1"


def test_capture_profile_rejects_incomplete_or_fault_configuration(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    complete = estimator_capture_args(tmp_path)
    assert parse_capture_args(complete).source_fanout_profile == "ready-shadow-heartbeat-estimator-v1"
    with pytest.raises(SystemExit):
        parse_capture_args(complete + ["--reference-fault-profile", "native-pre-epoch-v1"])
    with pytest.raises(SystemExit):
        parse_capture_args(complete[:4])


def test_explicit_estimator_session_replacement_accepts_restarted_native_sequence(tmp_path):
    from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness

    now = [10_000_000_000]
    readiness = EstimatorAwareReadiness(
        tmp_path,
        JournaledReadiness(clock=lambda: now[0]),
        clock=lambda: now[0],
        session_id="fault-session-0",
    )
    readiness.observe_ack_batch(
        [ack(sequence=7, sample_ns=2_400_000_000, internal=True)],
        source_row(sequence=11, sample_ns=2_400_000_000),
    )
    transition = readiness.replace_session("fault-session-1", reset_total=1)
    assert transition["previous_session_id"] == "fault-session-0"
    assert transition["session_id"] == "fault-session-1"
    assert transition["reset_total"] == 1
    with pytest.raises(ValueError, match="motion intent"):
        readiness.motion_intent_state()

    readiness.observe_ack_batch(
        [ack(sequence=0, sample_ns=8_100_000_000, internal=True)],
        source_row(sequence=12, observed_sim=8_100_000_000, sample_ns=8_100_000_000),
    )
    assert readiness.motion_intent_state()["native_sequence"] == 0
    snapshot = readiness.snapshot()
    assert snapshot["session_id"] == "fault-session-1"
    assert snapshot["reset_total"] == 1
    assert snapshot["session_replacements"] == 1
    with pytest.raises(ValueError, match="session"):
        readiness.replace_session("fault-session-0", reset_total=2)
    readiness.finish()


def test_motion_intent_state_projects_latest_internal_ack(tmp_path):
    from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness

    now = [10_000_000_000]
    readiness = EstimatorAwareReadiness(
        tmp_path, JournaledReadiness(clock=lambda: now[0]), clock=lambda: now[0]
    )
    value = ack(sequence=7, sample_ns=2_400_000_000, internal=True)
    readiness.observe_ack_batch(
        [value], source_row(sequence=11, sample_ns=2_400_000_000)
    )

    assert readiness.motion_intent_state() == {
        "kind": "C",
        "native_sequence": 7,
        "sample_ns": 2_400_000_000,
        "acknowledged_ns": value["acknowledged_ns"],
        "internal_initialized": True,
        "has_moved_since_zupt": value["has_moved_since_zupt"],
        "reset_counter": None,
    }
    readiness.finish()
