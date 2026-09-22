import numpy as np
import pytest

from flydrones.multitask_contract import PolicyIntent, ScenarioManifest, Skill
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


def test_critic_truth_read_does_not_change_future_noisy_actor_observations():
    manifest = ScenarioGenerator(19).generate(level=4, fleet_size=5)
    left = MultiTaskEnv(manifest)
    right = MultiTaskEnv(manifest)
    left.reset(seed=19)
    right.reset(seed=19)
    left.critic_observation()
    np.testing.assert_array_equal(left.actor_observation(0), right.actor_observation(0))


def test_rewards_do_not_train_tasks_that_are_absent_or_not_selected():
    manifest = ScenarioManifest.from_dict(
        {
            "schema_version": 1,
            "seed": 31,
            "world": "forest",
            "fleet_size": 1,
            "active_skills": ["gate_course"],
            "disturbances": [],
            "failure_vehicle_ids": [],
            "minimum_active_factors": 1,
        }
    )
    env = MultiTaskEnv(manifest)
    env.reset(seed=31)
    _, _, _, _, info = env.step(
        {0: PolicyIntent(Skill.GATE_COURSE, (0.5, 0.0, 0.0, 0.0), 1.0, 0.2)}
    )
    terms = info["reward_terms"][0]
    assert terms["exit_progress"] == 0.0
    assert terms["target_tracking"] == 0.0
    assert terms["new_coverage"] == 0.0
    assert terms["gate_progress"] != 0.0
