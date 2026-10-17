"""PX4 position-source safety checks without a MAVLink socket or airframe."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flydrones.drones.mavlink import MavlinkDrone
from flydrones.motor.command import FlightCommand
from flydrones.runtime import run_realtime
from flydrones.sitl_swarm import run_px4_swarm_trial


class Clock:
    now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Link:
    target_system = 1
    target_component = 1

    def __init__(self):
        self.messages = []
        self.velocity = []
        self.commands = []
        self.modes = []
        self.arm_calls = 0
        self.closed = False
        self.mav = SimpleNamespace(
            set_position_target_local_ned_send=lambda *args: self.velocity.append(args),
            heartbeat_send=lambda *args: None,
            command_long_send=lambda *args: self.commands.append(args),
        )

    def recv_match(self, **_kwargs):
        return self.messages.pop(0) if self.messages else None

    def set_mode(self, mode):
        self.modes.append(mode)

    def arducopter_arm(self):
        self.arm_calls += 1

    def motors_armed(self):
        return True

    def wait_heartbeat(self, **_kwargs):
        return None

    def close(self):
        self.closed = True


def position(boot_ms, *, x=0.0, system=1):
    return SimpleNamespace(
        get_type=lambda: "LOCAL_POSITION_NED", time_boot_ms=boot_ms,
        get_srcSystem=lambda: system, get_srcComponent=lambda: 1,
        x=x, y=0.0, z=-1.0, vx=0.0, vy=0.0, vz=0.0,
    )


def drone(autopilot="px4"):
    clock = Clock()
    link = Link()
    mavutil = SimpleNamespace(mavlink=SimpleNamespace(
        MAV_FRAME_BODY_NED=8, MAV_TYPE_GCS=6, MAV_AUTOPILOT_INVALID=8,
        MAV_STATE_ACTIVE=4, MAV_CMD_NAV_LAND=21,
    ))
    vehicle = MavlinkDrone(
        autopilot=autopilot, mavutil_module=mavutil,
        time_fn=clock.time, sleep_fn=clock.sleep,
    )
    vehicle.m = link
    return vehicle, clock, link


def test_px4_rejects_movement_without_a_fresh_position_and_stops_after_loss():
    vehicle, clock, link = drone()
    with pytest.raises(RuntimeError, match="position"):
        vehicle.send(FlightCommand(forward=0.5))
    assert not link.velocity
    # A refused session must be explicitly reconnected before reuse.
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    vehicle.flying = True
    vehicle.send(FlightCommand(forward=0.5))
    assert link.velocity[-1][8] == 0.5
    clock.now = 0.51
    # A control-loop timestamp advances; the source sample does not.
    with pytest.raises(RuntimeError, match="position"):
        vehicle.telemetry()
    assert link.velocity[-1][8:11] == (0, 0, 0)
    assert len(link.commands) == 1
    assert vehicle.flying is False


def test_duplicate_boot_timestamp_does_not_refresh_position_age():
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    clock.now = 0.4
    link.messages.append(position(100, x=500.0))
    assert vehicle.telemetry().x_m == 0.0
    clock.now = 0.51
    with pytest.raises(RuntimeError, match="position"):
        vehicle.send(FlightCommand(forward=0.2))


def test_stale_source_refuses_even_neutral_offboard_setpoint():
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    vehicle.flying = True
    clock.now = 0.51
    with pytest.raises(RuntimeError, match="stale LOCAL_POSITION_NED"):
        vehicle.send(FlightCommand.hover())
    assert link.velocity[-1][8:11] == (0, 0, 0)
    assert len(link.commands) == 1


def test_wrong_system_cannot_replace_px4_position_source():
    vehicle, _clock, link = drone()
    link.messages.append(position(100, system=2))
    with pytest.raises(RuntimeError, match="wrong or unknown position source"):
        vehicle.telemetry()
    link.messages.append(position(101))
    with pytest.raises(RuntimeError, match="wrong or unknown position source"):
        vehicle.telemetry()
    with pytest.raises(RuntimeError, match="wrong or unknown position source"):
        vehicle.send(FlightCommand(forward=0.2))
    assert not link.velocity


@pytest.mark.parametrize("bad", [position(99), position(101, x=float("nan")), position(101, x=10 ** 1000)])
def test_regressed_or_invalid_position_latches_refusal(bad):
    vehicle, _clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    link.messages.append(bad)
    with pytest.raises(RuntimeError, match="position"):
        vehicle.telemetry()
    link.messages.append(position(102))
    with pytest.raises(RuntimeError, match="position"):
        vehicle.telemetry()
    with pytest.raises(RuntimeError, match="position"):
        vehicle.send(FlightCommand(forward=0.2))
    assert not link.velocity


def test_px4_does_not_switch_offboard_or_arm_without_position_source():
    vehicle, _clock, link = drone()
    with pytest.raises(RuntimeError, match="position"):
        vehicle.takeoff()
    assert not link.modes
    assert link.arm_calls == 0


def test_ardupilot_path_does_not_inherit_px4_position_requirement():
    vehicle, _clock, link = drone("ardupilot")
    vehicle.send(FlightCommand(forward=0.2))
    assert link.velocity[-1][8] == 0.2


@pytest.mark.parametrize("bad_clock", [9.0, float("nan")])
def test_increasing_source_cannot_hide_invalid_decode_clock(bad_clock):
    vehicle, clock, link = drone()
    clock.now = 10.0
    link.messages.append(position(100))
    vehicle.telemetry()
    clock.now = bad_clock
    link.messages.append(position(101))
    with pytest.raises(RuntimeError, match="clock"):
        vehicle.telemetry()
    clock.now = 9.1 if bad_clock == 9.0 else 10.1
    with pytest.raises(RuntimeError, match="clock"):
        vehicle.send(FlightCommand(forward=0.2))
    assert not link.velocity


def test_expired_observation_cannot_be_revived_by_late_progress():
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    clock.now = 0.51
    link.messages.append(position(101))
    with pytest.raises(RuntimeError, match="stale LOCAL_POSITION_NED"):
        vehicle.telemetry()
    with pytest.raises(RuntimeError, match="stale LOCAL_POSITION_NED"):
        vehicle.send(FlightCommand(forward=0.2))
    assert not link.velocity


def test_public_send_consumes_live_position_stream_during_hover():
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    vehicle.flying = True
    for index in range(30):
        link.messages.append(position(101 + index))
        vehicle.send(FlightCommand.hover())
        clock.sleep(0.05)
    assert vehicle.flying
    assert not link.messages
    assert not link.commands


def test_coordinated_startup_checks_all_position_sources_before_any_arm():
    clock = Clock()
    links = []

    def factory(**_kwargs):
        vehicle, _unused_clock, link = drone()
        vehicle._time = clock.time
        vehicle._sleep = clock.sleep
        vehicle.connect = lambda: None
        links.append(link)
        return vehicle

    with pytest.raises(RuntimeError, match="position"):
        run_px4_swarm_trial(drone_factory=factory, time_fn=clock.time, sleep_fn=clock.sleep)
    assert all(not link.modes and link.arm_calls == 0 for link in links)


def test_land_is_attempted_if_neutral_stop_send_fails(monkeypatch):
    vehicle, clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    vehicle.flying = True
    clock.now = 0.51

    def broken_send(*_args):
        raise OSError("neutral send failed")

    monkeypatch.setattr(link.mav, "set_position_target_local_ned_send", broken_send)
    with pytest.raises(OSError, match="neutral send failed"):
        vehicle.send(FlightCommand(forward=0.2))
    assert len(link.commands) == 1


def test_arm_wait_failure_attempts_land(monkeypatch):
    vehicle, _clock, link = drone()
    link.messages.append(position(100))
    vehicle.telemetry()
    monkeypatch.setattr(vehicle, "_prime_px4_offboard", lambda: None)

    def broken_wait(*_args, **_kwargs):
        raise RuntimeError("arm wait failed")

    monkeypatch.setattr(vehicle, "_wait_armed", broken_wait)
    with pytest.raises(RuntimeError, match="arm wait failed"):
        vehicle.takeoff()
    assert link.arm_calls == 1
    assert len(link.commands) == 1


def test_backend_close_closes_actual_mavlink_connection():
    vehicle, _clock, link = drone()
    vehicle.close()
    assert link.closed


def test_explicit_reconnect_closes_old_link_and_clears_cached_session():
    vehicle, clock, old_link = drone()
    old_link.messages.append(position(100))
    vehicle.telemetry()
    clock.now = 0.51
    with pytest.raises(RuntimeError, match="stale"):
        vehicle.telemetry()
    new_link = Link()
    vehicle.mavutil.mavlink_connection = lambda *_args, **_kwargs: new_link
    vehicle.connect()
    assert old_link.closed
    assert vehicle.telemetry().x_m is None
    new_link.messages.append(position(1, x=3.0))
    vehicle.send(FlightCommand(forward=0.2))
    assert new_link.velocity[-1][8] == 0.2
    assert vehicle.telemetry().x_m == 3.0


def test_active_flight_cannot_reset_guard_by_reconnecting():
    vehicle, _clock, link = drone()
    vehicle.flying = True
    vehicle.mavutil.mavlink_connection = lambda *_args, **_kwargs: Link()
    with pytest.raises(RuntimeError, match="active"):
        vehicle.connect()
    assert vehicle.m is link
    assert not link.closed


def test_bounded_armed_check_is_required(monkeypatch):
    vehicle, _clock, link = drone()
    monkeypatch.setattr(link, "motors_armed", None)
    with pytest.raises(RuntimeError, match="bounded armed-status"):
        vehicle._wait_armed()


@pytest.mark.parametrize("failing_cleanup", ["send", "land"])
def test_realtime_cleanup_always_attempts_land_and_close(failing_cleanup):
    calls = []

    def call(name):
        calls.append(name)
        if name == failing_cleanup:
            raise OSError(f"cleanup {name} failed")

    vehicle = SimpleNamespace(
        connect=lambda: call("connect"), send=lambda _cmd: call("send"),
        land=lambda: call("land"), close=lambda: call("close"),
    )
    pilot = SimpleNamespace(
        drone=vehicle, decoder=SimpleNamespace(settle_s=0.0),
        cfg={"control": {"takeoff": False}}, warmup=lambda *_args: None,
    )
    with pytest.raises(OSError, match=f"cleanup {failing_cleanup} failed"):
        run_realtime(pilot, seconds=0)
    assert calls == ["connect", "send", "land", "close"]


def test_realtime_cleanup_preserves_primary_failure(capsys):
    calls = []

    def broken_stop(_cmd):
        calls.append("send")
        raise OSError("stop failure")

    def broken_warmup(*_args):
        raise ValueError("primary warmup failure")

    vehicle = SimpleNamespace(
        connect=lambda: calls.append("connect"), send=broken_stop,
        land=lambda: calls.append("land"), close=lambda: calls.append("close"),
    )
    pilot = SimpleNamespace(drone=vehicle, decoder=SimpleNamespace(settle_s=0), warmup=broken_warmup)
    with pytest.raises(ValueError, match="primary warmup failure"):
        run_realtime(pilot, seconds=0)
    assert calls == ["connect", "send", "land", "close"]
    assert "cleanup stop failed" in capsys.readouterr().out
