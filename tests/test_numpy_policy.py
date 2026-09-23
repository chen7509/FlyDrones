from __future__ import annotations

import numpy as np
from gymnasium import Env, spaces

from flydrones.numpy_policy import NumpyMlpPolicy, export_sb3_ppo_actor


def test_numpy_mlp_policy_applies_two_tanh_layers_and_clips_action(tmp_path):
    path = tmp_path / "actor.npz"
    np.savez(
        path,
        w1=np.ones((2, 3)),
        b1=np.zeros(2),
        w2=np.eye(2),
        b2=np.zeros(2),
        wa=np.array([[4.0, 0.0], [0.0, -4.0]]),
        ba=np.zeros(2),
    )
    policy = NumpyMlpPolicy.load(path)

    action = policy.predict(np.array([0.5, 0.25, -0.1], dtype=np.float32))

    assert action.shape == (2,)
    assert np.all(action <= 1.0)
    assert np.all(action >= -1.0)
    assert policy.predict_calls == 1


def test_exported_numpy_actor_matches_stable_baselines_deterministic_prediction(tmp_path):
    class FixedShapeEnv(Env):
        observation_space = spaces.Box(-1.0, 1.0, shape=(16,), dtype=np.float32)
        action_space = spaces.Box(-1.0, 1.0, shape=(2,), dtype=np.float32)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(16, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(16, dtype=np.float32), 0.0, False, False, {}

    from stable_baselines3 import PPO

    model_path = tmp_path / "source-policy"
    PPO("MlpPolicy", FixedShapeEnv(), seed=7).save(model_path)
    output = tmp_path / "actor.npz"
    export_sb3_ppo_actor(model_path, output)

    original = PPO.load(model_path)
    exported = NumpyMlpPolicy.load(output)
    rng = np.random.default_rng(20260921)
    for _ in range(20):
        observation = rng.uniform(-1.0, 1.0, 16).astype(np.float32)
        expected, _state = original.predict(observation, deterministic=True)
        actual = exported.predict(observation)
        np.testing.assert_allclose(actual, expected, atol=2e-6)
