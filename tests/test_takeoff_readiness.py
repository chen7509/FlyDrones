import json

import pytest

from flydrones.takeoff_readiness import (
    CommandAckEvidence,
    TakeoffEvent,
    TakeoffEvidence,
    TakeoffFailureReason,
    TakeoffStage,
    classify_takeoff_chain,
    summarize_ulog_takeoff,
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
            target_system=255,
            target_component=190,
            received_at_s=1.1,
            source_system=3,
            source_component=1,
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
    assert serialized["arm_ack"]["target_system"] == 255
    assert serialized["arm_ack"]["target_component"] == 190
    assert serialized["arm_ack"]["source_system"] == 3
    assert serialized["arm_ack"]["source_component"] == 1


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


def _ulog_datasets(*, estimator_gain=0.8, groundtruth_gain=0.8):
    return {
        "vehicle_command": {
            "timestamp": [1_000_000, 2_000_000, 3_000_000],
            "command": [400, 22, 176],
        },
        "vehicle_command_ack": {
            "timestamp": [1_100_000, 2_100_000, 3_100_000],
            "command": [400, 22, 176],
            "result": [0, 0, 0],
        },
        "actuator_motors": {
            "timestamp": [2_200_000, 2_300_000],
            "control": [[0.0, 0.0, 0.0, 0.0], [0.8, 0.8, 0.8, 0.8]],
        },
        "vehicle_local_position": {
            "timestamp": [1_000_000, 2_500_000],
            "z": [0.0, -estimator_gain],
        },
        "vehicle_local_position_groundtruth": {
            "timestamp": [1_000_000, 2_500_000],
            "z": [0.0, -groundtruth_gain],
        },
        "vehicle_land_detected": {
            "timestamp": [1_000_000, 4_000_000],
            "landed": [1, 1],
        },
    }


def test_ulog_takeoff_extracts_accepted_commands_climb_and_raw_source_timestamps():
    evidence = summarize_ulog_takeoff(_ulog_datasets(), source_sha256="ulog-sha")

    assert evidence["accepted"]
    assert evidence["reason"] is None
    assert evidence["actuator_output_present"]
    assert evidence["estimator_altitude_gain_m"] == pytest.approx(0.8)
    assert evidence["groundtruth_altitude_gain_m"] == pytest.approx(0.8)
    assert evidence["command_acks"]["takeoff"]["timestamp_us"] == 2_100_000
    assert evidence["source"]["sha256"] == "ulog-sha"
    assert evidence["timestamps_us"]["actuator_motors"] == [2_200_000, 2_300_000]
    assert "esc_status" not in evidence


def test_ulog_takeoff_extracts_flattened_motor_controls_and_ignores_non_finite_channels():
    datasets = _ulog_datasets()
    datasets["actuator_motors"] = {
        "timestamp": [2_200_000, 2_300_000],
        "control[0]": [0.0, 0.78],
        "control[1]": [0.0, 0.79],
        "control[2]": [0.0, 0.80],
        "control[3]": [0.0, 0.77],
        "control[4]": [float("nan"), float("nan")],
    }

    evidence = summarize_ulog_takeoff(datasets)

    assert evidence["accepted"]
    assert evidence["actuator_output_present"]
    assert evidence["maximum_actuator_output"] == pytest.approx(0.80)


def test_ulog_takeoff_distinguishes_physics_and_estimator_failures():
    stationary = summarize_ulog_takeoff(_ulog_datasets(groundtruth_gain=0.02))
    estimator_stale = summarize_ulog_takeoff(_ulog_datasets(estimator_gain=0.02, groundtruth_gain=0.8))

    assert stationary["reason"] == TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value
    assert estimator_stale["reason"] == TakeoffFailureReason.ESTIMATOR_RESPONSE_TIMEOUT.value


def test_ulog_takeoff_missing_dataset_is_legacy_unverified():
    datasets = _ulog_datasets()
    del datasets["vehicle_local_position_groundtruth"]

    evidence = summarize_ulog_takeoff(datasets)

    assert not evidence["accepted"]
    assert evidence["reason"] == TakeoffFailureReason.LEGACY_UNVERIFIED.value
    assert evidence["missing_datasets"] == ["vehicle_local_position_groundtruth"]
