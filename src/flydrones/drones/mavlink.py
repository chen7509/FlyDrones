"""ArduPilot / PX4 multirotors over MAVLink (real vehicles or SITL).

Sends body-frame velocity + yaw-rate setpoints (SET_POSITION_TARGET_LOCAL_NED).
ArduPilot: GUIDED mode. PX4: OFFBOARD mode (setpoints are streamed before the
mode switch, as PX4 requires).

    pip install "flydrones[mavlink]"
    flydrones fly --drone mavlink --autopilot px4 --mavlink udpin:0.0.0.0:14540 --send
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


class MavlinkDrone(Drone):
    name = "mavlink"
    has_camera = False

    def __init__(self, connection: str | None = None, autopilot: str = "ardupilot", v_max: float = 1.0,
                 vz_max: float = 0.5, yaw_rate_max_dps: float = 45.0, takeoff_alt: float = 1.5,
                 takeoff_timeout: float = 20.0, offboard_rate_hz: float = 20.0, mavutil_module=None,
                 time_fn=None, sleep_fn=None):
        if mavutil_module is None:
            try:
                from pymavlink import mavutil
            except ImportError as e:  # pragma: no cover - optional dependency
                raise SystemExit("pymavlink missing: pip install 'flydrones[mavlink]'") from e
            mavutil_module = mavutil
        self.autopilot = autopilot.lower()
        self.mavutil = mavutil_module
        self.conn_str = connection or ("udpin:0.0.0.0:14540" if self.autopilot == "px4" else "udpin:0.0.0.0:14550")
        self.v_max, self.vz_max, self.yr_max = v_max, vz_max, math.radians(yaw_rate_max_dps)
        self.takeoff_alt = takeoff_alt
        self.takeoff_timeout = max(0.1, float(takeoff_timeout))
        self.offboard_rate_hz = max(2.1, float(offboard_rate_hz))
        self._time = time_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep
        self.m = None
        self._tel = Telemetry()
        self.flying = False
        self._last_gcs_heartbeat = -math.inf

    def connect(self) -> None:
        if "," in self.conn_str:
            dev, baud = self.conn_str.split(",", 1)
            self.m = self.mavutil.mavlink_connection(dev, baud=int(baud))
        else:
            self.m = self.mavutil.mavlink_connection(self.conn_str)
        self.m.wait_heartbeat(timeout=30)
        print(f"MAVLink heartbeat from system {self.m.target_system}")

    def _send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        self._send_gcs_heartbeat_if_due()
        self.m.mav.set_position_target_local_ned_send(
            int(self._time() * 1000) & 0xFFFFFFFF,
            self.m.target_system, self.m.target_component, self.mavutil.mavlink.MAV_FRAME_BODY_NED,
            TYPE_MASK_VEL_YAWRATE, 0, 0, 0, vx, vy, vz, 0, 0, 0, 0, yaw_rate)

    def _send_gcs_heartbeat_if_due(self) -> None:
        now = self._time()
        if now - self._last_gcs_heartbeat < 1.0:
            return
        self.m.mav.heartbeat_send(
            self.mavutil.mavlink.MAV_TYPE_GCS,
            self.mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            self.mavutil.mavlink.MAV_STATE_ACTIVE,
        )
        self._last_gcs_heartbeat = now

    def _prime_px4_offboard(self) -> None:
        period = 1.0 / self.offboard_rate_hz
        samples = max(20, math.ceil(self.offboard_rate_hz * 1.1))
        for _ in range(samples):
            self._send_velocity(0, 0, 0, 0)
            self._sleep(period)

    def _wait_armed(self, timeout: float = 10.0) -> None:
        """Wait for arming without relying on pymavlink's unbounded helper."""
        if not hasattr(self.m, "motors_armed"):
            self.m.motors_armed_wait()
            return
        deadline = self._time() + timeout
        period = 1.0 / self.offboard_rate_hz
        while not self.m.motors_armed():
            if self._time() >= deadline:
                raise TimeoutError(f"PX4 did not arm within {timeout:g} seconds")
            # PX4 exits OFFBOARD if setpoints stop for roughly half a second.
            # Keep both the GCS heartbeat and the neutral setpoint alive while
            # waiting for the next vehicle heartbeat to report the armed bit.
            self._send_velocity(0, 0, 0, 0)
            self.m.recv_match(type="HEARTBEAT", blocking=False)
            self._sleep(period)

    def _px4_takeoff(self) -> None:
        period = 1.0 / self.offboard_rate_hz
        self._prime_px4_offboard()
        self.m.set_mode("OFFBOARD")
        self.m.arducopter_arm()
        self._wait_armed(timeout=10)
        self.flying = True
        deadline = self._time() + self.takeoff_timeout
        while True:
            tel = self.telemetry()
            if tel.alt_m is not None and tel.alt_m >= self.takeoff_alt - 0.1:
                self._send_velocity(0, 0, 0, 0)
                return
            if self._time() >= deadline:
                self.land()
                raise TimeoutError(f"PX4 did not reach takeoff altitude {self.takeoff_alt:.2f} m")
            self._send_velocity(0, 0, -min(self.vz_max, 0.6), 0)
            self._sleep(period)

    def takeoff(self) -> None:
        m = self.m
        if self.autopilot == "px4":
            self._px4_takeoff()
            return
        else:
            m.set_mode("GUIDED")
            m.arducopter_arm()
            m.motors_armed_wait()
            m.mav.command_long_send(m.target_system, m.target_component, self.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                                    0, 0, 0, 0, 0, 0, 0, self.takeoff_alt)
            self._sleep(6)
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
        while True:
            msg = self.m.recv_match(type=["LOCAL_POSITION_NED", "ATTITUDE", "BATTERY_STATUS", "SYS_STATUS"], blocking=False)
            if msg is None:
                break
            k = msg.get_type()
            if k == "LOCAL_POSITION_NED":
                t.x_m, t.y_m, t.alt_m, t.vz_mps = msg.x, msg.y, -msg.z, -msg.vz
            elif k == "ATTITUDE":
                t.yaw_deg, t.yaw_rate_dps = math.degrees(msg.yaw), math.degrees(msg.yawspeed)
            elif k == "SYS_STATUS" and msg.battery_remaining >= 0:
                t.battery_pct = float(msg.battery_remaining)
            elif k == "BATTERY_STATUS" and msg.battery_remaining >= 0:
                t.battery_pct = float(msg.battery_remaining)
        t.t = self._time()
        t.flying = self.flying
        return t
