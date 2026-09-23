"""Small dependency-free runtime for exported Stable-Baselines PPO actors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class NumpyMlpPolicy:
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray
    wa: np.ndarray
    ba: np.ndarray
    predict_calls: int = 0

    @classmethod
    def load(cls, path: str | Path) -> NumpyMlpPolicy:
        with np.load(path) as values:
            return cls(*(np.asarray(values[name], dtype=np.float32) for name in ("w1", "b1", "w2", "b2", "wa", "ba")))

    def predict(self, observation: np.ndarray) -> np.ndarray:
        values = np.asarray(observation, dtype=np.float32)
        if values.shape != (self.w1.shape[1],):
            raise ValueError(f"expected observation shape {(self.w1.shape[1],)}, got {values.shape}")
        hidden = np.tanh(self.w1 @ values + self.b1)
        hidden = np.tanh(self.w2 @ hidden + self.b2)
        action = self.wa @ hidden + self.ba
        self.predict_calls += 1
        return np.clip(action, -1.0, 1.0).astype(np.float32)


def export_sb3_ppo_actor(model_path: str | Path, output_path: str | Path) -> Path:
    """Export the deterministic actor only; training/value tensors are omitted."""
    from stable_baselines3 import PPO

    model = PPO.load(model_path, device="cpu")
    state = model.policy.state_dict()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        w1=state["mlp_extractor.policy_net.0.weight"].cpu().numpy(),
        b1=state["mlp_extractor.policy_net.0.bias"].cpu().numpy(),
        w2=state["mlp_extractor.policy_net.2.weight"].cpu().numpy(),
        b2=state["mlp_extractor.policy_net.2.bias"].cpu().numpy(),
        wa=state["action_net.weight"].cpu().numpy(),
        ba=state["action_net.bias"].cpu().numpy(),
    )
    return output
