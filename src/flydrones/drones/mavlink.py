"""ArduPilot / PX4 multirotors over MAVLink (real vehicles or SITL).

Sends body-frame velocity + yaw-rate setpoints (SET_POSITION_TARGET_LOCAL_NED).
ArduPilot: GUIDED mode. PX4: OFFBOARD mode (setpoints are streamed before the
mode switch, as PX4 requires).

    pip install "flydrones[mavlink]"
    flydrones fly --drone mavlink --mavlink udpin:0.0.0.0:14550 --send      # SITL
    flydrones fly --drone mavlink --mavlink /dev/ttyUSB0,57600 --send      # telemetry radio
"""

from __future__ import annotations

import math
import struct
import time

from ..motor.command import FlightCommand
from ..safety import Telemetry
from ..takeoff_readiness import (
    CommandAckEvidence,
    TakeoffEvent,
    TakeoffEvidence,
    TakeoffFailureReason,
    TakeoffStage,
)
from .base import Drone

# ignore position (0-2), acceleration (6-8) and yaw angle (10); use velocity + yaw rate
TYPE_MASK_VEL_YAWRATE = 0b0000_0101_1100_0111
ESTIMATOR_REQUIRED_FLAGS = 1 | 2 | 4 | 8 | 32
MAV_CMD_INJECT_FAILURE = 420
GPS_FAILURE_TYPES = {"ok": 0, "off": 1, "stuck": 2, "wrong": 4}


def _encode_int32_parameter(value: int) -> float:
    """Encode an INT32 parameter in MAVLink's bytewise float field."""
    return struct.unpack(">f", struct.pack(">i", int(value)))[0]


def _decode_int32_parameter(value: float) -> int:
    """Decode MAVLink's bytewise float field back into an INT32 parameter."""
    return struct.unpack(">i", struct.pack(">f", float(value)))[0]


