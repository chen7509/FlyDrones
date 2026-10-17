"""Benchmark publication failure barrier; fake links/servers, no flight."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from flydrones.benchmark.contract import Command
from flydrones.benchmark.gateway import Gateway, NativeGazeboPx4Backend, shape_command
from flydrones.drones.mavlink import MavlinkDrone


class Drone:
    autopilot = "px4"

    def __init__(self, *, source_error=None, send_error=None, land_error=None):
        self.flying = True
        self.events = []
        self.source_error, self.send_error, self.land_error = source_error, send_error, land_error
        self.sent = []
        self.m = SimpleNamespace(target_system=9, target_component=1,
            mav=SimpleNamespace(set_position_target_local_ned_send=self.send))
        self.mavutil = SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_LOCAL_NED=1))

    def require_position_observation(self):
        self.events.append("position")
        if self.source_error:
            raise self.source_error

    def _send_gcs_heartbeat_if_due(self):
        self.events.append("heartbeat")

    def send(self, *args):
        self.events.append("send")
        self.sent.append(args)
        if self.send_error:
            raise self.send_error

    def land(self):
        self.events.append("land")
        if self.land_error:
            raise self.land_error
        self.flying = False


@pytest.fixture
def backend(tmp_path):
    result = NativeGazeboPx4Backend(tmp_path, tmp_path / "run", {"goal": [2, 0, 1]})
    result.drone = Drone()
    return result


def test_valid_private_world_velocity_checks_source_and_preserves_frame(backend):
    backend._send_local_ned((.3, -.2, .1, -.4))
    assert backend.drone.events == ["position", "heartbeat", "send"]
    msg = backend.drone.sent[0]
    assert msg[3] == 1 and msg[4] == 0b0000_0101_1100_0111
    assert msg[8:11] == (.3, -.2, .1) and msg[15] == -.4


@pytest.mark.parametrize("command", [(float("nan"), 0, 0, 0), (0, float("inf"), 0, 0),
                                       (True, 0, 0, 0), (10**1000, 0, 0, 0),
                                       (1e39, 0, 0, 0), (0, 0, 0), (0, 0, 0, 0, 0)])
def test_invalid_private_command_never_sends_motion_and_latches(backend, command):
    with pytest.raises(ValueError):
        backend._send_local_ned(command)
    assert not backend.drone.sent and backend._setpoint_stop.is_set()
    with pytest.raises(RuntimeError):
        backend._send_local_ned((0, 0, 0, 0))


def test_source_failure_cannot_reach_raw_motion(backend):
    original = RuntimeError("source missing")
    backend.drone = Drone(source_error=original)
    with pytest.raises(RuntimeError) as caught:
        backend._send_local_ned((.2, 0, 0, 0))
    assert caught.value is original
    assert backend.drone.events == ["position", "land"] and not backend.drone.sent
    assert backend._setpoint_stop.is_set()


def test_transport_failure_preserves_primary_and_land_failure(backend):
    original = OSError("wire failed")
    backend.drone = Drone(send_error=original, land_error=OSError("LAND failed"))
    with pytest.raises(OSError) as caught:
        backend._send_local_ned((.2, 0, 0, 0))
    assert caught.value is original and backend._setpoint_stop.is_set()
    assert any("LAND failed" in str(row) for row in backend.setpoint_failures)
    assert backend.drone.events.count("land") == 1


def test_stopped_wait_is_not_an_acknowledgement(backend):
    backend._setpoint_stop.set()
    with pytest.raises(RuntimeError, match="setpoint"):
        backend._set_command((.2, 0, 0, 0))
    assert backend._setpoint_ack == -1


def test_no_publisher_cannot_accept_a_command(backend):
    with pytest.raises(RuntimeError, match="setpoint"):
        backend._set_command((.2, 0, 0, 0))
    assert backend._setpoint_ack == -1


def test_stopped_stream_cannot_step_physics(backend):
    backend.stats["sim_ns"] = 0
    effects = []
    backend._setpoint_stop.set()
    backend._set_dynamic_poses = lambda _target: effects.append("dynamic")
    def run(_block, steps, _paused):
        effects.append("physics")
        backend.stats["sim_ns"] = steps * 1_000_000
        return True
    backend.server = SimpleNamespace(run=run, is_running=lambda: False)
    backend._drain_heartbeats = lambda: None
    with pytest.raises(RuntimeError):
        backend.advance((.2, 0, 0, 0), .05)
    assert effects == []


def test_background_failure_is_observable_and_does_not_advance_ack(backend):
    original = OSError("publisher failure")
    entered, release = threading.Event(), threading.Event()
    def send(_command):
        entered.set()
        assert release.wait(1)
        raise original
    backend._send_local_ned = send
    worker = threading.Thread(target=backend._setpoint_loop)
    backend._setpoint_thread = worker
    worker.start()
    assert entered.wait(1)
    release.set()
    worker.join(1)
    assert not worker.is_alive()
    with pytest.raises(RuntimeError) as caught:
        backend._set_command((.2, 0, 0, 0))
    assert caught.value.__cause__ is original and backend._setpoint_ack == -1


class FacadeBackend:
    def __init__(self):
        self.stopped, self.advanced = [], []
    def start(self, _world): pass
    def close(self): pass
    def stop_motion(self, error): self.stopped.append(error)
    def advance(self, command, _dt): self.advanced.append(command)


def test_facade_invalid_command_stops_old_stream_and_latches():
    native = FacadeBackend()
    gate = Gateway({"control": {"dt_s": .05, "speed_max_mps": 1,
                    "acceleration_max_mps2": 2, "yaw_rate_max_radps": .5}}, native)
    gate.start("unused")
    with pytest.raises(ValueError):
        gate.advance(Command((float("nan"), 0, 0), 0))
    assert len(native.stopped) == 1 and native.advanced == []
    with pytest.raises(RuntimeError):
        gate.advance(Command((0, 0, 0), 0))
    with pytest.raises(RuntimeError):
        gate.start("duplicate")


@pytest.mark.parametrize("previous", [Command((float("nan"), 0, 0), 0), Command((2, 0, 0), 0)])
def test_invalid_previous_state_cannot_bypass_command_limits(previous):
    with pytest.raises(ValueError):
        shape_command(Command((0, 0, 0), 0), previous, dt_s=.05, speed_max=1,
                      acceleration_max=2, yaw_rate_max=.5)


def test_large_finite_vector_has_stable_direction_instead_of_overflow_hover():
    shaped = shape_command(Command((1e308, 1e308, 0), 0), Command((0, 0, 0), 0),
                           dt_s=1, speed_max=1, acceleration_max=2, yaw_rate_max=.5)
    assert shaped.velocity_enu == pytest.approx((2**-.5, 2**-.5, 0))
    assert np.isfinite(shaped.velocity_enu).all()


def test_existing_mavlink_stale_position_gate_is_used_by_private_sender(backend):
    sent, commands = [], []
    constants = SimpleNamespace(MAV_FRAME_LOCAL_NED=1, MAV_FRAME_BODY_NED=8, MAV_CMD_NAV_LAND=21,
                                MAV_TYPE_GCS=6, MAV_AUTOPILOT_INVALID=8, MAV_STATE_ACTIVE=4)
    drone = MavlinkDrone(autopilot="px4", mavutil_module=SimpleNamespace(mavlink=constants), time_fn=lambda: .6)
    drone.m = SimpleNamespace(target_system=9, target_component=1, recv_match=lambda **_kwargs: None,
        mav=SimpleNamespace(set_position_target_local_ned_send=lambda *args: sent.append(args),
                            heartbeat_send=lambda *_args: None,
                            command_long_send=lambda *args: commands.append(args)))
    drone.flying = True
    drone._position_observed_at = 0.
    drone._position_boot_ms = 1
    backend.drone = drone
    with pytest.raises(RuntimeError, match="position"):
        backend._send_local_ned((.2, 0, 0, 0))
    assert not any(message[3] == 1 for message in sent)
    assert commands and not drone.flying


def test_physics_run_exception_stops_old_stream_and_is_recorded(backend):
    original = OSError("physics step failed")
    backend.stats["sim_ns"] = 0
    backend._setpoint_thread = SimpleNamespace(is_alive=lambda: True)
    backend._set_command = lambda _command: None
    backend._set_dynamic_poses = lambda _target: None
    def run(*_args):
        raise original
    backend.server = SimpleNamespace(run=run)
    with pytest.raises(OSError) as caught:
        backend.advance((.2, 0, 0, 0), .05)
    assert caught.value is original and backend._setpoint_stop.is_set()
    assert any("physics step failed" in str(row) for row in backend.control_records)


def test_failed_native_instance_cannot_restart_before_importing_sdk(backend):
    backend.drone.source_error = RuntimeError("source loss")
    with pytest.raises(RuntimeError):
        backend._send_local_ned((.2, 0, 0, 0))
    with pytest.raises(RuntimeError, match="latched"):
        backend.start("never-load-world")


def test_valid_live_python_publisher_ack_is_local_dispatch_only(backend):
    worker = threading.Thread(target=backend._setpoint_loop)
    backend._setpoint_thread = worker
    worker.start()
    try:
        backend._set_command((.2, -.1, 0, .3))
        assert backend._setpoint_ack >= backend._setpoint_generation
        assert any(msg[8:11] == (.2, -.1, 0) for msg in backend.drone.sent)
    finally:
        backend._setpoint_stop.set()
        worker.join(1)
    assert not worker.is_alive()


def test_stop_during_source_callback_prevents_later_motion(backend):
    entered, release = threading.Event(), threading.Event()
    errors = []
    def source():
        backend.drone.events.append("position")
        entered.set()
        assert release.wait(2)
    backend.drone.require_position_observation = source
    def send():
        try:
            backend._send_local_ned((.2, 0, 0, 0))
        except BaseException as exc:
            errors.append(exc)
    sender = threading.Thread(target=send)
    original = RuntimeError("independent safety stop")
    stopper = threading.Thread(target=lambda: backend.stop_motion(original))
    sender.start()
    try:
        assert entered.wait(1)
        stopper.start()
        assert backend._setpoint_stop.wait(1)
    finally:
        release.set()
        sender.join(1)
        if stopper.ident is not None:
            stopper.join(1)
    assert not sender.is_alive() and not stopper.is_alive()
    assert not backend.drone.sent and backend.drone.events == ["position", "land"]
    assert errors and errors[0].__cause__ is original


def test_admitted_physics_step_retained_then_refuses_future_step(backend):
    backend.stats["sim_ns"] = 0
    backend._setpoint_thread = SimpleNamespace(is_alive=lambda: True)
    backend._set_command = lambda _command: None
    backend._set_dynamic_poses = lambda _target: None
    calls = []
    original = RuntimeError("source lost during admitted step")
    def run(_block, steps, _paused):
        calls.append(steps)
        backend.stats["sim_ns"] += steps * 1_000_000
        backend.stop_motion(original)
        return True
    backend.server = SimpleNamespace(run=run)
    with pytest.raises(RuntimeError):
        backend.advance((.2, 0, 0, 0), .05)
    assert calls == [50]
    assert any(row.get("setpoint_failure_after_run") for row in backend.control_records)
    with pytest.raises(RuntimeError):
        backend.advance((.2, 0, 0, 0), .05)
    assert calls == [50]


def test_facade_cleanup_exception_cannot_replace_shape_failure():
    native = FacadeBackend()
    def stop(_error):
        raise OSError("cleanup failed")
    native.stop_motion = stop
    gate = Gateway({"control": {"dt_s": .05, "speed_max_mps": 1,
                    "acceleration_max_mps2": 2, "yaw_rate_max_radps": .5}}, native)
    gate.start("unused")
    with pytest.raises(ValueError, match="finite"):
        gate.advance(Command((float("nan"), 0, 0), 0))
    assert gate.cleanup_errors == ["OSError('cleanup failed')"]


def test_ack_received_after_deadline_cannot_be_accepted(backend, monkeypatch):
    clock = [0.]
    monkeypatch.setattr("flydrones.benchmark.gateway.time.monotonic", lambda: clock[0])
    backend._setpoint_thread = SimpleNamespace(is_alive=lambda: True)
    def wait(_timeout):
        clock[0] = .6
        backend._setpoint_ack = backend._setpoint_generation
    monkeypatch.setattr(backend._setpoint_condition, "wait", wait)
    with pytest.raises(TimeoutError):
        backend._set_command((.2, 0, 0, 0))
    assert backend._setpoint_stop.is_set()


def test_failure_during_pose_preparation_prevents_unstarted_physics(backend):
    backend.stats["sim_ns"] = 0
    backend._setpoint_thread = SimpleNamespace(is_alive=lambda: True)
    backend._set_command = lambda _command: None
    calls = []
    backend._set_dynamic_poses = lambda _target: backend.stop_motion(RuntimeError("pose preparation loss"))
    backend.server = SimpleNamespace(run=lambda *_args: calls.append("physics") or True)
    with pytest.raises(RuntimeError, match="latched"):
        backend.advance((.2, 0, 0, 0), .05)
    assert calls == []


def test_close_does_not_land_during_mavlink_callback(backend):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    backend._setpoint_thread = SimpleNamespace(join=lambda **_kwargs: None)
    def callback():
        with backend._mavlink_lock:
            entered.set()
            assert release.wait(2)
    def close():
        try:
            backend.close()
        finally:
            finished.set()
    owner = threading.Thread(target=callback)
    closer = threading.Thread(target=close)
    owner.start()
    try:
        assert entered.wait(1)
        closer.start()
        assert backend._setpoint_stop.wait(1)
        assert not finished.wait(.1)
        assert "land" not in backend.drone.events
    finally:
        release.set()
        owner.join(1)
        if closer.ident is not None:
            closer.join(1)
    assert not owner.is_alive() and not closer.is_alive()
    assert backend.drone.events == ["land"]


def heartbeat(*, offboard=True):
    return SimpleNamespace(get_type=lambda: "HEARTBEAT", get_srcSystem=lambda: 9,
                           autopilot=12, custom_mode=(6 if offboard else 1) << 16, base_mode=128)


def test_telemetry_filtered_heartbeat_is_observed_without_cached_renewal(backend):
    hb = heartbeat()
    backend.drone.m.message_hooks = []
    backend.drone.m.recv_match = lambda **_kwargs: None
    def source():
        for hook in backend.drone.m.message_hooks:
            hook(backend.drone.m, hb)
    backend.drone.require_position_observation = source
    install = getattr(backend, "_install_offboard_hook", None)
    if install:
        install()
    backend.stats["sim_ns"] = 100
    backend._send_local_ned((.2, 0, 0, 0))
    assert backend._last_offboard_sim_ns == 100
    backend.stats["sim_ns"] = 200
    backend._drain_heartbeats()
    backend._record_offboard_heartbeat(hb)
    assert backend._last_offboard_sim_ns == 100 and len(backend.offboard_evidence) == 1
    backend.close()
    assert backend.drone.m.message_hooks == []


def test_filtered_nonoffboard_heartbeat_refuses_motion(backend):
    backend.drone.m.message_hooks = []
    def source():
        for hook in backend.drone.m.message_hooks:
            hook(backend.drone.m, heartbeat(offboard=False))
    backend.drone.require_position_observation = source
    install = getattr(backend, "_install_offboard_hook", None)
    if install:
        install()
    backend.stats["sim_ns"] = 100
    with pytest.raises(RuntimeError, match="OFFBOARD"):
        backend._send_local_ned((.2, 0, 0, 0))
    assert backend.drone.sent == [] and backend._setpoint_stop.is_set()


def test_cleanup_lock_timeout_is_recorded_without_concurrent_land(backend):
    backend._mavlink_lock = SimpleNamespace(acquire=lambda **_kwargs: False)
    backend.close()
    assert "land" not in backend.drone.events
    assert backend.control_records[-1]["land_attempted"] is False
    assert "barrier" in backend.control_records[-1]["land_error"]
