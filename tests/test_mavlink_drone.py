from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from flydrones.drones import mavlink as mavlink_module
from flydrones.drones.mavlink import MavlinkDrone, _decode_int32_parameter, _encode_int32_parameter
from flydrones.safety import Telemetry
from flydrones.takeoff_readiness import CommandAckEvidence, TakeoffFailureReason, TakeoffStage


class Message:
    def __init__(self, kind: str, **values):
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self):
        return self.kind


class HeaderMessage(Message):
    def __init__(self, kind: str, *, source_system: int, source_component: int, **values):
        super().__init__(kind, **values)
        self._source_system = source_system
        self._source_component = source_component

    def get_srcSystem(self):
        return self._source_system

    def get_srcComponent(self):
        return self._source_component


class Connection:
    def __init__(self, messages):
        self.messages = list(messages)
        self.arm_calls = 0
        self.disarm_calls = 0
        self.mode_calls = []

    def recv_match(self, **_kwargs):
        return self.messages.pop(0) if self.messages else None

    def arducopter_arm(self):
        self.arm_calls += 1

    def arducopter_disarm(self):
        self.disarm_calls += 1

    def set_mode(self, mode):
        self.mode_calls.append(mode)


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
    drone._unmatched_command_acks = []
    drone._command_acks = []
    drone.mavutil = SimpleNamespace(
        mavlink=SimpleNamespace(
            MAV_MODE_FLAG_SAFETY_ARMED=128,
            MAV_LANDED_STATE_ON_GROUND=1,
            MAV_LANDED_STATE_IN_AIR=2,
            MAV_RESULT_ACCEPTED=0,
            MAV_RESULT_IN_PROGRESS=5,
        )
    )
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
    acknowledgements = [
        Message("PARAM_VALUE", param_id=b"SYS_FAILURE_EN", param_value=_encode_int32_parameter(1))
    ]
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        param_set_send=lambda *args: parameter_sets.append(args),
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.enable_failure_injection(timeout_s=1.0)

    assert len(parameter_sets) == 1
    assert parameter_sets[0][0::2] == ("SYS_FAILURE_EN", 6)
    assert _decode_int32_parameter(parameter_sets[0][1]) == 1


def test_disabling_gps_fusion_waits_for_the_px4_parameter_echo(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 1.0)
    parameter_sets = []
    acknowledgements = [
        Message("PARAM_VALUE", param_id="EKF2_GPS_CTRL", param_value=_encode_int32_parameter(0))
    ]
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        param_set_send=lambda *args: parameter_sets.append(args),
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.disable_gps_fusion(timeout_s=1.0)

    assert len(parameter_sets) == 1
    assert parameter_sets[0][0::2] == ("EKF2_GPS_CTRL", 6)
    assert _decode_int32_parameter(parameter_sets[0][1]) == 0


def test_enabling_external_vision_fusion_uses_horizontal_position_and_velocity(monkeypatch):
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: 1.0)
    parameter_sets = []
    acknowledgements = [
        Message("PARAM_VALUE", param_id="EKF2_EV_CTRL", param_value=_encode_int32_parameter(5))
    ]
    drone = object.__new__(MavlinkDrone)
    drone.m = SimpleNamespace(
        param_set_send=lambda *args: parameter_sets.append(args),
        recv_match=lambda **_kwargs: acknowledgements.pop(0) if acknowledgements else None,
    )

    drone.enable_external_vision_fusion(timeout_s=1.0)

    assert len(parameter_sets) == 1
    assert parameter_sets[0][0::2] == ("EKF2_EV_CTRL", 6)
    assert _decode_int32_parameter(parameter_sets[0][1]) == 5


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


def test_ingest_tracks_armed_landed_and_offboard_status():
    drone = bare_drone([])

    drone._ingest_message(Message("HEARTBEAT", base_mode=128, custom_mode=6 << 16), received_at=2.0)
    drone._ingest_message(Message("EXTENDED_SYS_STATE", landed_state=2), received_at=2.1)

    assert drone._tel.armed is True
    assert drone._tel.landed is False
    assert drone._tel.navigation_state == 6
    assert drone._tel.offboard is True
    assert drone._tel.status_updated_at == 2.1


