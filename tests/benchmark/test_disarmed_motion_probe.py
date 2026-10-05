import math

import pytest

from tools.benchmark.disarmed_motion_probe import MotionPolicy, profile


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
