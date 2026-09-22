import numpy as np
import pytest

from flydrones.multitask_contract import PolicyIntent, Skill
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_scenarios import ScenarioGenerator


def test_reset_is_seeded_and_actor_has_no_global_truth():
    manifest = ScenarioGenerator(13).generate(level=3, fleet_size=20)
    left = MultiTaskEnv(manifest)
    right = MultiTaskEnv(manifest)
    left_actors, left_info = left.reset(seed=13)
    right_actors, right_info = right.reset(seed=13)
    assert set(left_actors) == set(range(20))
    np.testing.assert_array_equal(left_actors[0], right_actors[0])
    assert left_actors[0].shape == (90,)
    assert left.single_observation_space.shape == (90,)
    assert left.critic_observation().shape[0] > left_actors[0].shape[0]
    assert "global_positions" not in left_info
    assert left_info["manifest_digest"] == right_info["manifest_digest"]


def test_collision_is_a_hard_failure_and_not_only_a_reward_penalty():
    env = MultiTaskEnv(ScenarioGenerator(2).generate(level=1, fleet_size=1))
    env.reset(seed=2)
    env._debug_set_clearance_m(0, -0.01)
    _, rewards, terminated, _, info = env.step(
        {
            0: PolicyIntent(
                Skill.NAVIGATE_EXIT,
                (1.0, 0.0, 0.0, 0.0),
                1.0,
                0.5,
            )
        }
    )
    assert terminated
    assert rewards[0] <= -100.0
    assert info["safety_failure"] == "collision"


def test_step_rejects_central_or_wrong_action_types():
    env = MultiTaskEnv(ScenarioGenerator(2).generate(level=1, fleet_size=1))
    env.reset(seed=2)
    with pytest.raises(TypeError, match="PolicyIntent"):
        env.step({0: np.zeros(4)})


def test_step_requires_exact_local_vehicle_action_set():
    env = MultiTaskEnv(ScenarioGenerator(3).generate(level=1, fleet_size=2))
    env.reset(seed=3)
    intent = PolicyIntent(Skill.NAVIGATE_EXIT, (0.0, 0.0, 0.0, 0.0), 1.0, 0.5)
    with pytest.raises(ValueError, match="action vehicle IDs"):
        env.step({0: intent})
    with pytest.raises(ValueError, match="action vehicle IDs"):
        env.step({0: intent, 1: intent, 2: intent})