def test_wait_command_ack_ignores_unrelated_and_wrong_target_acks(monkeypatch):
    now = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        Message("COMMAND_ACK", command=22, result=0, target_system=3, target_component=1),
        Message("COMMAND_ACK", command=400, result=0, target_system=9, target_component=1),
        Message("COMMAND_ACK", command=400, result=0, target_system=3, target_component=1),
    ])
    drone.m.target_system = 3
    drone.m.target_component = 1

    acknowledgement = drone._wait_command_ack(400, timeout_s=1.0)

    assert acknowledgement.command == 400
    assert acknowledgement.target_system == 3
    assert len(drone._unmatched_command_acks) == 2


def test_wait_command_ack_matches_px4_header_source_and_local_payload_recipient(monkeypatch):
    now = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        HeaderMessage(
            "COMMAND_ACK", command=400, result=0,
            source_system=2, source_component=1,
            target_system=255, target_component=190,
        ),
        HeaderMessage(
            "COMMAND_ACK", command=400, result=0,
            source_system=1, source_component=1,
            target_system=9, target_component=190,
        ),
        HeaderMessage(
            "COMMAND_ACK", command=400, result=0,
            source_system=1, source_component=1,
            target_system=255, target_component=190,
        ),
    ])
    drone.m.target_system = 1
    drone.m.target_component = 1
    drone.m.source_system = 255
    drone.m.source_component = 190

    acknowledgement = drone._wait_command_ack(400, timeout_s=1.0)

    assert acknowledgement.source_system == 1
    assert acknowledgement.source_component == 1
    assert acknowledgement.target_system == 255
    assert acknowledgement.target_component == 190
    assert len(drone._unmatched_command_acks) == 2


def test_wait_command_ack_accepts_missing_mavlink2_target_extensions(monkeypatch):
    now = iter((0.0, 0.1))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        HeaderMessage(
            "COMMAND_ACK", command=22, result=0,
            source_system=1, source_component=1,
        ),
    ])
    drone.m.target_system = 1
    drone.m.target_component = 1
    drone.m.source_system = 255
    drone.m.source_component = 190

    acknowledgement = drone._wait_command_ack(22, timeout_s=1.0)

    assert acknowledgement.source_system == 1
    assert acknowledgement.target_system == 0
    assert acknowledgement.target_component == 0


def test_wait_command_ack_treats_connected_target_component_zero_as_wildcard(monkeypatch):
    now = iter((0.0, 0.1))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        HeaderMessage(
            "COMMAND_ACK", command=400, result=0,
            source_system=1, source_component=1,
            target_system=255, target_component=0,
        ),
    ])
    drone.m.target_system = 1
    drone.m.target_component = 0
    drone.m.source_system = 255
    drone.m.source_component = 0

    acknowledgement = drone._wait_command_ack(400, timeout_s=1.0)

    assert acknowledgement.source_component == 1
    assert acknowledgement.target_system == 255


def test_wait_command_ack_accepts_in_progress_only_after_final_result(monkeypatch):
    now = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        Message("COMMAND_ACK", command=22, result=5, progress=40, target_system=3, target_component=1),
        Message("COMMAND_ACK", command=22, result=0, progress=100, target_system=3, target_component=1),
    ])
    drone.m.target_system = 3
    drone.m.target_component = 1

    acknowledgement = drone._wait_command_ack(22, timeout_s=1.0)

    assert acknowledgement.result == 0
    assert acknowledgement.progress == 100


def test_wait_command_ack_returns_a_matching_rejection(monkeypatch):
    now = iter((0.0, 0.1))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([Message("COMMAND_ACK", command=22, result=4, target_system=3, target_component=1)])
    drone.m.target_system = 3
    drone.m.target_component = 1

    acknowledgement = drone._wait_command_ack(22, timeout_s=1.0)

    assert acknowledgement.result == 4


def test_wait_command_ack_has_a_hard_timeout(monkeypatch):
    now = iter((0.0, 0.2))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([])
    drone.m.target_system = 3
    drone.m.target_component = 1

    with pytest.raises(TimeoutError, match="command 22"):
        drone._wait_command_ack(22, timeout_s=0.1)


def test_ack_wait_ingests_interleaved_position_and_status(monkeypatch):
    now = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        Message("LOCAL_POSITION_NED", x=1.0, y=2.0, z=-0.7, vz=-0.1),
        Message("HEARTBEAT", base_mode=128, custom_mode=6 << 16),
        Message("COMMAND_ACK", command=22, result=0, target_system=3, target_component=1),
    ])
    drone.m.target_system = 3
    drone.m.target_component = 1

    acknowledgement = drone._wait_command_ack(22, timeout_s=1.0)

    assert acknowledgement.result == 0
    assert drone._tel.alt_m == 0.7
    assert drone._tel.position_updated_at == 0.1
    assert drone._tel.offboard is True
    assert drone._tel.status_updated_at == 0.2


