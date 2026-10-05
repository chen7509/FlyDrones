import math

import pytest

from tools.benchmark.disarmed_motion_probe import MotionPolicy, profile


def fixture_probe(tmp_path, monkeypatch):
    import sys
    import time
    from types import SimpleNamespace as NS

    from tools.benchmark.disarmed_motion_probe import GazeboMotionProbe

    class Vector:
        def __init__(self, *values):
            self.values = values

        def x(self):
            return self.values[0]

        def y(self):
            return self.values[1]

        def z(self):
            return self.values[2]

    monkeypatch.setitem(sys.modules, "gz.math7", NS(Vector3d=Vector))
    monkeypatch.setitem(sys.modules, "gz.sim8", NS(K_NULL_ENTITY=0, Link=None, Model=None, World=None, world_entity=None))
    rotation = NS(
        x=lambda: 0.0, y=lambda: 0.0, z=lambda: 0.0, w=lambda: 1.0, roll=lambda: 0.0, pitch=lambda: 0.0, yaw=lambda: 0.0
    )
    pose = NS(pos=lambda: Vector(0.0, 0.0, 0.0), rot=lambda: rotation)
    forces = []
    link = NS(
        world_pose=lambda _: pose,
        world_linear_velocity=lambda _: Vector(0.0, 0.0, 0.0),
        world_linear_acceleration=lambda _: Vector(0.0, 0.0, 0.0),
        world_angular_velocity=lambda _: Vector(0.0, 0.0, 0.0),
        add_world_force=lambda _, force: forces.append(force.values),
    )
    probe = GazeboMotionProbe(tmp_path, [], time.monotonic_ns)
    probe.link = link
    probe.policy.origin = [0.0, 0.0, 0.0]
    probe.policy.last_ns = 4_999_000_000
    return probe, link, rotation, Vector, forces


@pytest.mark.parametrize("failed_stream", ["commands", "truth", "both"])
def test_close_failure_retains_applied_but_unrecorded_force(tmp_path, monkeypatch, failed_stream):
    from datetime import timedelta
    from types import SimpleNamespace as NS

    probe, _, _, _, forces = fixture_probe(tmp_path, monkeypatch)
    closed = []

    class FaultyStream:
        def __init__(self, name, original):
            self.name, self.original = name, original

        def write(self, _):
            raise OSError("injected record failure")

        def close(self):
            closed.append(self.name)
            self.original.close()
            if failed_stream in (self.name, "both"):
                raise OSError("injected close " + self.name)

    for name in ("commands", "truth"):
        setattr(probe, name, FaultyStream(name, getattr(probe, name)))
    probe.pre_update(NS(sim_time=timedelta(seconds=5), dt=timedelta(milliseconds=1), paused=False), None)
    assert forces == [(0.0, 26.0, 0.0)]
    assert "record failure" in probe.policy.failure
    summary = probe.finish()
    assert closed == ["commands", "truth"]
    assert summary["last_attempt"]["call_returned"] is True
    assert summary["recorded_commands"] == 0
    assert "record failure" in summary["failure"]
    expected = 2 if failed_stream == "both" else 1
    assert len(summary["close_errors"]) == expected
    assert summary["eligible_for_px4_fusion"] is False


@pytest.mark.parametrize("field", ["accel", "angular", "quaternion"])
@pytest.mark.parametrize("invalid", [math.nan, math.inf])
def test_off_cadence_invalid_physics_stops_next_force(tmp_path, monkeypatch, field, invalid):
    from datetime import timedelta
    from types import SimpleNamespace as NS

    probe, link, rotation, vector, forces = fixture_probe(tmp_path, monkeypatch)
    if field == "accel":
        link.world_linear_acceleration = lambda _: vector(invalid, 0.0, 0.0)
    if field == "angular":
        link.world_angular_velocity = lambda _: vector(0.0, invalid, 0.0)
    if field == "quaternion":
        rotation.w = lambda: invalid
    probe.policy.last_ns = 5_001_000_000
    probe.post_update(NS(sim_time=timedelta(seconds=5.001)), None)
    probe.pre_update(NS(sim_time=timedelta(seconds=5.002), dt=timedelta(milliseconds=1), paused=False), None)
    summary = probe.finish()
    assert summary["failure"] is not None
    assert probe.errors
    assert not forces
    assert summary["truth_records"] == 0


