"""Constructed estimated inputs through real backend paths; no simulator/network."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from flydrones.benchmark import contract
from flydrones.benchmark.gateway import Gateway, NativeGazeboPx4Backend
from flydrones.drones.mavlink import MavlinkDrone


@pytest.fixture(autouse=True)
def no_native_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("software test attempted a native/process/network effect")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("os.system", forbidden)


def state(**changes):
    cls = getattr(contract, "EstimatedControllerState", None)
    assert cls is not None, "estimated controller state interface is missing"
    result = cls(
        session_id="owned-estimator-fixture",
        reset_counter=0,
        sample_ns=150_000_000,
        camera_frame_ns=100_000_000,
        position=(1.0, 2.0, 1.5),
        velocity=(0.2, -0.1, 0.05),
        yaw=0.3,
        yaw_rate=-0.2,
        camera_pose=(1.1, 2.2, 1.7, 0.0, 0.0, 0.0, 1.0),
    )
    return replace(result, **changes)


class Source:
    def __init__(self, value=None):
        self.value = value
        self.failure = None
        self.reads = 0
        self.checks = []

    def require_ready(self, sim_ns):
        self.checks.append(sim_ns)
        if self.failure:
            raise self.failure

    def snapshot(self, sim_ns, frame_ns):
        assert (sim_ns, frame_ns) == (150_000_000, 100_000_000)
        self.reads += 1
        return self.value


def backend(tmp_path, source):
    result = NativeGazeboPx4Backend(
        tmp_path,
        tmp_path / "run",
        {"goal": [900.0, 900.0, 900.0]},
        estimated_state_source=source,
        goal_in_estimator_frame=(8.0, 0.0, 1.5),
    )
    result.stats["sim_ns"] = 150_000_000
    result.frames["rgb"][100_000_000] = np.full((2, 3, 3), 7, np.uint8)
    result.frames["depth"][100_000_000] = np.full((2, 3), 4.0, np.float32)

    def truth_forbidden():
        raise AssertionError("controller input touched simulator truth")

    result._current_model_pose = truth_forbidden
    result._velocity = lambda _: truth_forbidden()
    return result


def test_estimated_observation_reaches_controller_without_truth_or_world_goal(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    gateway = Gateway(
        {"control": {"dt_s": 0.05, "speed_max_mps": 0.8, "acceleration_max_mps2": 1.2, "yaw_rate_max_radps": 0.6}}, native
    )
    gateway.started = True  # No native startup; exercise the real facade observe path.
    obs = gateway.observe()
    assert obs.position == (1.0, 2.0, 1.5)
    assert obs.velocity == (0.2, -0.1, 0.05)
    assert (obs.yaw, obs.yaw_rate) == (0.3, -0.2)
    assert obs.camera_pose == (1.1, 2.2, 1.7, 0.0, 0.0, 0.0, 1.0)
    assert obs.goal == (8.0, 0.0, 1.5)
    assert (obs.sim_ns, obs.frame_ns) == (150_000_000, 100_000_000)
    assert np.all(obs.rgb == 7) and np.all(obs.depth_m == 4.0)
    obs.rgb[:] = 0
    assert np.all(native.frames["rgb"][100_000_000] == 7)
    assert native.odometry_source == "supplied_estimator_unverified"
    assert native.camera_pose_source == "supplied_estimator_unverified"


def test_estimated_mode_requires_separate_goal_before_output_effects(tmp_path):
    with pytest.raises(ValueError, match="goal"):
        NativeGazeboPx4Backend(tmp_path, tmp_path / "absent", {"goal": [8.0, 0.0, 1.5]}, estimated_state_source=Source())
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_ns": 49_999_999},
        {"sample_ns": 150_000_001},
        {"camera_frame_ns": 99_999_999},
        {"sample_ns": True},
        {"position": (float("nan"), 0.0, 0.0)},
        {"velocity": (float("inf"), 0.0, 0.0)},
        {"yaw": float("nan")},
        {"yaw_rate": True},
        {"camera_pose": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)},
        {"camera_pose": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0)},
        {"session_id": ""},
        {"reset_counter": -1},
        {"reset_counter": True},
        {"position": [1.0, 2.0, 3.0]},
    ],
)
def test_bad_estimate_never_falls_back_to_truth(tmp_path, changes):
    native = backend(tmp_path, Source(state(**changes)))
    with pytest.raises((ValueError, RuntimeError)):
        native.observe()


@pytest.mark.parametrize("change", [{"session_id": "replacement"}, {"reset_counter": 1}])
def test_same_rgb_frame_does_not_hide_estimator_reset(tmp_path, change):
    source = Source(state())
    native = backend(tmp_path, source)
    native.observe()
    source.value = state(**change)
    with pytest.raises(ValueError, match="session|reset"):
        native.observe()
    source.value = state()
    with pytest.raises(RuntimeError, match="latched"):
        native.observe()


def test_unknown_source_readiness_prevents_takeoff(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    armed = []
    native.drone = SimpleNamespace(takeoff=lambda: armed.append(True), flying=False)
    source.failure = RuntimeError("calibration/clock/fusion not ready")
    with pytest.raises(RuntimeError, match="not ready"):
        native._takeoff_with_estimated_input()
    assert armed == []


def test_takeoff_retry_rechecks_estimate_instead_of_rearming_on_old_readiness(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    attempts = []

    def takeoff():
        attempts.append(True)
        source.failure = RuntimeError("fusion lost")
        raise TimeoutError("PX4 did not arm within 10 seconds")

    native.drone = SimpleNamespace(takeoff=takeoff, flying=False)
    with pytest.raises(RuntimeError, match="fusion lost"):
        native._takeoff_with_estimated_input()
    assert attempts == [True]


def test_final_send_rechecks_source_after_telemetry_and_heartbeat(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    sends, lands = [], []

    def heartbeat():
        source.failure = RuntimeError("source expired during heartbeat")

    native.drone = SimpleNamespace(
        autopilot="px4",
        flying=True,
        require_position_observation=lambda: None,
        _send_gcs_heartbeat_if_due=heartbeat,
        land=lambda: lands.append(True),
        m=SimpleNamespace(
            target_system=9,
            target_component=1,
            mav=SimpleNamespace(set_position_target_local_ned_send=lambda *a: sends.append(a)),
        ),
        mavutil=SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_LOCAL_NED=1)),
    )
    with pytest.raises(RuntimeError, match="expired"):
        native._send_local_ned((0.2, 0.0, 0.0, 0.0))
    assert sends == [] and lands == [True]
    assert native._setpoint_stop.is_set()


def test_source_failure_stops_before_physics_or_setpoint(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    source.failure = RuntimeError("estimator failed")
    effects = []
    native._setpoint_thread = SimpleNamespace(is_alive=lambda: True)
    native._set_command = lambda _: effects.append("command")
    native.server = SimpleNamespace(run=lambda *a: effects.append("physics"))
    with pytest.raises(RuntimeError, match="estimator failed"):
        native.advance((0.2, 0.0, 0.0, 0.0), 0.05)
    assert effects == []


def test_readiness_lost_during_mode_switch_prevents_actual_arm_command(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    events = []
    drone = MavlinkDrone(autopilot="px4", mavutil_module=SimpleNamespace(), flight_readiness_check=native._check_estimated_input)
    native.drone = drone
    drone._prime_px4_offboard = lambda: None
    drone._require_px4_position = lambda: None
    drone.land = lambda: events.append("LAND requested")

    def switch_mode(mode):
        events.append(mode)
        source.failure = RuntimeError("fusion failed while mode switched")

    drone.m = SimpleNamespace(set_mode=switch_mode, arducopter_arm=lambda: events.append("ARM sent"))
    with pytest.raises(RuntimeError, match="fusion failed"):
        native._takeoff_with_estimated_input()
    assert events == ["OFFBOARD", "LAND requested"]


def test_takeoff_body_velocity_cannot_bypass_estimator_failure(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    events = []
    drone = MavlinkDrone(
        autopilot="px4",
        mavutil_module=SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_BODY_NED=8)),
        flight_readiness_check=native._check_estimated_input,
    )
    native.drone = drone
    drone.flying = True
    drone.land = lambda: events.append("LAND requested")
    drone._send_gcs_heartbeat_if_due = lambda: None
    drone.m = SimpleNamespace(
        target_system=9,
        target_component=1,
        mav=SimpleNamespace(set_position_target_local_ned_send=lambda *a: events.append("setpoint")),
    )
    source.failure = RuntimeError("fusion lost during ascent")
    with pytest.raises(RuntimeError, match="fusion lost"):
        drone._send_velocity(0.0, 0.0, -0.5, 0.0)
    assert events == ["LAND requested"]


def test_estimated_observation_does_not_replace_independent_truth_scorer(tmp_path):
    native = backend(tmp_path, Source(state()))
    native.observe()
    native.world = {
        "bounds": [[-12.0, -8.0, 0.1], [12.0, 8.0, 4.9]],
        "boxes": [],
        "cylinders": [],
        "dynamic": [],
        "vehicle_envelope_radius_m": 0.5,
    }
    native._current_model_pose = lambda: ((-3.0, -4.0, 1.5, 0.0, 0.0, 0.0, 1.0), 150_000_000)
    score = native.score_sample()
    assert score.position == (-3.0, -4.0, 1.5)
    assert native.observe().position == (1.0, 2.0, 1.5)


def test_disappearing_latest_frame_cannot_pair_old_stamp_with_cached_new_pixels(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    native.observe()
    native.frames["rgb"] = {90_000_000: np.zeros((2, 3, 3), np.uint8)}
    native.frames["depth"] = {90_000_000: np.ones((2, 3), np.float32)}
    source.snapshot = lambda sim_ns, frame_ns: state(camera_frame_ns=frame_ns)
    with pytest.raises(ValueError, match="frame"):
        native.observe()


def test_legacy_observe_still_explicitly_labels_truth(tmp_path):
    native = NativeGazeboPx4Backend(tmp_path, tmp_path / "run", {"goal": [8.0, 0.0, 1.5]})
    native.stats["sim_ns"] = 100_000_000
    native._current_model_pose = lambda: ((2.0, 3.0, 1.5, 0.0, 0.0, 0.0, 1.0), 100_000_000)
    native._velocity = lambda _: ((0.1, 0.2, 0.3), 0.4)
    native.pose_history.add(100_000_000, (2.0, 3.0, 1.5, 0.0, 0.0, 0.0, 1.0))
    native.frames["rgb"][100_000_000] = np.zeros((2, 3, 3), np.uint8)
    native.frames["depth"][100_000_000] = np.ones((2, 3), np.float32)
    obs = native.observe()
    assert obs.position == (2.0, 3.0, 1.5) and obs.velocity == (0.1, 0.2, 0.3)
    assert native.odometry_source == native.camera_pose_source == "gazebo_model_truth"


def test_waiting_sender_cannot_enter_between_validation_failure_and_latch(tmp_path):
    """Deterministically model another sender at the lock-release boundary."""
    import threading

    source = Source(state(sample_ns=150_000_001))
    native = backend(tmp_path, source)
    sends = []
    native.drone = SimpleNamespace(
        autopilot="px4",
        flying=False,
        require_position_observation=lambda: None,
        _send_gcs_heartbeat_if_due=lambda: None,
        m=SimpleNamespace(
            target_system=9,
            target_component=1,
            mav=SimpleNamespace(set_position_target_local_ned_send=lambda *a: sends.append(a)),
        ),
        mavutil=SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_LOCAL_NED=1)),
    )

    class ReleaseBoundary:
        def __init__(self):
            self.lock = threading.RLock()
            self.injected = False

        def __enter__(self):
            self.lock.acquire()
            return self

        def __exit__(self, exc_type, value, traceback):
            self.lock.release()
            if exc_type is not None and not self.injected:
                self.injected = True
                source.value = state()
                try:
                    native._send_local_ned((0.2, 0.0, 0.0, 0.0))
                except RuntimeError:
                    pass

    native._estimate_lock = ReleaseBoundary()
    with pytest.raises(ValueError, match="time"):
        native.observe()
    assert sends == []


@pytest.mark.parametrize("new_time", [251_000_000, 149_999_999])
def test_final_readiness_return_must_revalidate_current_time(tmp_path, new_time):
    source = Source(state())
    native = backend(tmp_path, source)

    def check(sim_ns):
        source.checks.append(sim_ns)
        if len(source.checks) == 2:
            native.stats["sim_ns"] = new_time

    source.require_ready = check
    with pytest.raises(ValueError, match="time"):
        native.observe()


def test_pending_arm_ack_neutral_setpoint_still_requires_live_source(tmp_path):
    source = Source(state())
    native = backend(tmp_path, source)
    events = []
    drone = MavlinkDrone(
        autopilot="px4",
        mavutil_module=SimpleNamespace(mavlink=SimpleNamespace(MAV_FRAME_BODY_NED=8)),
        flight_readiness_check=native._check_estimated_input,
        time_fn=lambda: 0.0,
        sleep_fn=lambda _: None,
    )
    native.drone = drone
    drone._prime_px4_offboard = lambda: None
    drone._require_px4_position = lambda: None
    drone.telemetry = lambda: SimpleNamespace(alt_m=2.0)
    drone._send_gcs_heartbeat_if_due = lambda: None
    drone.land = lambda: events.append("LAND requested")
    armed = iter((False, True))

    def arm():
        events.append("ARM sent")
        source.failure = RuntimeError("fusion lost waiting for ARM acknowledgement")

    drone.m = SimpleNamespace(
        target_system=9,
        target_component=1,
        set_mode=lambda _: None,
        arducopter_arm=arm,
        motors_armed=lambda: next(armed),
        recv_match=lambda **kw: None,
        mav=SimpleNamespace(set_position_target_local_ned_send=lambda *a: events.append("neutral setpoint")),
    )
    with pytest.raises(RuntimeError, match="fusion lost"):
        native._takeoff_with_estimated_input()
    assert events == ["ARM sent", "LAND requested"]
    assert drone._arming_pending is False


def test_clock_regression_between_polls_does_not_hide_behind_repeated_estimate(tmp_path):
    source = Source(state(sample_ns=100_000_000))
    native = backend(tmp_path, source)
    source.snapshot = lambda sim_ns, frame_ns: source.value
    native.observe()
    native.stats["sim_ns"] = 149_999_999
    with pytest.raises(ValueError, match="time regressed"):
        native.observe()