def test_ack_wait_calls_keepalive_while_ingesting_interleaved_messages(monkeypatch):
    now = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(mavlink_module.time, "monotonic", lambda: next(now))
    drone = bare_drone([
        Message("LOCAL_POSITION_NED", x=1.0, y=2.0, z=-0.7, vz=-0.1),
        Message("COMMAND_ACK", command=176, result=0, target_system=3, target_component=1),
    ])
    drone.m.target_system = 3
    drone.m.target_component = 1
    keepalive_calls = []

    acknowledgement = drone._wait_command_ack(
        176,
        timeout_s=1.0,
        keepalive=lambda: keepalive_calls.append(True),
    )

    assert acknowledgement.result == 0
    assert keepalive_calls


def test_ack_wait_drains_a_queued_telemetry_burst_before_the_deadline(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(mavlink_module.time, "monotonic", clock.monotonic)

    class BackloggedConnection(Connection):
        def recv_match(self, **kwargs):
            if kwargs.get("blocking"):
                clock.now += 0.2
            return super().recv_match(**kwargs)

    messages = [
        Message("LOCAL_POSITION_NED", x=float(index), y=2.0, z=-0.7, vz=-0.1)
        for index in range(20)
    ]
    messages.append(Message("COMMAND_ACK", command=22, result=0, target_system=3, target_component=1))
    drone = bare_drone([])
    drone.m = BackloggedConnection(messages)
    drone.m.mav = MavSender()
    drone.m.target_system = 3
    drone.m.target_component = 1

    acknowledgement = drone._wait_command_ack(22, timeout_s=1.0)

    assert acknowledgement.result == 0
    assert drone._tel.x_m == 19.0
    assert clock.now == pytest.approx(0.2)


def test_ack_wait_limits_each_nonblocking_queue_drain(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(mavlink_module.time, "monotonic", clock.monotonic)

    class EndlessConnection(Connection):
        def __init__(self):
            super().__init__([])
            self.nonblocking_since_wait = 0
            self.maximum_nonblocking = 0

        def recv_match(self, **kwargs):
            if kwargs.get("blocking"):
                self.maximum_nonblocking = max(self.maximum_nonblocking, self.nonblocking_since_wait)
                self.nonblocking_since_wait = 0
                clock.now += 0.6
            else:
                self.nonblocking_since_wait += 1
            return Message("HEARTBEAT", base_mode=128, custom_mode=4 << 16)

    drone = bare_drone([])
    drone.m = EndlessConnection()
    drone.m.mav = MavSender()
    drone.m.target_system = 3
    drone.m.target_component = 1

    with pytest.raises(TimeoutError, match="command 22"):
        drone._wait_command_ack(22, timeout_s=1.0)

    assert drone.m.maximum_nonblocking <= mavlink_module.ACK_BURST_LIMIT


def test_ingest_does_not_refresh_sensor_timestamps_without_sensor_messages():
    drone = bare_drone([])
    drone._tel.position_updated_at = 1.0
    drone._tel.attitude_updated_at = 1.1
    drone._tel.estimator_updated_at = 1.2

    drone._ingest_message(Message("HEARTBEAT", base_mode=0, custom_mode=0), received_at=5.0)

    assert drone._tel.position_updated_at == 1.0
    assert drone._tel.attitude_updated_at == 1.1
    assert drone._tel.estimator_updated_at == 1.2
    assert drone._tel.status_updated_at == 5.0


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


def transactional_drone(monkeypatch, telemetry_fn, ack_results=None):
    clock = FakeClock()
    monkeypatch.setattr(mavlink_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mavlink_module.time, "sleep", clock.sleep)
    drone = bare_drone([])
    drone.flying = False
    drone.autopilot = "px4"
    drone.offboard_rate_hz = 2.0
    drone.arm_timeout_s = 1.0
    drone.takeoff_alt = 1.5
    drone.m.target_system = 3
    drone.m.target_component = 1
    drone.m.motors_armed = lambda: bool(drone._tel.armed)
    drone.mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM = 400
    drone.mavutil.mavlink.MAV_CMD_NAV_TAKEOFF = 22
    drone.mavutil.mavlink.MAV_CMD_DO_SET_MODE = 176
    drone.mavutil.mavlink.MAV_CMD_NAV_LAND = 21
    drone.mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
    drone.mavutil.mavlink.MAV_FRAME_BODY_NED = 8
    results = {400: 0, 22: 0, 176: 0, 21: 0}
    results.update(ack_results or {})
    requested_commands = []

    def wait_ack(command, *, timeout_s, keepalive=None):
        requested_commands.append(command)
        if keepalive is not None:
            keepalive()
        return CommandAckEvidence(command, results[command], 3, 1, clock.now)

    drone._wait_command_ack = wait_ack

    def wait_until_armed(*, timeout_s):
        drone._tel.armed = True
        clock.sleep(0.1)

    drone._wait_until_armed = wait_until_armed
    drone.telemetry = lambda: telemetry_fn(clock, drone)
    return drone, clock, requested_commands


def landing_drone(monkeypatch, telemetry_fn):
    clock = FakeClock()
    monkeypatch.setattr(mavlink_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mavlink_module.time, "sleep", clock.sleep)
    drone = bare_drone([])
    drone.autopilot = "px4"
    drone.m.target_system = 3
    drone.m.target_component = 1
    drone.mavutil.mavlink.MAV_CMD_NAV_LAND = 21
    drone.telemetry = lambda: telemetry_fn(clock, drone)
    return drone, clock


def test_px4_land_waits_for_landed_then_disarms_and_confirms_disarmed(monkeypatch):
    disarm_times = []

    def telemetry(clock, drone):
        if drone.m.disarm_calls:
            return status_sample(clock.now, altitude=0.04, sequence=4, armed=False, landed=True)
        if clock.now < 0.2:
            return status_sample(clock.now, altitude=0.04, sequence=2, armed=True, landed=False)
        return status_sample(clock.now, altitude=0.04, sequence=3, armed=True, landed=True)

    drone, clock = landing_drone(monkeypatch, telemetry)
    original_disarm = drone.m.arducopter_disarm

    def record_disarm():
        disarm_times.append(clock.now)
        original_disarm()

    drone.m.arducopter_disarm = record_disarm

    drone.land(timeout_s=0.5)

    assert any(command[2] == 21 for command in drone.m.mav.commands)
    assert disarm_times == [pytest.approx(0.2)]
    assert drone.m.disarm_calls == 1
    assert drone.flying is False


def test_px4_land_times_out_without_landed_confirmation_and_does_not_disarm(monkeypatch):
    drone, _clock = landing_drone(
        monkeypatch,
        lambda clock, _drone: status_sample(
            clock.now, altitude=0.02, sequence=1, armed=True, landed=False
        ),
    )

    with pytest.raises(TimeoutError, match="landed state"):
        drone.land(timeout_s=0.3)

    assert drone.m.disarm_calls == 0
    assert drone.flying is False


def test_px4_land_times_out_without_disarm_confirmation(monkeypatch):
    drone, _clock = landing_drone(
        monkeypatch,
        lambda clock, _drone: status_sample(
            clock.now, altitude=0.02, sequence=1, armed=True, landed=True
        ),
    )

    with pytest.raises(TimeoutError, match="disarmed state"):
        drone.land(timeout_s=0.3)

    assert drone.m.disarm_calls == 1
    assert drone.flying is False


def telemetry_sequence(samples):
    remaining = list(samples)
    last = remaining[-1]

    def read(_clock, _drone):
        nonlocal last
        if remaining:
            last = remaining.pop(0)
        return last

    return read


def status_sample(clock, *, altitude, sequence, armed=True, landed=False, offboard=False):
    return Telemetry(
        t=clock,
        alt_m=altitude,
        position_updated_at=float(sequence),
        status_updated_at=float(sequence),
        position_valid=True,
        estimator_healthy=True,
        armed=armed,
        landed=landed,
        navigation_state=6 if offboard else 4,
        offboard=offboard,
    )


def test_takeoff_requires_three_fresh_climb_samples_and_offboard_confirmation(monkeypatch):
    observed_flying = []
    samples = [
        status_sample(0.0, altitude=0.0, sequence=0, armed=False, landed=True),
        status_sample(0.1, altitude=0.0, sequence=1, armed=True, landed=True),
        status_sample(0.2, altitude=0.55, sequence=2),
        status_sample(0.3, altitude=0.65, sequence=3),
        status_sample(0.4, altitude=0.75, sequence=4),
        status_sample(2.0, altitude=0.75, sequence=5, offboard=True),
    ]
    sequence = telemetry_sequence(samples)

    def telemetry(clock, drone):
        observed_flying.append(drone.flying)
        return sequence(clock, drone)

    drone, _clock, requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert evidence.accepted
    assert evidence.terminal_stage is TakeoffStage.MISSION_READY
    assert evidence.maximum_altitude_gain_m == pytest.approx(0.75)
    assert requested == [400, 22, 176]
    assert observed_flying and not any(observed_flying)
    assert drone.flying is True
    assert len(drone.m.mav.setpoints) >= 5


def test_offboard_priming_drains_telemetry_between_setpoints(monkeypatch):
    samples = [
        status_sample(0.0, altitude=0.0, sequence=0, armed=False, landed=True),
        status_sample(0.1, altitude=0.0, sequence=1, armed=True, landed=True),
        status_sample(0.2, altitude=0.55, sequence=2),
        status_sample(0.3, altitude=0.65, sequence=3),
        status_sample(0.4, altitude=0.75, sequence=4),
        status_sample(2.0, altitude=0.75, sequence=5, offboard=True),
    ]
    sequence = telemetry_sequence(samples)
    telemetry_calls = 0

    def telemetry(clock, drone):
        nonlocal telemetry_calls
        telemetry_calls += 1
        return sequence(clock, drone)

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)
    setpoint_telemetry_counts = []
    original_send_velocity = drone._send_velocity

    def send_velocity(*args):
        setpoint_telemetry_counts.append(telemetry_calls)
        original_send_velocity(*args)

    drone._send_velocity = send_velocity

    evidence = drone.takeoff()

    assert evidence.accepted
    assert all(
        later > earlier
        for earlier, later in zip(
            setpoint_telemetry_counts[:3], setpoint_telemetry_counts[1:3]
        )
    )


def test_takeoff_streams_setpoints_until_delayed_offboard_state_is_observed(monkeypatch):
    reads = 0

    def telemetry(clock, drone):
        nonlocal reads
        reads += 1
        if reads == 1:
            return status_sample(clock.now, altitude=0.0, sequence=reads, armed=False, landed=True)
        if reads == 2:
            return status_sample(clock.now, altitude=0.0, sequence=reads, armed=True, landed=True)
        altitude = min(0.75, 0.45 + reads * 0.05)
        return status_sample(
            clock.now,
            altitude=altitude,
            sequence=reads,
            offboard=bool(drone.m.mode_calls) and len(drone.m.mav.setpoints) >= 7,
        )

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert evidence.accepted
    # Three priming setpoints, one ACK keepalive, and three state-poll holds.
    assert len(drone.m.mav.setpoints) >= 7


def test_offboard_state_timeout_keeps_streaming_then_fails_closed(monkeypatch):
    def telemetry(clock, drone):
        landing_requested = any(command[2] == 21 for command in drone.m.mav.commands)
        if landing_requested:
            return status_sample(clock.now, altitude=0.0, sequence=99, armed=False, landed=True)
        if clock.now == 0.0:
            return status_sample(clock.now, altitude=0.0, sequence=0, armed=False, landed=True)
        if clock.now < 0.2:
            return status_sample(clock.now, altitude=0.0, sequence=1, armed=True, landed=True)
        return status_sample(
            clock.now,
            altitude=0.75,
            sequence=int(clock.now * 10) + 2,
            offboard=False,
        )

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert not evidence.accepted
    assert evidence.failure_reason is TakeoffFailureReason.OFFBOARD_STATE_TIMEOUT
    assert len(drone.m.mav.setpoints) >= 10
    assert any(command[2] == 21 for command in drone.m.mav.commands)
    assert drone.flying is False


def test_one_altitude_spike_does_not_confirm_takeoff(monkeypatch):
    def telemetry(clock, drone):
        if clock.now == 0.0:
            return status_sample(clock.now, altitude=0.0, sequence=0, armed=False, landed=True)
        if drone.m.arm_calls and clock.now < 0.5:
            return status_sample(clock.now, altitude=0.0, sequence=1, armed=True, landed=True)
        if clock.now < 1.0:
            return status_sample(clock.now, altitude=0.7, sequence=2)
        landed = any(command[2] == 21 for command in drone.m.mav.commands)
        return status_sample(clock.now, altitude=0.1, sequence=int(clock.now * 10) + 3, landed=landed)

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert not evidence.accepted
    assert evidence.failure_reason is TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT
    assert drone.m.arm_calls == 1
    assert sum(command[2] == 22 for command in drone.m.mav.commands) == 1
    assert drone.flying is False


def test_climb_samples_without_confirmed_not_landed_state_do_not_pass(monkeypatch):
    samples = [
        status_sample(0.0, altitude=0.0, sequence=0, armed=False, landed=True),
        status_sample(0.1, altitude=0.0, sequence=1, armed=True, landed=True),
        status_sample(0.2, altitude=0.6, sequence=2, landed=None),
        status_sample(0.3, altitude=0.7, sequence=3, landed=None),
        status_sample(0.4, altitude=0.8, sequence=4, landed=None),
        status_sample(2.0, altitude=0.8, sequence=5, landed=None, offboard=True),
    ]
    sequence = telemetry_sequence(samples)

    def telemetry(clock, drone):
        if any(command[2] == 21 for command in drone.m.mav.commands):
            return status_sample(clock.now, altitude=0.0, sequence=99, armed=False, landed=True)
        return sequence(clock, drone)

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert not evidence.accepted
    assert evidence.failure_reason is TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT


def test_accepted_commands_with_stationary_altitude_fail_and_do_not_retry(monkeypatch):
    def telemetry(clock, drone):
        if clock.now == 0.0:
            return status_sample(clock.now, altitude=0.0, sequence=0, armed=False, landed=True)
        landed = any(command[2] == 21 for command in drone.m.mav.commands)
        return status_sample(
            clock.now,
            altitude=0.02,
            sequence=int(clock.now * 10) + 1,
            armed=not landed,
            landed=landed,
        )

    drone, _clock, requested = transactional_drone(monkeypatch, telemetry)

    evidence = drone.takeoff()

    assert evidence.failure_reason is TakeoffFailureReason.ACTUATOR_RESPONSE_TIMEOUT
    assert requested.count(400) == 1
    assert requested.count(22) == 1
    assert drone.m.arm_calls == 1
    assert drone.m.disarm_calls == 1


def test_offboard_rejection_fails_after_climb_and_requests_safe_landing(monkeypatch):
    samples = [
        status_sample(0.0, altitude=0.0, sequence=0, armed=False, landed=True),
        status_sample(0.1, altitude=0.0, sequence=1, armed=True, landed=True),
        status_sample(0.2, altitude=0.6, sequence=2),
        status_sample(0.3, altitude=0.7, sequence=3),
        status_sample(0.4, altitude=0.8, sequence=4),
    ]
    sequence = telemetry_sequence(samples)
    post_disarm_reads = []

    def telemetry(clock, drone):
        if any(command[2] == 21 for command in drone.m.mav.commands):
            if drone.m.disarm_calls:
                post_disarm_reads.append(clock.now)
                return status_sample(clock.now, altitude=0.0, sequence=100, armed=False, landed=True)
            return status_sample(clock.now, altitude=0.0, sequence=99, armed=True, landed=True)
        return sequence(clock, drone)

    drone, _clock, requested = transactional_drone(monkeypatch, telemetry, {176: 4})

    evidence = drone.takeoff()

    assert not evidence.accepted
    assert evidence.failure_reason is TakeoffFailureReason.OFFBOARD_COMMAND_REJECTED
    assert requested == [400, 22, 176]
    assert any(command[2] == 21 for command in drone.m.mav.commands)
    assert drone.m.disarm_calls == 1
    assert post_disarm_reads
    assert evidence.cleanup_failure is None


def test_offboard_ack_timeout_is_distinct_from_an_explicit_rejection(monkeypatch):
    samples = [
        status_sample(0.0, altitude=0.0, sequence=0, armed=False, landed=True),
        status_sample(0.1, altitude=0.0, sequence=1, armed=True, landed=True),
        status_sample(0.2, altitude=0.6, sequence=2),
        status_sample(0.3, altitude=0.7, sequence=3),
        status_sample(0.4, altitude=0.8, sequence=4),
    ]
    sequence = telemetry_sequence(samples)

    def telemetry(clock, drone):
        if any(command[2] == 21 for command in drone.m.mav.commands):
            return status_sample(clock.now, altitude=0.0, sequence=99, armed=False, landed=True)
        return sequence(clock, drone)

    drone, _clock, _requested = transactional_drone(monkeypatch, telemetry)
    original_wait = drone._wait_command_ack

    def wait_ack(command, *, timeout_s, keepalive=None):
        if command == 176:
            raise TimeoutError("queued ACK was not observed")
        return original_wait(command, timeout_s=timeout_s, keepalive=keepalive)

    drone._wait_command_ack = wait_ack

    evidence = drone.takeoff()

    assert not evidence.accepted
    assert evidence.failure_reason is TakeoffFailureReason.OFFBOARD_COMMAND_TIMEOUT
    assert evidence.cleanup_failure is None
