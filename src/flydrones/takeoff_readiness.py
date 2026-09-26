"""Takeoff transaction evidence and pure end-to-end chain classification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum


class TakeoffStage(str, Enum):
    PREFLIGHT_READY = "preflight-ready"
    ARM_SENT = "arm-sent"
    ARMED = "armed"
    TAKEOFF_SENT = "takeoff-sent"
    TAKEOFF_ACCEPTED = "takeoff-accepted"
    CLIMB_CONFIRMED = "climb-confirmed"
    OFFBOARD_PRIMED = "offboard-primed"
    OFFBOARD_CONFIRMED = "offboard-confirmed"
    MISSION_READY = "mission-ready"
    FAILED = "failed"


class TakeoffFailureReason(str, Enum):
    ARM_COMMAND_REJECTED = "arm-command-rejected"
    ARM_STATE_TIMEOUT = "arm-state-timeout"
    TAKEOFF_COMMAND_REJECTED = "takeoff-command-rejected"
    TAKEOFF_COMMAND_TIMEOUT = "takeoff-command-timeout"
    OFFBOARD_COMMAND_REJECTED = "offboard-command-rejected"
    OFFBOARD_STATE_TIMEOUT = "offboard-state-timeout"
    GAZEBO_MOTOR_COMMAND_MISSING = "gazebo-motor-command-missing"
    PX4_ACTUATOR_OUTPUT_MISSING = "px4-actuator-output-missing"
    ACTUATOR_RESPONSE_TIMEOUT = "actuator-response-timeout"
    ESTIMATOR_RESPONSE_TIMEOUT = "estimator-response-timeout"
    TAKEOFF_STATE_STALE = "takeoff-state-stale"
    WORKER_NOT_MISSION_READY = "worker-not-mission-ready"
    LEGACY_UNVERIFIED = "legacy-unverified"


@dataclass(frozen=True)
class CommandAckEvidence:
    command: int
    result: int
    target_system: int
    target_component: int
    received_at_s: float
    progress: int | None = None
    result_param2: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TakeoffEvent:
    stage: TakeoffStage
    at_s: float
    target_system: int
    target_component: int
    command: int | None = None
    ack_result: int | None = None
    armed: bool | None = None
    landed: bool | None = None
    navigation_state: int | None = None
    offboard: bool | None = None
    altitude_m: float | None = None
    status_age_s: float | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["stage"] = self.stage.value
        return result


@dataclass(frozen=True)
class TakeoffEvidence:
    target_system: int
    target_component: int
    terminal_stage: TakeoffStage
    accepted: bool
    failure_reason: TakeoffFailureReason | None = None
    baseline_altitude_m: float | None = None
    maximum_altitude_gain_m: float = 0.0
    arm_ack: CommandAckEvidence | None = None
    takeoff_ack: CommandAckEvidence | None = None
    offboard_ack: CommandAckEvidence | None = None
    armed_at_s: float | None = None
    takeoff_accepted_at_s: float | None = None
    climb_confirmed_at_s: float | None = None
    offboard_confirmed_at_s: float | None = None
    events: tuple[TakeoffEvent, ...] = field(default_factory=tuple)
    cleanup_failure: str | None = None

    def __post_init__(self) -> None:
        if self.accepted != (self.terminal_stage is TakeoffStage.MISSION_READY):
            raise ValueError("accepted takeoff evidence must terminate at mission-ready")
        if self.accepted and self.failure_reason is not None:
            raise ValueError("accepted takeoff evidence cannot contain a failure reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "target_system": self.target_system,
            "target_component": self.target_component,
            "terminal_stage": self.terminal_stage.value,
            "accepted": self.accepted,
            "failure_reason": self.failure_reason.value if self.failure_reason is not None else None,
            "baseline_altitude_m": self.baseline_altitude_m,
            "maximum_altitude_gain_m": self.maximum_altitude_gain_m,
            "arm_ack": self.arm_ack.to_dict() if self.arm_ack is not None else None,
            "takeoff_ack": self.takeoff_ack.to_dict() if self.takeoff_ack is not None else None,
            "offboard_ack": self.offboard_ack.to_dict() if self.offboard_ack is not None else None,
            "armed_at_s": self.armed_at_s,
            "takeoff_accepted_at_s": self.takeoff_accepted_at_s,
            "climb_confirmed_at_s": self.climb_confirmed_at_s,
            "offboard_confirmed_at_s": self.offboard_confirmed_at_s,
            "events": [event.to_dict() for event in self.events],
            "cleanup_failure": self.cleanup_failure,
        }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def classify_takeoff_chain(
    worker: Mapping[str, object] | None,
    ulog: Mapping[str, object] | None,
    gazebo: Mapping[str, object] | None,
    *,
    minimum_altitude_gain_m: float = 0.5,
    minimum_motor_command: float = 0.1,
) -> dict[str, object]:
    """Classify a complete worker/PX4/Gazebo takeoff evidence chain.

    Thresholds are function inputs so offline scoring cannot silently inherit
    mutable application configuration.
    """

    sections = {"worker": worker, "ulog": ulog, "gazebo": gazebo}
    missing_sections = [name for name, section in sections.items() if not isinstance(section, Mapping)]
    if missing_sections:
        return {
            "accepted": False,
            "reason": TakeoffFailureReason.LEGACY_UNVERIFIED.value,
            "missing_sections": missing_sections,
        }

    worker_data = _mapping(worker)
    ulog_data = _mapping(ulog)
    gazebo_data = _mapping(gazebo)
    worker_ready = bool(worker_data.get("accepted")) and worker_data.get("terminal_stage") == TakeoffStage.MISSION_READY.value
    px4_output = bool(ulog_data.get("actuator_output_present"))
    motor_peak = float(gazebo_data.get("maximum_motor_command", 0.0) or 0.0)
    motor_received = bool(gazebo_data.get("motor_command_received")) and motor_peak >= minimum_motor_command
    physical_gain = float(gazebo_data.get("altitude_gain_m", 0.0) or 0.0)
    physical_climb = physical_gain >= minimum_altitude_gain_m
    estimator_gain = max(
        float(ulog_data.get("estimator_altitude_gain_m", 0.0) or 0.0),
        float(worker_data.get("maximum_altitude_gain_m", 0.0) or 0.0),
    )
    estimator_climb = estimator_gain >= minimum_altitude_gain_m

    reason: str | None
    if not worker_ready:
        reason = str(worker_data.get("failure_reason") or TakeoffFailureReason.WORKER_NOT_MISSION_READY.value)
    elif not px4_output:
        reason = TakeoffFailureReason.PX4_ACTUATOR_OUTPUT_MISSING.value
    elif not motor_received:
        reason = TakeoffFailureReason.GAZEBO_MOTOR_COMMAND_MISSING.value
    elif not physical_climb:
        reason = TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value
    elif not estimator_climb:
        reason = TakeoffFailureReason.ESTIMATOR_RESPONSE_TIMEOUT.value
    else:
        reason = None

    return {
        "accepted": reason is None,
        "reason": reason,
        "worker_mission_ready": worker_ready,
        "px4_actuator_output_present": px4_output,
        "gazebo_motor_command_received": motor_received,
        "gazebo_physical_climb": physical_climb,
        "estimator_climb": estimator_climb,
    }
