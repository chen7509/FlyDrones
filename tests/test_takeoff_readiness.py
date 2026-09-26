import json

import pytest

from flydrones.takeoff_readiness import (
    CommandAckEvidence,
    TakeoffEvent,
    TakeoffEvidence,
    TakeoffFailureReason,
    TakeoffStage,
    classify_takeoff_chain,
)


def _ready_evidence() -> TakeoffEvidence:
    return TakeoffEvidence(
        target_system=3,
        target_component=1,
        terminal_stage=TakeoffStage.MISSION_READY,
        accepted=True,
        baseline_altitude_m=0.02,
        maximum_altitude_gain_m=0.81,
        arm_ack=CommandAckEvidence(
            command=400,
            result=0,
            target_system=3,
            target_component=1,
            received_at_s=1.1,
        ),
        events=(
            TakeoffEvent(stage=TakeoffStage.ARM_SENT, at_s=1.0, target_system=3, target_component=1),
            TakeoffEvent(stage=TakeoffStage.MISSION_READY, at_s=4.5, target_system=3, target_component=1),
        ),
    )


def test_evidence_serialization_is_json_safe_and_preserves_event_order_and_targets():
    serialized = _ready_evidence().to_dict()

    assert json.loads(json.dumps(serialized)) == serialized
    assert serialized["target_system"] == 3
    assert serialized["target_component"] == 1
    assert [event["stage"] for event in serialized["events"]] == ["arm-sent", "mission-ready"]
    assert serialized["arm_ack"]["target_system"] == 3
    assert serialized["arm_ack"]["target_component"] == 1


def test_accepted_evidence_requires_mission_ready_terminal_stage():
    with pytest.raises(ValueError, match="mission-ready"):
        TakeoffEvidence(
            target_system=1,
            target_component=1,
            terminal_stage=TakeoffStage.CLIMB_CONFIRMED,
            accepted=True,
        )


@pytest.mark.parametrize("missing", ["worker", "ulog", "gazebo"])
def test_missing_chain_section_is_legacy_unverified(missing):
    sections = {
        "worker": _ready_evidence().to_dict(),
        "ulog": {"actuator_output_present": True, "estimator_altitude_gain_m": 0.8},
        "gazebo": {"motor_command_received": True, "maximum_motor_command": 0.9, "altitude_gain_m": 0.8},
    }
    sections[missing] = None

    result = classify_takeoff_chain(
        sections["worker"],
        sections["ulog"],
        sections["gazebo"],
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert not result["accepted"]
    assert result["reason"] == "legacy-unverified"
    assert result["missing_sections"] == [missing]


def test_classifier_reports_gazebo_motor_command_missing():
    result = classify_takeoff_chain(
        _ready_evidence().to_dict(),
        {"actuator_output_present": True, "estimator_altitude_gain_m": 0.8},
        {"motor_command_received": False, "maximum_motor_command": 0.0, "altitude_gain_m": 0.0},
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert result == {
        "accepted": False,
        "reason": TakeoffFailureReason.GAZEBO_MOTOR_COMMAND_MISSING.value,
        "worker_mission_ready": True,
        "px4_actuator_output_present": True,
        "gazebo_motor_command_received": False,
        "gazebo_physical_climb": False,
        "estimator_climb": True,
    }


def test_classifier_reports_actuator_response_timeout():
    result = classify_takeoff_chain(
        _ready_evidence().to_dict(),
        {"actuator_output_present": True, "estimator_altitude_gain_m": 0.0},
        {"motor_command_received": True, "maximum_motor_command": 0.9, "altitude_gain_m": 0.04},
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert result["reason"] == TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value
    assert not result["gazebo_physical_climb"]


def test_classifier_reports_estimator_response_timeout():
    worker = _ready_evidence().to_dict()
    worker["maximum_altitude_gain_m"] = 0.03
    result = classify_takeoff_chain(
        worker,
        {"actuator_output_present": True, "estimator_altitude_gain_m": 0.03},
        {"motor_command_received": True, "maximum_motor_command": 0.9, "altitude_gain_m": 0.75},
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert result["reason"] == TakeoffFailureReason.ESTIMATOR_RESPONSE_TIMEOUT.value
    assert result["gazebo_physical_climb"]
    assert not result["estimator_climb"]


def test_complete_matching_chain_is_accepted():
    result = classify_takeoff_chain(
        _ready_evidence().to_dict(),
        {"actuator_output_present": True, "estimator_altitude_gain_m": 0.8},
        {"motor_command_received": True, "maximum_motor_command": 0.9, "altitude_gain_m": 0.75},
        minimum_altitude_gain_m=0.5,
        minimum_motor_command=0.1,
    )

    assert result["accepted"]
    assert result["reason"] is None
