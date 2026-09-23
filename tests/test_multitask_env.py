import numpy as np
import pytest

from flydrones.multitask_contract import PolicyIntent, ScenarioManifest, Skill
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_scenarios import ScenarioGenerator


def manifest_with(*disturbances: str, fleet_size: int = 2) -> ScenarioManifest:
    return ScenarioManifest.from_dict(
        {
            "schema_version": 1,
            "seed": 9,
            "world": "forest",
            "fleet_size": fleet_size,
            "active_skills": ["navigate_exit"],
            "disturbances": list(disturbances),
            "failure_vehicle_ids": [],
            "minimum_active_factors": 1 + len(disturbances),
        }
    )


def hold_actions(env: MultiTaskEnv) -> dict[int, PolicyIntent]:
    return {
        vehicle_id: PolicyIntent(
            Skill.NAVIGATE_EXIT, (0.0, 0.0, 0.0, 0.0), 1.0, 0.2
        )
        for vehicle_id in sorted(env._active)
    }


def run_hold_steps(env: MultiTaskEnv, count: int) -> None:
    for _ in range(count):
        _observations, _rewards, terminated, truncated, _info = env.step(
            hold_actions(env)
        )
        if terminated or truncated:
            break


@pytest.mark.parametrize(
    "name",
    [
        "wind",
        "sensor_noise",
        "packet_loss",
        "frame_drop",
        "localization_drift",
        "battery_variation",
    ],
)
def test_each_declared_disturbance_has_a_measured_effect(name):
    env = MultiTaskEnv(manifest_with(name), max_steps=20)
    env.reset(seed=9)

    run_hold_steps(env, 10)

    assert env.telemetry().disturbance_injections[name] > 0


def test_localization_drift_changes_actor_estimate_not_critic_truth():
    control = MultiTaskEnv(manifest_with())
    drifted = MultiTaskEnv(manifest_with("localization_drift"))
    control.reset(seed=4)
    drifted.reset(seed=4)

    for _ in range(5):
        control.step(hold_actions(control))
        drifted.step(hold_actions(drifted))

    np.testing.assert_array_equal(control.true_positions(), drifted.true_positions())
    assert not np.array_equal(
        control.local_observation(0).flight_state,
        drifted.local_observation(0).flight_state,
    )


def test_stale_dropped_frame_fails_before_policy_input():
    env = MultiTaskEnv(
        manifest_with("frame_drop"), maximum_observation_age_s=0.2
    )
    env.reset(seed=1)
    env._debug_force_frame_drops(0, count=3)

    with pytest.raises(ValueError, match="stale"):
        env.local_observation(0)


def test_unknown_disturbance_is_rejected_at_environment_boundary():
    with pytest.raises(ValueError, match="unsupported disturbance"):
        MultiTaskEnv(manifest_with("unimplemented-weather"))


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