class MavlinkDrone(Drone):
    name = "mavlink"
    has_camera = False

    def __init__(self, connection: str = "udpin:0.0.0.0:14550", autopilot: str = "ardupilot", v_max: float = 1.0,
                 vz_max: float = 0.5, yaw_rate_max_dps: float = 45.0, takeoff_alt: float = 1.5,
                 offboard_rate_hz: float = 20.0, arm_timeout_s: float = 10.0):
        try:
            from pymavlink import mavutil
        except ImportError as e:  # pragma: no cover - optional dependency
            raise SystemExit("pymavlink missing: pip install 'flydrones[mavlink]'") from e
        self.mavutil = mavutil
        self.conn_str = connection
        self.autopilot = autopilot.lower()
        self.v_max, self.vz_max, self.yr_max = v_max, vz_max, math.radians(yaw_rate_max_dps)
        self.takeoff_alt = takeoff_alt
        self.offboard_rate_hz = max(5.0, float(offboard_rate_hz))
        self.arm_timeout_s = max(1.0, float(arm_timeout_s))
        self.m = None
        self._tel = Telemetry()
        self.flying = False
        self._last_controller_heartbeat_at = float("-inf")
        self._command_acks: list[CommandAckEvidence] = []
        self._unmatched_command_acks: list[CommandAckEvidence] = []

    def connect(self) -> None:
        if "," in self.conn_str:
            dev, baud = self.conn_str.split(",", 1)
            self.m = self.mavutil.mavlink_connection(dev, baud=int(baud))
        else:
            self.m = self.mavutil.mavlink_connection(self.conn_str)
        self.m.wait_heartbeat(timeout=30)
        print(f"MAVLink heartbeat from system {self.m.target_system}")
        self._send_controller_heartbeat(time.monotonic())
        # Ask PX4 for every stream used by the local state-health gate. A stale
        # or absent stream then becomes an explicit fail-closed condition.
        for message_id, rate_hz in ((32, 20.0), (30, 20.0), (230, 10.0), (245, 5.0)):
            self.m.mav.command_long_send(
                self.m.target_system,
                self.m.target_component,
                self.mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                0,
                message_id,
                1_000_000.0 / rate_hz,
                0,
                0,
                0,
                0,
                0,
            )

    def _send_controller_heartbeat(self, now: float) -> None:
        if now - self._last_controller_heartbeat_at < 1.0:
            return
        # This is a vehicle-local control endpoint. PX4 classifies the MAVLink
        # sender as a GCS so its standard data-link health check sees the link;
        # no shared or central controller is involved.
        self.m.mav.heartbeat_send(6, 8, 0, 0, 4)
        self._last_controller_heartbeat_at = now

    def _wait_until_armed(self, *, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"PX4 did not arm within {timeout_s:.1f} seconds")
            self._send_controller_heartbeat(now)
            message = self.m.recv_match(
                type="HEARTBEAT",
                blocking=True,
                timeout=min(0.25, deadline - now),
            )
            if message is not None:
                self._ingest_message(message, received_at=now)
            if self._tel.armed is True or self.m.motors_armed():
                return

    @staticmethod
    def _message_source(message, field: str, method: str, fallback: int) -> int:
        getter = getattr(message, method, None)
        if callable(getter):
            return int(getter())
        value = getattr(message, field, None)
        return fallback if value is None else int(value)

    def _ingest_message(self, message, *, received_at: float) -> None:
        """Update cached state for one message without refreshing unrelated streams."""

        telemetry = self._tel
        kind = message.get_type()
        if kind == "LOCAL_POSITION_NED":
            telemetry.x_m, telemetry.y_m = message.x, message.y
            telemetry.alt_m, telemetry.vz_mps = -message.z, -message.vz
            telemetry.position_updated_at = received_at
            telemetry.position_valid = all(
                math.isfinite(float(value))
                for value in (telemetry.x_m, telemetry.y_m, telemetry.alt_m, telemetry.vz_mps)
            )
        elif kind == "ATTITUDE":
            telemetry.yaw_deg = math.degrees(message.yaw)
            telemetry.yaw_rate_dps = math.degrees(message.yawspeed)
            telemetry.attitude_updated_at = received_at
            telemetry.attitude_valid = all(
                math.isfinite(float(value))
                for value in (telemetry.yaw_deg, telemetry.yaw_rate_dps)
            )
        elif kind == "ESTIMATOR_STATUS":
            telemetry.estimator_updated_at = received_at
            flags = int(message.flags)
            telemetry.estimator_healthy = (flags & ESTIMATOR_REQUIRED_FLAGS) == ESTIMATOR_REQUIRED_FLAGS
        elif kind == "SYS_STATUS" and message.battery_remaining >= 0:
            telemetry.battery_pct = float(message.battery_remaining)
        elif kind == "HEARTBEAT":
            armed_flag = int(getattr(self.mavutil.mavlink, "MAV_MODE_FLAG_SAFETY_ARMED", 128))
            telemetry.armed = bool(int(message.base_mode) & armed_flag)
            telemetry.navigation_state = (int(message.custom_mode) >> 16) & 0xFF
            telemetry.offboard = telemetry.navigation_state == 6
            telemetry.status_updated_at = received_at
        elif kind == "EXTENDED_SYS_STATE":
            landed_state = int(message.landed_state)
            on_ground = int(getattr(self.mavutil.mavlink, "MAV_LANDED_STATE_ON_GROUND", 1))
            in_air = int(getattr(self.mavutil.mavlink, "MAV_LANDED_STATE_IN_AIR", 2))
            telemetry.landed = True if landed_state == on_ground else False if landed_state == in_air else None
            telemetry.status_updated_at = received_at
        elif kind == "COMMAND_ACK":
            source_system = self._message_source(
                message,
                "source_system",
                "get_srcSystem",
                int(self.m.target_system),
            )
            source_component = self._message_source(
                message,
                "source_component",
                "get_srcComponent",
                int(self.m.target_component),
            )
            target_system = int(getattr(message, "target_system", 0) or 0)
            target_component = int(getattr(message, "target_component", 0) or 0)
            acknowledgement = CommandAckEvidence(
                command=int(message.command),
                result=int(message.result),
                target_system=target_system,
                target_component=target_component,
                received_at_s=received_at,
                progress=int(message.progress) if getattr(message, "progress", None) is not None else None,
                result_param2=int(message.result_param2) if getattr(message, "result_param2", None) is not None else None,
                source_system=source_system,
                source_component=source_component,
            )
            if not hasattr(self, "_command_acks"):
                self._command_acks = []
            self._command_acks.append(acknowledgement)

    def _wait_command_ack(self, command: int, *, timeout_s: float) -> CommandAckEvidence:
        deadline = time.monotonic() + timeout_s
        in_progress = int(getattr(self.mavutil.mavlink, "MAV_RESULT_IN_PROGRESS", 5))
        if not hasattr(self, "_command_acks"):
            self._command_acks = []
        if not hasattr(self, "_unmatched_command_acks"):
            self._unmatched_command_acks = []
        vehicle_component = int(self.m.target_component)
        local_system = int(getattr(self.m, "source_system", self.m.target_system))
        local_component = int(getattr(self.m, "source_component", self.m.target_component))
        while True:
            retained: list[CommandAckEvidence] = []
            for acknowledgement in self._command_acks:
                matches = (
                    acknowledgement.command == command
                    and acknowledgement.source_system in (0, int(self.m.target_system))
                    and (
                        vehicle_component == 0
                        or acknowledgement.source_component in (0, vehicle_component)
                    )
                    and acknowledgement.target_system in (0, local_system)
                    and acknowledgement.target_component in (0, local_component)
                )
                if not matches:
                    self._unmatched_command_acks.append(acknowledgement)
                    continue
                if acknowledgement.result == in_progress:
                    continue
                self._command_acks = retained
                return acknowledgement
            self._command_acks = retained

            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"PX4 did not acknowledge command {command} within {timeout_s:.1f} seconds")
            self._send_controller_heartbeat(now)
            message = self.m.recv_match(blocking=True, timeout=min(0.25, deadline - now))
            if message is not None:
                self._ingest_message(message, received_at=now)

    def _send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        self.m.mav.set_position_target_local_ned_send(
            0, self.m.target_system, self.m.target_component, self.mavutil.mavlink.MAV_FRAME_BODY_NED,
            TYPE_MASK_VEL_YAWRATE, 0, 0, 0, vx, vy, vz, 0, 0, 0, 0, yaw_rate)

    def inject_gps_failure(self, mode: str, *, timeout_s: float = 3.0) -> None:
        try:
            failure_type = GPS_FAILURE_TYPES[mode]
        except KeyError as exc:
            raise ValueError(f"unsupported GPS failure mode: {mode}") from exc
        self.m.mav.command_long_send(
            self.m.target_system,
            self.m.target_component,
            MAV_CMD_INJECT_FAILURE,
            0,
            4,
            failure_type,
            0,
            0,
            0,
            0,
            0,
        )
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError(f"PX4 did not acknowledge GPS failure mode {mode}")
            acknowledgement = self.m.recv_match(
                type="COMMAND_ACK",
                blocking=True,
                timeout=min(0.25, remaining),
            )
            if acknowledgement is None or int(acknowledgement.command) != MAV_CMD_INJECT_FAILURE:
                continue
            if int(acknowledgement.result) != 0:
                raise RuntimeError(
                    f"PX4 rejected GPS failure mode {mode} with result {acknowledgement.result}"
                )
            return

    def _set_parameter(self, name: str, value: int, *, timeout_s: float) -> None:
        self.m.param_set_send(name, _encode_int32_parameter(value), 6)
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError(f"PX4 did not acknowledge parameter {name}")
            acknowledgement = self.m.recv_match(
                type="PARAM_VALUE",
                blocking=True,
                timeout=min(0.25, remaining),
            )
            if acknowledgement is None:
                continue
            param_id = acknowledgement.param_id
            if isinstance(param_id, bytes):
                param_id = param_id.decode("ascii", errors="ignore")
            if str(param_id).rstrip("\x00") != name:
                continue
            if _decode_int32_parameter(acknowledgement.param_value) != value:
                raise RuntimeError(f"PX4 returned an unexpected value for {name}")
            return

    def enable_failure_injection(self, *, timeout_s: float = 3.0) -> None:
        self._set_parameter("SYS_FAILURE_EN", 1, timeout_s=timeout_s)

    def disable_gps_fusion(self, *, timeout_s: float = 3.0) -> None:
        self._set_parameter("EKF2_GPS_CTRL", 0, timeout_s=timeout_s)

    def enable_external_vision_fusion(self, *, timeout_s: float = 3.0) -> None:
        # EKF2_EV_CTRL bit 0 = horizontal position, bit 2 = 3-D velocity.
        # Barometric altitude and magnetometer yaw remain independent fallback
        # sources, which avoids coupling this GNSS-loss experiment to a vision
        # height or heading estimate.
        self._set_parameter("EKF2_EV_CTRL", 5, timeout_s=timeout_s)

    def _takeoff_event(
        self,
        stage: TakeoffStage,
        *,
        at_s: float,
        command: int | None = None,
        acknowledgement: CommandAckEvidence | None = None,
        detail: str | None = None,
    ) -> TakeoffEvent:
        telemetry = self._tel
        return TakeoffEvent(
            stage=stage,
            at_s=at_s,
            target_system=int(self.m.target_system),
            target_component=int(self.m.target_component),
            command=command,
            ack_result=acknowledgement.result if acknowledgement is not None else None,
            armed=telemetry.armed,
            landed=telemetry.landed,
            navigation_state=telemetry.navigation_state,
            offboard=telemetry.offboard,
            altitude_m=telemetry.alt_m,
            status_age_s=(
                max(0.0, at_s - telemetry.status_updated_at)
                if telemetry.status_updated_at is not None
                else None
            ),
            detail=detail,
        )

    def _recover_failed_takeoff(self, *, timeout_s: float = 5.0) -> str | None:
        """Request LAND, confirm landed, then disarm; return cleanup failure text."""

        land_command = int(self.mavutil.mavlink.MAV_CMD_NAV_LAND)
        self.m.mav.command_long_send(
            self.m.target_system,
            self.m.target_component,
            land_command,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            telemetry = self.telemetry()
            if telemetry.landed is True:
                self.m.arducopter_disarm()
                disarm_deadline = time.monotonic() + timeout_s
                while time.monotonic() < disarm_deadline:
                    if self.telemetry().armed is False:
                        self.flying = False
                        return None
                    time.sleep(min(0.1, max(0.0, disarm_deadline - time.monotonic())))
                self.flying = False
                return "disarmed state was not confirmed before cleanup timeout"
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        self.flying = False
        return "landed state was not confirmed before cleanup timeout"

    def _takeoff_failure(
        self,
        *,
        stage: TakeoffStage,
        reason: TakeoffFailureReason,
        events: list[TakeoffEvent],
        baseline_altitude_m: float | None,
        maximum_altitude_gain_m: float,
        arm_ack: CommandAckEvidence | None,
        takeoff_ack: CommandAckEvidence | None,
        offboard_ack: CommandAckEvidence | None,
        armed_at_s: float | None,
        takeoff_accepted_at_s: float | None,
        climb_confirmed_at_s: float | None,
        recover: bool,
    ) -> TakeoffEvidence:
        now = time.monotonic()
        events.append(self._takeoff_event(stage, at_s=now, detail=reason.value))
        cleanup_failure = self._recover_failed_takeoff() if recover else None
        self.flying = False
        return TakeoffEvidence(
            target_system=int(self.m.target_system),
            target_component=int(self.m.target_component),
            terminal_stage=stage,
            accepted=False,
            failure_reason=reason,
            baseline_altitude_m=baseline_altitude_m,
            maximum_altitude_gain_m=maximum_altitude_gain_m,
            arm_ack=arm_ack,
            takeoff_ack=takeoff_ack,
            offboard_ack=offboard_ack,
            armed_at_s=armed_at_s,
            takeoff_accepted_at_s=takeoff_accepted_at_s,
            climb_confirmed_at_s=climb_confirmed_at_s,
            events=tuple(events),
            cleanup_failure=cleanup_failure,
        )

    def takeoff(self) -> TakeoffEvidence | None:
        m = self.m
        if self.autopilot == "px4":
            self.flying = False
            events: list[TakeoffEvent] = []
            arm_ack = None
            takeoff_ack = None
            offboard_ack = None
            armed_at_s = None
            takeoff_accepted_at_s = None
            climb_confirmed_at_s = None
            baseline = self.telemetry().alt_m
            maximum_gain = 0.0
            now = time.monotonic()
            events.append(self._takeoff_event(TakeoffStage.PREFLIGHT_READY, at_s=now))

            arm_command = int(self.mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM)
            m.arducopter_arm()
            events.append(self._takeoff_event(TakeoffStage.ARM_SENT, at_s=time.monotonic(), command=arm_command))
            try:
                arm_ack = self._wait_command_ack(arm_command, timeout_s=self.arm_timeout_s)
            except TimeoutError:
                return self._takeoff_failure(
                    stage=TakeoffStage.ARM_SENT,
                    reason=TakeoffFailureReason.ARM_STATE_TIMEOUT,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=None,
                    takeoff_ack=None,
                    offboard_ack=None,
                    armed_at_s=None,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=False,
                )
            accepted_result = int(getattr(self.mavutil.mavlink, "MAV_RESULT_ACCEPTED", 0))
            if arm_ack.result != accepted_result:
                return self._takeoff_failure(
                    stage=TakeoffStage.ARM_SENT,
                    reason=TakeoffFailureReason.ARM_COMMAND_REJECTED,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=None,
                    offboard_ack=None,
                    armed_at_s=None,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=False,
                )
            try:
                self._wait_until_armed(timeout_s=self.arm_timeout_s)
            except TimeoutError:
                return self._takeoff_failure(
                    stage=TakeoffStage.ARM_SENT,
                    reason=TakeoffFailureReason.ARM_STATE_TIMEOUT,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=None,
                    offboard_ack=None,
                    armed_at_s=None,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=self._tel.armed is True,
                )
            armed_status = self.telemetry()
            if armed_status.armed is not True:
                return self._takeoff_failure(
                    stage=TakeoffStage.ARM_SENT,
                    reason=TakeoffFailureReason.ARM_STATE_TIMEOUT,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=None,
                    offboard_ack=None,
                    armed_at_s=None,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=False,
                )
            armed_at_s = time.monotonic()
            events.append(self._takeoff_event(TakeoffStage.ARMED, at_s=armed_at_s, acknowledgement=arm_ack))

            # NaN altitude -> PX4 uses MIS_TAKEOFF_ALT
            takeoff_command = int(self.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF)
            m.mav.command_long_send(
                m.target_system,
                m.target_component,
                takeoff_command,
                0,
                0,
                0,
                0,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
            )
            events.append(self._takeoff_event(TakeoffStage.TAKEOFF_SENT, at_s=time.monotonic(), command=takeoff_command))
            try:
                takeoff_ack = self._wait_command_ack(takeoff_command, timeout_s=3.0)
            except TimeoutError:
                return self._takeoff_failure(
                    stage=TakeoffStage.TAKEOFF_SENT,
                    reason=TakeoffFailureReason.TAKEOFF_COMMAND_TIMEOUT,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=None,
                    offboard_ack=None,
                    armed_at_s=armed_at_s,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=True,
                )
            if takeoff_ack.result != accepted_result:
                return self._takeoff_failure(
                    stage=TakeoffStage.TAKEOFF_SENT,
                    reason=TakeoffFailureReason.TAKEOFF_COMMAND_REJECTED,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=takeoff_ack,
                    offboard_ack=None,
                    armed_at_s=armed_at_s,
                    takeoff_accepted_at_s=None,
                    climb_confirmed_at_s=None,
                    recover=True,
                )
            takeoff_accepted_at_s = time.monotonic()
            events.append(
                self._takeoff_event(
                    TakeoffStage.TAKEOFF_ACCEPTED,
                    at_s=takeoff_accepted_at_s,
                    acknowledgement=takeoff_ack,
                )
            )

            climb_deadline = time.monotonic() + 12.0
            consecutive = 0
            last_position_update = None
            poll_period = 1.0 / self.offboard_rate_hz
            while time.monotonic() < climb_deadline:
                telemetry = self.telemetry()
                if telemetry.position_updated_at != last_position_update and telemetry.alt_m is not None:
                    last_position_update = telemetry.position_updated_at
                    gain = telemetry.alt_m - (baseline or 0.0)
                    maximum_gain = max(maximum_gain, gain)
                    if gain >= 0.5 and telemetry.landed is False:
                        consecutive += 1
                    else:
                        consecutive = 0
                    if consecutive >= 3:
                        climb_confirmed_at_s = time.monotonic()
                        events.append(
                            self._takeoff_event(TakeoffStage.CLIMB_CONFIRMED, at_s=climb_confirmed_at_s)
                        )
                        break
                time.sleep(poll_period)
            else:
                return self._takeoff_failure(
                    stage=TakeoffStage.TAKEOFF_ACCEPTED,
                    reason=TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=takeoff_ack,
                    offboard_ack=None,
                    armed_at_s=armed_at_s,
                    takeoff_accepted_at_s=takeoff_accepted_at_s,
                    climb_confirmed_at_s=None,
                    recover=True,
                )

            prime_period = 1.0 / self.offboard_rate_hz
            for _ in range(max(1, math.ceil(1.5 * self.offboard_rate_hz))):
                # PX4 needs a >2 Hz setpoint stream before accepting OFFBOARD.
                self._send_velocity(0, 0, 0, 0)
                time.sleep(prime_period)
            events.append(self._takeoff_event(TakeoffStage.OFFBOARD_PRIMED, at_s=time.monotonic()))
            m.set_mode("OFFBOARD")
            offboard_command = int(self.mavutil.mavlink.MAV_CMD_DO_SET_MODE)
            try:
                offboard_ack = self._wait_command_ack(offboard_command, timeout_s=3.0)
            except TimeoutError:
                offboard_ack = None
            if offboard_ack is None or offboard_ack.result != accepted_result:
                return self._takeoff_failure(
                    stage=TakeoffStage.OFFBOARD_PRIMED,
                    reason=TakeoffFailureReason.OFFBOARD_COMMAND_REJECTED,
                    events=events,
                    baseline_altitude_m=baseline,
                    maximum_altitude_gain_m=maximum_gain,
                    arm_ack=arm_ack,
                    takeoff_ack=takeoff_ack,
                    offboard_ack=offboard_ack,
                    armed_at_s=armed_at_s,
                    takeoff_accepted_at_s=takeoff_accepted_at_s,
                    climb_confirmed_at_s=climb_confirmed_at_s,
                    recover=True,
                )
            offboard_deadline = time.monotonic() + 3.0
            while time.monotonic() < offboard_deadline:
                if self.telemetry().offboard is True:
                    offboard_confirmed_at_s = time.monotonic()
                    events.append(
                        self._takeoff_event(TakeoffStage.OFFBOARD_CONFIRMED, at_s=offboard_confirmed_at_s)
                    )
                    events.append(self._takeoff_event(TakeoffStage.MISSION_READY, at_s=offboard_confirmed_at_s))
                    self.flying = True
                    return TakeoffEvidence(
                        target_system=int(m.target_system),
                        target_component=int(m.target_component),
                        terminal_stage=TakeoffStage.MISSION_READY,
                        accepted=True,
                        baseline_altitude_m=baseline,
                        maximum_altitude_gain_m=maximum_gain,
                        arm_ack=arm_ack,
                        takeoff_ack=takeoff_ack,
                        offboard_ack=offboard_ack,
                        armed_at_s=armed_at_s,
                        takeoff_accepted_at_s=takeoff_accepted_at_s,
                        climb_confirmed_at_s=climb_confirmed_at_s,
                        offboard_confirmed_at_s=offboard_confirmed_at_s,
                        events=tuple(events),
                    )
                time.sleep(poll_period)
            return self._takeoff_failure(
                stage=TakeoffStage.OFFBOARD_PRIMED,
                reason=TakeoffFailureReason.OFFBOARD_STATE_TIMEOUT,
                events=events,
                baseline_altitude_m=baseline,
                maximum_altitude_gain_m=maximum_gain,
                arm_ack=arm_ack,
                takeoff_ack=takeoff_ack,
                offboard_ack=offboard_ack,
                armed_at_s=armed_at_s,
                takeoff_accepted_at_s=takeoff_accepted_at_s,
                climb_confirmed_at_s=climb_confirmed_at_s,
                recover=True,
            )
        else:
            m.set_mode("GUIDED")
            m.arducopter_arm()
            self._wait_until_armed(timeout_s=self.arm_timeout_s)
            m.mav.command_long_send(m.target_system, m.target_component, self.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                                    0, 0, 0, 0, 0, 0, 0, self.takeoff_alt)
            time.sleep(6)
            self.flying = True
            return None

    def send(self, cmd: FlightCommand) -> None:
        # NED body frame: +x forward, +y right, +z DOWN; yaw rate + = clockwise
        self._send_velocity(cmd.forward * self.v_max, cmd.lateral * self.v_max, -cmd.throttle * self.vz_max, cmd.yaw * self.yr_max)

    def land(self) -> None:
        if self.autopilot == "px4":
            self.m.mav.command_long_send(self.m.target_system, self.m.target_component, self.mavutil.mavlink.MAV_CMD_NAV_LAND,
                                         0, 0, 0, 0, 0, 0, 0, 0)
        else:
            self.m.set_mode("LAND")
        self.flying = False

    def emergency_stop(self) -> None:
        # force disarm (param2 = 21196). The vehicle WILL fall.
        self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                     self.mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0)
        self.flying = False

    def telemetry(self) -> Telemetry:
        t = self._tel
        received_at = time.monotonic()
        self._send_controller_heartbeat(received_at)
        while True:
            msg = self.m.recv_match(
                type=[
                    "LOCAL_POSITION_NED",
                    "ATTITUDE",
                    "ESTIMATOR_STATUS",
                    "BATTERY_STATUS",
                    "SYS_STATUS",
                    "HEARTBEAT",
                    "EXTENDED_SYS_STATE",
                    "COMMAND_ACK",
                ],
                blocking=False,
            )
            if msg is None:
                break
            self._ingest_message(msg, received_at=received_at)
        t.t = received_at
        t.flying = self.flying
        return t
