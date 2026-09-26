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
    LANDING_NOT_CONFIRMED = "landing-not-confirmed"
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
    source_system: int | None = None
    source_component: int | None = None

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


def _values(dataset: Mapping[str, object], field: str) -> list[object]:
    value = dataset.get(field, [])
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _ned_altitude_gain(dataset: Mapping[str, object]) -> float:
    z_values = [float(value) for value in _values(dataset, "z")]
    return max(0.0, z_values[0] - min(z_values)) if z_values else 0.0


def summarize_ulog_takeoff(
    datasets: Mapping[str, Mapping[str, object]],
    *,
    source_sha256: str | None = None,
    minimum_altitude_gain_m: float = 0.5,
    minimum_motor_command: float = 0.1,
) -> dict[str, object]:
    """Extract takeoff evidence from ULog datasets without inferring Gazebo receipt."""

    required = (
        "vehicle_command",
        "vehicle_command_ack",
        "actuator_motors",
        "vehicle_local_position",
        "vehicle_local_position_groundtruth",
        "vehicle_land_detected",
    )
    missing = [name for name in required if not isinstance(datasets.get(name), Mapping)]
    if missing:
        return {
            "accepted": False,
            "reason": TakeoffFailureReason.LEGACY_UNVERIFIED.value,
            "missing_datasets": missing,
            "source": {"sha256": source_sha256},
            "timestamps_us": {},
        }

    acknowledgements = _mapping(datasets["vehicle_command_ack"])
    ack_timestamps = _values(acknowledgements, "timestamp")
    ack_commands = _values(acknowledgements, "command")
    ack_results = _values(acknowledgements, "result")
    command_names = {"arm": 400, "takeoff": 22, "offboard": 176}
    command_acks: dict[str, dict[str, int] | None] = {}
    for name, command in command_names.items():
        command_acks[name] = next((
            {
                "command": command,
                "result": int(result),
                "timestamp_us": int(timestamp),
            }
            for timestamp, ack_command, result in zip(ack_timestamps, ack_commands, ack_results)
            if int(ack_command) == command
        ), None)
    commands_accepted = all(
        evidence is not None and evidence["result"] == 0
        for evidence in command_acks.values()
    )

    motors = _mapping(datasets["actuator_motors"])
    controls = _values(motors, "control")
    motor_values: list[float] = []
    for row in controls:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if isinstance(row, (list, tuple)):
            motor_values.extend(float(value) for value in row)
        else:
            motor_values.append(float(row))
    maximum_motor = max((abs(value) for value in motor_values), default=0.0)
    actuator_output_present = maximum_motor >= minimum_motor_command
    estimator_gain = _ned_altitude_gain(_mapping(datasets["vehicle_local_position"]))
    groundtruth_gain = _ned_altitude_gain(_mapping(datasets["vehicle_local_position_groundtruth"]))
    landed_values = _values(_mapping(datasets["vehicle_land_detected"]), "landed")
    landed_at_end = bool(landed_values and bool(landed_values[-1]))

    reason: str | None
    if not commands_accepted or not actuator_output_present:
        reason = TakeoffFailureReason.PX4_ACTUATOR_OUTPUT_MISSING.value
    elif groundtruth_gain < minimum_altitude_gain_m:
        reason = TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value
    elif estimator_gain < minimum_altitude_gain_m:
        reason = TakeoffFailureReason.ESTIMATOR_RESPONSE_TIMEOUT.value
    else:
        reason = None
    timestamps = {
        name: [int(value) for value in _values(_mapping(datasets[name]), "timestamp")]
        for name in required
    }
    return {
        "accepted": reason is None,
        "reason": reason,
        "missing_datasets": [],
        "command_acks": command_acks,
        "commands_accepted": commands_accepted,
        "actuator_output_present": actuator_output_present,
        "maximum_actuator_output": maximum_motor,
        "estimator_altitude_gain_m": estimator_gain,
        "groundtruth_altitude_gain_m": groundtruth_gain,
        "landed_at_end": landed_at_end,
        "source": {"sha256": source_sha256},
        "timestamps_us": timestamps,
    }


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
    elif ulog_data.get("accepted") is False:
        reason = str(ulog_data.get("reason") or TakeoffFailureReason.LEGACY_UNVERIFIED.value)
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


def actuator_model_names(fleet_size: int) -> tuple[str, ...]:
    if fleet_size not in (1, 5):
        raise ValueError("fleet_size must be one or five")
    return tuple(f"x500_depth_fly_{vehicle_id}" for vehicle_id in range(fleet_size))