def test_complete_profile_impulse_and_exact_active_boundaries():
    policy = MotionPolicy()
    active = []
    for ns in range(0, 25_000_000_000, 1_000_000):
        force = policy.step(ns, 1_000_000, unarmed_wall_ns=1000, wall_ns=1001)
        if force:
            active.append((ns, force))
    assert len(active) == 1600
    assert active[0] == (5_000_000_000, 26.0)
    assert active[-1] == (6_599_000_000, 26.0)
    assert sum(v for _, v in active) * 0.001 == 0
    assert sum(abs(v) for _, v in active) * 0.001 == 41.6
    assert policy.finish()["active_steps"] == 1600
    assert profile()["eligible_for_px4_fusion"] is False


@pytest.mark.parametrize("fault", ["gap", "duplicate", "dt", "bool", "negative"])
def test_step_refusal_latches(fault):
    p = MotionPolicy()
    p.step(0, 1_000_000, unarmed_wall_ns=None, wall_ns=1000)
    ns, dt = 1_000_000, 1_000_000
    if fault == "gap":
        ns = 2_000_000
    if fault == "duplicate":
        ns = 0
    if fault == "dt":
        dt = 2_000_000
    if fault == "bool":
        ns = True
    if fault == "negative":
        ns = -1
    with pytest.raises(ValueError):
        p.step(ns, dt, unarmed_wall_ns=None, wall_ns=1000)
    with pytest.raises(ValueError, match="latched"):
        p.step(1_000_000, 1_000_000, unarmed_wall_ns=999, wall_ns=1000)


@pytest.mark.parametrize("heartbeat", [None, 0, 1, 4000000000])
def test_active_force_requires_recent_nonfuture_disarmed_heartbeat(heartbeat):
    p = MotionPolicy()
    for ns in range(0, 5_000_000_000, 1_000_000):
        p.step(ns, 1_000_000, unarmed_wall_ns=None, wall_ns=3_000_000_000)
    with pytest.raises(ValueError, match="heartbeat"):
        p.step(5_000_000_000, 1_000_000, unarmed_wall_ns=heartbeat, wall_ns=3_000_000_000)


@pytest.mark.parametrize(
    "position,velocity,rpy",
    [
        ([1.001, 0, 0], [0, 0, 0], [0, 0, 0]),
        ([0, 0, 0], [3.001, 0, 0], [0, 0, 0]),
        ([0, 0, 0], [0, 0, 0], [math.pi / 4 + 0.001, 0, 0]),
        ([0, 0, 0], [0, 0, 0], [0, math.pi / 4 + 0.001, 0]),
        ([0, math.nan, 0], [0, 0, 0], [0, 0, 0]),
        ([0, 0, 0], [0, math.inf, 0], [0, 0, 0]),
    ],
)
def test_fixture_monitor_latches_without_sending_truth_to_policy(position, velocity, rpy):
    p = MotionPolicy()
    p.observe([0, 0, 0], [0, 0, 0], [0, 0, 0])
    with pytest.raises(ValueError):
        p.observe(position, velocity, rpy)
    with pytest.raises(ValueError, match="latched"):
        p.step(0, 1_000_000, unarmed_wall_ns=1000, wall_ns=1001)


def test_monitor_boundary_and_initial_position_offset():
    p = MotionPolicy()
    p.observe([-8, 0, 0.24], [0, 0, 0], [0, 0, 0])
    p.observe([-7, 0, 0.24], [3, 0, 0], [math.pi / 4, 0, 0])
    assert p.finish()["failure"] is None
