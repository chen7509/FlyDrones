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
import time

from ..motor.command import FlightCommand
from ..safety import Telemetry
from .base import Drone

# ignore position (0-2), acceleration (6-8) and yaw angle (10); use velocity + yaw rate
TYPE_MASK_VEL_YAWRATE = 0b0000_0101_1100_0111
ESTIMATOR_REQUIRED_FLAGS = 1 | 2 | 4 | 8 | 32
MAV_CMD_INJECT_FAILURE = 420
GPS_FAILURE_TYPES = {"ok": 0, "off": 1, "stuck": 2, "wrong": 4}


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
        for message_id, rate_hz in ((32, 20.0), (30, 20.0), (230, 10.0)):
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
            self.m.recv_match(
                type="HEARTBEAT",
                blocking=True,
                timeout=min(0.25, deadline - now),
            )
            if self.m.motors_armed():
                return

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
        self.m.param_set_send(name, value, 6)
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
            if round(float(acknowledgement.param_value)) != value:
                raise RuntimeError(f"PX4 returned an unexpected value for {name}")
            return

    def enable_failure_injection(self, *, timeout_s: float = 3.0) -> None:
        self._set_parameter("SYS_FAILURE_EN", 1, timeout_s=timeout_s)

    def disable_gps_fusion(self, *, timeout_s: float = 3.0) -> None:
        self._set_parameter("EKF2_GPS_CTRL", 0, timeout_s=timeout_s)

    def takeoff(self) -> None:
        m = self.m
        if self.autopilot == "px4":
            m.arducopter_arm()
            self._wait_until_armed(timeout_s=self.arm_timeout_s)
            # NaN altitude -> PX4 uses MIS_TAKEOFF_ALT
            m.mav.command_long_send(m.target_system, m.target_component, self.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                                    0, 0, 0, 0, float("nan"), float("nan"), float("nan"), float("nan"))
            time.sleep(6)
            prime_period = 1.0 / self.offboard_rate_hz
            for _ in range(max(10, math.ceil(1.5 * self.offboard_rate_hz))):
                # PX4 needs a >2 Hz setpoint stream before accepting OFFBOARD.
                self._send_velocity(0, 0, 0, 0)
                time.sleep(prime_period)
            m.set_mode("OFFBOARD")
        else:
            m.set_mode("GUIDED")
            m.arducopter_arm()
            self._wait_until_armed(timeout_s=self.arm_timeout_s)
            m.mav.command_long_send(m.target_system, m.target_component, self.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                                    0, 0, 0, 0, 0, 0, 0, self.takeoff_alt)
            time.sleep(6)
        self.flying = True

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
                type=["LOCAL_POSITION_NED", "ATTITUDE", "ESTIMATOR_STATUS", "BATTERY_STATUS", "SYS_STATUS"],
                blocking=False,
            )
            if msg is None:
                break
            k = msg.get_type()
            if k == "LOCAL_POSITION_NED":
                t.x_m, t.y_m, t.alt_m, t.vz_mps = msg.x, msg.y, -msg.z, -msg.vz
                t.position_updated_at = received_at
                t.position_valid = all(
                    math.isfinite(float(value))
                    for value in (t.x_m, t.y_m, t.alt_m, t.vz_mps)
                )
            elif k == "ATTITUDE":
                t.yaw_deg, t.yaw_rate_dps = math.degrees(msg.yaw), math.degrees(msg.yawspeed)
                t.attitude_updated_at = received_at
                t.attitude_valid = all(
                    math.isfinite(float(value))
                    for value in (t.yaw_deg, t.yaw_rate_dps)
                )
            elif k == "ESTIMATOR_STATUS":
                t.estimator_updated_at = received_at
                flags = int(msg.flags)
                t.estimator_healthy = (flags & ESTIMATOR_REQUIRED_FLAGS) == ESTIMATOR_REQUIRED_FLAGS
            elif k == "SYS_STATUS" and msg.battery_remaining >= 0:
                t.battery_pct = float(msg.battery_remaining)
        t.t = received_at
        t.flying = self.flying
        return t
