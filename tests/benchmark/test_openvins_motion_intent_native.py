import hashlib
from pathlib import Path

import pytest


def action(**updates):
    value = {
        "kind": "motion_intent",
        "sample_ns": 2_621_000_000,
        "source_arrival_ns": 10_000,
        "session_id": "native-42",
        "clock_id": "gazebo-sim+linux-monotonic",
        "command_sequence": 0,
        "intent_sha256": "a" * 64,
    }
    value.update(updates)
    return value


def test_motion_intent_packet_is_exact_truth_free_and_session_bound():
    from tools.benchmark.openvins_online_shadow import encode_packet

    packet = encode_packet(action(), sequence=11, dispatch_ns=10_100)
    session = hashlib.sha256(b"native-42").hexdigest()
    clock = hashlib.sha256(b"gazebo-sim+linux-monotonic").hexdigest()
    assert packet == (
        f"M 11 2621000000 10000 10100 0 {'a' * 64} {session} {clock}\n".encode()
    )
    assert b"pose" not in packet and b"velocity" not in packet and b"truth" not in packet


@pytest.mark.parametrize(
    "mutation",
    [
        {"command_sequence": True},
        {"intent_sha256": "A" * 64},
        {"session_id": ""},
        {"clock_id": "clock with whitespace"},
        {"truth_velocity_m_s": [0.0, 0.0, 0.0]},
    ],
)
def test_motion_intent_packet_rejects_schema_identity_and_truth_mutations(mutation):
    from tools.benchmark.openvins_online_shadow import encode_packet

    with pytest.raises(ValueError):
        encode_packet(action(**mutation), sequence=11, dispatch_ns=10_100)
    with pytest.raises(ValueError):
        encode_packet(action(), sequence=11, dispatch_ns=10_100, pixels=b"x")


def test_native_motion_intent_ack_projection_is_exact():
    from tools.benchmark.openvins_online_shadow import project_motion_intent_ack

    row = {
        "sequence": 11,
        "kind": "M",
        "sample_ns": 2_621_000_000,
        "receive_ns": 10_101,
        "start_ns": 10_102,
        "end_ns": 10_103,
        "acknowledged_ns": 10_104,
        "source_arrival_ns": 10_000,
        "dispatch_ns": 10_100,
        "intent_sha256": "a" * 64,
        "estimator_session_sha256": hashlib.sha256(b"native-42").hexdigest(),
        "clock_id_sha256": hashlib.sha256(b"gazebo-sim+linux-monotonic").hexdigest(),
        "command_sequence": 0,
        "internal_initialized": True,
        "has_moved_since_zupt": True,
        "motion_intent_applied": True,
        "try_zupt": True,
        "zupt_only_at_beginning": True,
        "reset_counter": None,
        "fusion_eligible": False,
        "quality": None,
    }
    projected = project_motion_intent_ack(row, action())
    assert projected["native_sequence"] == 11
    assert "sequence" not in projected and "dispatch_ns" not in projected
    assert projected["try_zupt"] is projected["zupt_only_at_beginning"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "C"},
        {"estimator_session_sha256": "0" * 64},
        {"clock_id_sha256": "0" * 64},
        {"command_sequence": 1},
        {"try_zupt": False},
        {"zupt_only_at_beginning": False},
        {"motion_intent_applied": False},
    ],
)
def test_native_motion_intent_ack_projection_rejects_mutation(mutation):
    from tools.benchmark.openvins_online_shadow import project_motion_intent_ack

    base = {
        "sequence": 11,
        "kind": "M",
        "sample_ns": 2_621_000_000,
        "receive_ns": 10_101,
        "start_ns": 10_102,
        "end_ns": 10_103,
        "acknowledged_ns": 10_104,
        "source_arrival_ns": 10_000,
        "dispatch_ns": 10_100,
        "intent_sha256": "a" * 64,
        "estimator_session_sha256": hashlib.sha256(b"native-42").hexdigest(),
        "clock_id_sha256": hashlib.sha256(b"gazebo-sim+linux-monotonic").hexdigest(),
        "command_sequence": 0,
        "internal_initialized": True,
        "has_moved_since_zupt": True,
        "motion_intent_applied": True,
        "try_zupt": True,
        "zupt_only_at_beginning": True,
        "reset_counter": None,
        "fusion_eligible": False,
        "quality": None,
    }
    base.update(mutation)
    with pytest.raises(ValueError):
        project_motion_intent_ack(base, action())


def test_gpl_linked_adapter_contains_narrow_fail_closed_motion_latch():
    source = Path("tools/benchmark/openvins_online_probe.cpp").read_text()
    for text in [
        "apply_motion_intent",
        "params.try_zupt",
        "params.zupt_only_at_beginning",
        "has_moved_since_zupt = true",
        "did_zupt_update = false",
        "motion intent before internal initialization",
        "duplicate native motion intent",
    ]:
        assert text in source


def test_gpl_linked_adapter_exports_read_only_full_imu_covariance():
    source = Path("tools/benchmark/openvins_online_probe.cpp").read_text()
    for text in [
        '"state/StateHelper.h"',
        "StateHelper::get_marginal_covariance(state, {state->_imu})",
        '\\\"imu_covariance15\\\"',
        "cov.rows()!=15 || cov.cols()!=15 || !cov.allFinite()",
    ]:
        assert text in source


def test_gpl_linked_adapter_aligns_fast_targets_to_the_absolute_50_hz_grid():
    source = Path("tools/benchmark/openvins_online_probe.cpp").read_text()
    assert "align_fast_target_ns" in source
    assert "((sample + fast_period_ns - 1) / fast_period_ns) * fast_period_ns" in source
    assert "next_target=align_fast_target_ns(sample);" in source


def test_integrated_gate_reports_native_adapter_only_when_explicit():
    import io

    from tools.benchmark.motion_intent_gate import MotionIntentGate

    gate = MotionIntentGate(
        session_id="native-42",
        clock_id="gazebo-sim+linux-monotonic",
        stream=io.StringIO(),
        clock=lambda: 1,
        native_adapter_integrated=True,
    )
    assert gate.finish()["native_adapter_integrated"] is True
