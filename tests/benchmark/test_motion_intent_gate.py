import io

import pytest


def estimator(sequence=10, sample_ns=2_400_000_000, acknowledged_ns=1000, reset_counter=None):
    return {
        "kind": "C",
        "native_sequence": sequence,
        "sample_ns": sample_ns,
        "acknowledged_ns": acknowledged_ns,
        "internal_initialized": True,
        "has_moved_since_zupt": False,
        "reset_counter": reset_counter,
    }


def command(**updates):
    value = {
        "session_id": "native-42",
        "clock_id": "gazebo-sim+linux-monotonic",
        "command_sequence": 0,
        "effective_sim_ns": 2_621_000_000,
        "issued_monotonic_ns": 1100,
        "unarmed": True,
        "safety_authorized": True,
        "velocity_setpoint_frd_m_s": [0.0, 0.4, 0.0],
        "yaw_rate_setpoint_rad_s": 0.0,
        "source": "px4-safe-setpoint-supervisor",
    }
    value.update(updates)
    return value


def native_ack(action, **updates):
    value = {
        "kind": "M",
        "native_sequence": 11,
        "sample_ns": action["sample_ns"],
        "intent_sha256": action["intent_sha256"],
        "receive_ns": 1200,
        "start_ns": 1201,
        "end_ns": 1202,
        "acknowledged_ns": 1203,
        "internal_initialized": True,
        "has_moved_since_zupt": True,
        "motion_intent_applied": True,
        "reset_counter": None,
    }
    value.update(updates)
    return value


def gate(now=lambda: 1300):
    from tools.benchmark.motion_intent_gate import MotionIntentGate

    return MotionIntentGate(
        session_id="native-42", clock_id="gazebo-sim+linux-monotonic", stream=io.StringIO(), clock=now
    )


def test_truth_free_motion_intent_must_be_applied_before_effective_step():
    value = gate()
    value.observe_estimator(estimator())
    action = value.request(command())
    assert action == {
        "kind": "motion_intent",
        "sample_ns": 2_621_000_000,
        "source_arrival_ns": 1100,
        "session_id": "native-42",
        "clock_id": "gazebo-sim+linux-monotonic",
        "command_sequence": 0,
        "intent_sha256": action["intent_sha256"],
    }
    assert value.authorize_step(2_620_999_999) is False
    value.acknowledge(native_ack(action))
    assert value.authorize_step(2_621_000_000) is True
    result = value.finish()
    assert result["qualified"] is True
    assert result["truth_used"] is False
    assert result["fusion_eligible"] is False


def test_effective_step_without_ack_latches_failure():
    value = gate()
    value.observe_estimator(estimator())
    value.request(command())
    assert value.authorize_step(2_621_000_000) is False
    assert "before native motion-intent acknowledgement" in value.failure
    with pytest.raises(ValueError):
        value.acknowledge({})


@pytest.mark.parametrize(
    "mutation",
    [
        {"session_id": "reconnected"},
        {"clock_id": "other-clock"},
        {"command_sequence": True},
        {"unarmed": False},
        {"safety_authorized": False},
        {"velocity_setpoint_frd_m_s": [0.0, 0.0, 0.0]},
        {"issued_monotonic_ns": 5000},
        {"truth_velocity_m_s": [0, 0, 0]},
    ],
)
def test_command_rejects_identity_safety_zero_motion_clock_and_truth(mutation):
    value = gate()
    value.observe_estimator(estimator())
    with pytest.raises(ValueError):
        value.request(command(**mutation))
    assert value.failure is not None


def test_command_before_initialization_and_duplicate_are_refused():
    early = gate()
    with pytest.raises(ValueError, match="internal initialization"):
        early.request(command())
    value = gate()
    value.observe_estimator(estimator())
    value.request(command())
    with pytest.raises(ValueError, match="already exists"):
        value.request(command(command_sequence=1))


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "C"},
        {"sample_ns": 2_621_000_001},
        {"intent_sha256": "0" * 64},
        {"receive_ns": 1099},
        {"acknowledged_ns": 2_000_000_101},
        {"internal_initialized": False},
        {"has_moved_since_zupt": False},
        {"motion_intent_applied": False},
        {"reset_counter": 1},
    ],
)
def test_native_ack_rejects_mutation_lateness_reset_and_unapplied_state(mutation):
    value = gate(now=lambda: 2_000_000_100)
    value.observe_estimator(estimator(acknowledged_ns=1_999_999_000))
    action = value.request(command(issued_monotonic_ns=1_999_999_100))
    acknowledgement = native_ack(
        action,
        receive_ns=1_999_999_200,
        start_ns=1_999_999_201,
        end_ns=1_999_999_202,
        acknowledged_ns=1_999_999_203,
    )
    acknowledgement.update(mutation)
    with pytest.raises(ValueError):
        value.acknowledge(acknowledgement)


def test_estimator_state_is_monotonic_and_session_reset_is_not_silent():
    value = gate()
    value.observe_estimator(estimator())
    with pytest.raises(ValueError):
        value.observe_estimator(estimator(sequence=9))
    reset = gate()
    reset.observe_estimator(estimator(reset_counter=0))
    with pytest.raises(ValueError, match="reset"):
        reset.observe_estimator(estimator(sequence=11, sample_ns=2_500_000_000, acknowledged_ns=1100, reset_counter=1))
