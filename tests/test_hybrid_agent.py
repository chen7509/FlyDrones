import math
from types import SimpleNamespace

import numpy as np

from flydrones.hybrid_agent import HybridPlannerAgent
from flydrones.local_planner import LocalPlannerConfig


class UnsafeReversePolicy:
    def __init__(self):
        self.calls = 0

    def predict(self, observation):
        self.calls += 1
        assert observation.shape == (16,)
        return np.asarray((-1.0, 0.0), dtype=np.float32)


def test_policy_reverse_preference_cannot_enter_unknown_space():
    policy = UnsafeReversePolicy()
    agent = HybridPlannerAgent(0, (6.5, 0.0), policy, config=LocalPlannerConfig())
    clear = SimpleNamespace(captured_at=1.0, ray_distances_m=(19.1,) * 9)
    command = agent.command(
        now=1.0,
        global_position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=clear,
    )
    assert policy.calls == 1
    assert command.forward >= 0.0
    assert agent.last_decision.rejection_counts["unknown"] > 0


def test_stale_depth_holds_then_requests_fail_closed_landing():
    agent = HybridPlannerAgent(
        0,
        (6.5, 0.0),
        UnsafeReversePolicy(),
        config=LocalPlannerConfig(),
        deadlock_land_after_s=3.0,
    )
    first = agent.command(
        now=1.0,
        global_position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=None,
    )
    agent.command(
        now=4.1,
        global_position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=None,
    )
    assert first.forward == first.lateral == 0.0
    assert agent.should_land


def test_agent_enters_arrived_phase_only_inside_target_radius():
    agent = HybridPlannerAgent(0, (6.5, 0.0), UnsafeReversePolicy(), config=LocalPlannerConfig())
    clear = SimpleNamespace(captured_at=1.0, ray_distances_m=(19.1,) * 9)
    agent.command(
        now=1.0,
        global_position=(6.2, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=clear,
    )
    assert agent.phase == "arrived"
    assert agent.last_decision.command.forward == 0.0


def test_depth_obstacle_creates_and_then_clears_a_local_bypass_target():
    agent = HybridPlannerAgent(
        2,
        (6.5, 0.0),
        UnsafeReversePolicy(),
        config=LocalPlannerConfig(),
        corridor_center_y=0.0,
    )
    blocked = SimpleNamespace(
        captured_at=1.0,
        ray_distances_m=(1.8, 1.7, 1.6, 1.0, 0.9, 1.0, 4.0, 4.0, 4.0),
    )
    agent.command(
        now=1.0,
        global_position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=blocked,
    )
    bypass = agent.active_target
    assert bypass[0] > 1.0
    assert bypass[1] > 0.5

    clear = SimpleNamespace(captured_at=2.0, ray_distances_m=(19.1,) * 9)
    agent.command(
        now=2.0,
        global_position=(bypass[0] + 0.1, bypass[1], 1.8),
        velocity=(0.2, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        peers=(),
        depth_observation=clear,
    )
    assert agent.active_target == agent.rally_target