def summarize_actuator_link(
    events: list[Mapping[str, object]],
    *,
    fleet_size: int,
    minimum_motor_command: float = 0.1,
    minimum_altitude_gain_m: float = 0.5,
) -> dict[str, object]:
    """Validate and summarize a read-only Gazebo actuator probe event stream."""

    models = actuator_model_names(fleet_size)
    expected_topics = {model: f"/{model}/command/motor_speed" for model in models}
    per_vehicle: dict[str, dict[str, object]] = {
        model: {
            "model": model,
            "topic": expected_topics[model],
            "topology_confirmed": False,
            "motor_command_samples": 0,
            "maximum_motor_command": 0.0,
            "motor_command_received": False,
            "odometry_samples": 0,
            "altitude_gain_m": 0.0,
            "physical_climb": False,
            "reason": None,
        }
        for model in models
    }
    altitude_samples: dict[str, list[float]] = {model: [] for model in models}
    errors = {
        "malformed_events": 0,
        "cross_model_events": 0,
        "out_of_order_events": 0,
        "probe_errors": 0,
    }
    start_count = 0
    stop_count = 0
    previous_timestamp: float | None = None

    for raw_event in events:
        if not isinstance(raw_event, Mapping):
            errors["malformed_events"] += 1
            continue
        try:
            kind = str(raw_event["event"])
            timestamp = float(raw_event["monotonic_s"])
        except (KeyError, TypeError, ValueError):
            errors["malformed_events"] += 1
            continue
        if previous_timestamp is not None and timestamp < previous_timestamp:
            errors["out_of_order_events"] += 1
        previous_timestamp = timestamp

        if kind == "start":
            start_count += 1
            continue
        if kind == "stop":
            stop_count += 1
            continue
        if kind == "error":
            errors["probe_errors"] += 1
            continue
        if kind not in {"topology", "motor-command", "odometry"}:
            errors["malformed_events"] += 1
            continue

        model = raw_event.get("model")
        if not isinstance(model, str) or model not in per_vehicle:
            errors["malformed_events"] += 1
            continue
        vehicle = per_vehicle[model]
        if kind in {"topology", "motor-command"}:
            topic = raw_event.get("topic")
            if topic != expected_topics[model]:
                errors["cross_model_events"] += 1
                continue
        if kind == "topology":
            if raw_event.get("subscription_ok") is not True:
                errors["probe_errors"] += 1
                continue
            vehicle["topology_confirmed"] = True
        elif kind == "motor-command":
            velocities = raw_event.get("velocities")
            if not isinstance(velocities, (list, tuple)) or not velocities:
                errors["malformed_events"] += 1
                continue
            try:
                peak = max(abs(float(value)) for value in velocities)
            except (TypeError, ValueError):
                errors["malformed_events"] += 1
                continue
            vehicle["motor_command_samples"] = int(vehicle["motor_command_samples"]) + 1
            vehicle["maximum_motor_command"] = max(float(vehicle["maximum_motor_command"]), peak)
        else:
            position = raw_event.get("position_m")
            if not isinstance(position, (list, tuple)) or len(position) != 3:
                errors["malformed_events"] += 1
                continue
            try:
                altitude = float(position[2])
            except (TypeError, ValueError):
                errors["malformed_events"] += 1
                continue
            altitude_samples[model].append(altitude)
            vehicle["odometry_samples"] = int(vehicle["odometry_samples"]) + 1

    for model, vehicle in per_vehicle.items():
        motor_received = (
            int(vehicle["motor_command_samples"]) > 0
            and float(vehicle["maximum_motor_command"]) >= minimum_motor_command
        )
        samples = altitude_samples[model]
        altitude_gain = max(samples) - samples[0] if samples else 0.0
        physical_climb = altitude_gain >= minimum_altitude_gain_m
        vehicle["motor_command_received"] = motor_received
        vehicle["altitude_gain_m"] = altitude_gain
        vehicle["physical_climb"] = physical_climb
        if not motor_received:
            vehicle["reason"] = TakeoffFailureReason.GAZEBO_MOTOR_COMMAND_MISSING.value
        elif not physical_climb:
            vehicle["reason"] = TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT.value

    closed_cleanly = stop_count == 1 and bool(events) and events[-1].get("event") == "stop"
    complete = all(
        bool(vehicle["topology_confirmed"])
        and int(vehicle["motor_command_samples"]) > 0
        and int(vehicle["odometry_samples"]) > 0
        for vehicle in per_vehicle.values()
    )
    structurally_valid = (
        start_count == 1
        and closed_cleanly
        and complete
        and not any(errors.values())
    )
    return {
        "schema": "flydrones-gazebo-actuator-link-summary-v1",
        "accepted": structurally_valid,
        "closed_cleanly": closed_cleanly,
        "fleet_size": fleet_size,
        "vehicles": per_vehicle,
        "errors": errors,
    }
