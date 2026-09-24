from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from flydrones.drones import mavlink as mavlink_module
from flydrones.drones.mavlink import MavlinkDrone
from flydrones.safety import Telemetry


class Message:
    def __init__(self, kind: str, **values):
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self):
        return self.kind


class Connection:
    def __init__(self, messages):
        self.messages = list(messages)

    def recv_match(self, **_kwargs):
        return self.messages.pop(0) if self.messages else None


class MavSender:
    def __init__(self):
        self.heartbeats = []
        self.setpoints = []
        self.commands = []

    def heartbeat_send(self, *args):
        self.heartbeats.append(args)

    def set_position_target_local_ned_send(self, *args):
        self.setpoints.append(args)

    def command_long_send(self, *args):
        self.commands.append(args)


def bare_drone(messages) -> MavlinkDrone:
    drone = object.__new__(MavlinkDrone)
    drone.m = Connection(messages)
    drone.m.mav = MavSender()
    drone._tel = Telemetry()
    drone.flying = True
    drone._last_controller_heartbeat_at = float("-inf")
    return drone


def test_constructor_accepts_the_offboard_stream_rate_used_by_px4_workers():
    assert "offboard_rate_hz" in inspect.signature(MavlinkDrone).parameters
    assert "arm_timeout_s" in inspect.signature(MavlinkDrone).parameters


def test_local_controller_sends_a_rate_limited_px4_gcs_heartbeat():
    drone = object.__new__(MavlinkDrone)
    sender = MavSender()
    drone.m = SimpleNamespace(mav=sender)
    drone._last_controller_heartbeat_at = float("-inf")

    drone._send_controller_heartbeat(3.0)
    drone._send_controller_heartbeat(3.5)
    drone._send_controller_heartbeat(4.01)

    assert len(sender.heartbeats) == 2
    assert sender.heartbeats[0] == (6, 8, 0, 0, 4)


def test_px4_arm_wait_has_a_hard_timeout(monkeypatch):
    now = iter((0.0, 0.2))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        recv_match=lambda **_kwargs: None,
        motors_armed=lambda: False,
        mav=MavSender(),
    )
    drone._last_controller_heartbeat_at = 0.0

    with pytest.raises(TimeoutError, match="did not arm"):
        drone._wait_until_armed(timeout_s=0.1)


def test_velocity_setpoint_uses_the_px4_supported_body_ned_frame():
    drone = object.__new__(MavlinkDrone)
    sender = MavSender()
    drone.m = SimpleNamespace(mav=sender, target_system=1, target_component=1)
    drone.mavutil = SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_BODY_NED=8))

    drone._send_velocity(1.0, 2.0, -0.5, 0.1)

    assert sender.setpoints[0][3] == 8


@pytest.mark.parametrize("mode,failure_type", [("off", 1), ("stuck", 2), ("wrong", 4), ("ok", 0)])
def test_gps_failure_injection_uses_the_standard_mavlink_command(monkeypatch, mode, failure_type):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 1.0)
    drone = object.__new__(MavlinkDrone)
    sender = MavSender()
    acknowledgements = [Message("COMMAND_ACK", command=420, result=0)]
    drone.m = SimpleNamespace(
        mav=sender,
        target_system=3,
        target_component=1,
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.inject_gps_failure(mode, timeout_s=1.0)

    command = sender.commands[0]
    assert command[:4] == (3, 1, 420, 0)
    assert command[4:7] == (4, failure_type, 0)


def test_gps_failure_injection_rejects_unknown_modes():
    drone = object.__new__(MavlinkDrone)
    with pytest.raises(ValueError, match="GPS failure mode"):
        drone.inject_gps_failure("drift")


def test_enabling_failure_injection_waits_for_the_px4_parameter_echo(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 1.0)
    parameter_sets = []
    acknowledgements = [Message("PARAM_VALUE", param_id=b"SYS_FAILURE_EN", param_value=1.0)]
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        param_set_send=lambda *args: parameter_sets.append(args),
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.enable_failure_injection(timeout_s=1.0)

    assert parameter_sets == [("SYS_FAILURE_EN", 1, 6)]


def test_disabling_gps_fusion_waits_for_the_px4_parameter_echo(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 1.0)
    parameter_sets = []
    acknowledgements = [Message("PARAM_VALUE", param_id="EKF2_GPS_CTRL", param_value=0.0)]
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        param_set_send=lambda *args: parameter_sets.append(args),
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.disable_gps_fusion(timeout_s=1.0)

    assert parameter_sets == [("EKF2_GPS_CTRL", 0, 6)]


def test_mavlink_telemetry_records_sensor_receipt_times_and_validity(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 12.5)
    drone = bare_drone([
        Message("LOCAL_POSITION_NED", x=1.0, y=-2.0, z=-1.8, vz=-0.2),
        Message("ATTITUDE", yaw=0.5, yawspeed=0.1),
        Message("ESTIMATOR_STATUS", flags=47),
    ])

    telemetry = drone.telemetry()

    assert telemetry.position_updated_at == 12.5
    assert telemetry.attitude_updated_at == 12.5
    assert telemetry.estimator_updated_at == 12.5
    assert telemetry.position_valid is True
    assert telemetry.attitude_valid is True
    assert telemetry.estimator_healthy is True
    assert telemetry.x_m == 1.0
    assert telemetry.alt_m == 1.8
    assert telemetry.yaw_deg == pytest.approx(28.6478898)


def test_reading_an_old_mavlink_snapshot_does_not_refresh_sensor_timestamps(monkeypatch):
    now = iter((4.0, 8.0))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        Message("LOCAL_POSITION_NED", x=0.0, y=0.0, z=-1.0, vz=0.0),
        Message("ATTITUDE", yaw=0.0, yawspeed=0.0),
        Message("ESTIMATOR_STATUS", flags=47),
    ])

    first = drone.telemetry()
    first_position_update = first.position_updated_at
    second = drone.telemetry()

    assert first_position_update == 4.0
    assert second.position_updated_at == 4.0
    assert second.t == 8.0


def test_mavlink_marks_estimator_unhealthy_when_a_required_solution_flag_is_missing(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 3.0)
    drone = bare_drone([Message("ESTIMATOR_STATUS", flags=47 & ~8)])

    telemetry = drone.telemetry()

    assert telemetry.estimator_updated_at == 3.0
    assert telemetry.estimator_healthy is False


def test_mavlink_marks_non_finite_pose_invalid(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 2.0)
    drone = bare_drone([
        Message("LOCAL_POSITION_NED", x=float("nan"), y=0.0, z=-1.0, vz=0.0),
        Message("ATTITUDE", yaw=0.0, yawspeed=0.0),
    ])

    telemetry = drone.telemetry()

    assert telemetry.position_valid is False
