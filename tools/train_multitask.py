"""Train the shared recurrent actor in the fast compound-task simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

import numpy as np
import torch
from torch.distributions import Categorical, Normal

from flydrones.multitask_contract import PolicyIntent, Skill
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_policy import CentralizedCritic, SharedRecurrentPolicy
from flydrones.multitask_scenarios import ScenarioGenerator


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def _code_version() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def train(args: argparse.Namespace) -> dict[str, object]:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)

    manifest = ScenarioGenerator(args.seed).generate(
        level=args.level,
        fleet_size=args.fleet_size,
    )
    env = MultiTaskEnv(manifest, max_steps=max(args.steps, 16))
    observations, _ = env.reset(seed=args.seed)
    actor = SharedRecurrentPolicy()
    critic_input = int(env.critic_observation().shape[0])
    critic = CentralizedCritic(critic_input)
    optimizer = torch.optim.Adam(
        [*actor.parameters(), *critic.parameters()],
        lr=args.learning_rate,
    )
    hidden = {
        vehicle_id: torch.zeros(64, dtype=torch.float32)
        for vehicle_id in observations
    }
    samples: list[dict[str, torch.Tensor | float | bool]] = []
    total_reward = 0.0
    collisions = 0
    central_commands = 0
    reward_terms: dict[str, float] = {}

    for _step in range(args.steps):
        actions: dict[int, PolicyIntent] = {}
        pending: dict[int, tuple[torch.Tensor, ...]] = {}
        critic_vector = torch.tensor(env.critic_observation(), dtype=torch.float32)
        value = critic(critic_vector.unsqueeze(0))[0]
        for vehicle_id, vector in sorted(observations.items()):
            observation_tensor = torch.tensor(vector, dtype=torch.float32).reshape(1, 1, -1)
            hidden_tensor = hidden[vehicle_id].reshape(1, 1, -1)
            logits, motion_mean, confidence, next_hidden = actor(
                observation_tensor,
                hidden_tensor,
            )
            skill_distribution = Categorical(logits=logits[0])
            motion_distribution = Normal(motion_mean[0], 0.15)
            skill_index = skill_distribution.sample()
            raw_motion = motion_distribution.sample()
            bounded_motion = torch.clamp(raw_motion, -1.0, 1.0)
            log_probability = (
                skill_distribution.log_prob(skill_index)
                + motion_distribution.log_prob(raw_motion).sum()
            )
            actions[vehicle_id] = PolicyIntent(
                tuple(Skill)[int(skill_index.item())],
                tuple(float(item) for item in bounded_motion.detach().numpy()),  # type: ignore[arg-type]
                float(confidence[0].detach().item()),
                0.2,
            )
            pending[vehicle_id] = (
                observation_tensor[0, 0].detach(),
                hidden_tensor[0, 0].detach(),
                skill_index.detach(),
                raw_motion.detach(),
                log_probability.detach(),
                critic_vector.detach(),
                value.detach(),
            )
            hidden[vehicle_id] = next_hidden[0, 0].detach()

        next_observations, rewards, terminated, truncated, info = env.step(actions)
        central_commands += int(info["central_control_commands"])
        if info["safety_failure"] == "collision":
            collisions += 1
        for vehicle_id, reward in rewards.items():
            total_reward += reward
            local_terms = info["reward_terms"][vehicle_id]
            for name, amount in local_terms.items():
                reward_terms[name] = reward_terms.get(name, 0.0) + float(amount)
            stored = pending[vehicle_id]
            samples.append(
                {
                    "observation": stored[0],
                    "hidden": stored[1],
                    "skill": stored[2],
                    "motion": stored[3],
                    "old_log_probability": stored[4],
                    "critic_observation": stored[5],
                    "value": stored[6],
                    "reward": float(reward),
                    "done": bool(terminated or truncated),
                }
            )
        observations = next_observations
        hidden = {
            vehicle_id: hidden.get(vehicle_id, torch.zeros(64, dtype=torch.float32))
            for vehicle_id in observations
        }
        if terminated or truncated:
            observations, _ = env.reset(seed=args.seed + _step + 1)
            hidden = {
                vehicle_id: torch.zeros(64, dtype=torch.float32)
                for vehicle_id in observations
            }

    rewards_tensor = torch.tensor([sample["reward"] for sample in samples], dtype=torch.float32)
    values_tensor = torch.stack([sample["value"] for sample in samples]).float()
    dones_tensor = torch.tensor([sample["done"] for sample in samples], dtype=torch.float32)
    advantages = torch.zeros_like(rewards_tensor)
    gae = torch.tensor(0.0)
    next_value = torch.tensor(0.0)
    for index in range(len(samples) - 1, -1, -1):
        mask = 1.0 - dones_tensor[index]
        delta = rewards_tensor[index] + 0.99 * next_value * mask - values_tensor[index]
        gae = delta + 0.99 * 0.95 * mask * gae
        advantages[index] = gae
        next_value = values_tensor[index]
    returns = advantages + values_tensor
    if len(advantages) > 1:
        advantages = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-8)

    observation_batch = torch.stack([sample["observation"] for sample in samples])
    hidden_batch = torch.stack([sample["hidden"] for sample in samples]).unsqueeze(0)
    skill_batch = torch.stack([sample["skill"] for sample in samples]).long()
    motion_batch = torch.stack([sample["motion"] for sample in samples])
    old_log_probability = torch.stack(
        [sample["old_log_probability"] for sample in samples]
    ).float()
    critic_batch = torch.stack([sample["critic_observation"] for sample in samples])
    for _epoch in range(4):
        logits, motion_mean, _confidence, _next_hidden = actor(
            observation_batch.unsqueeze(1),
            hidden_batch,
        )
        skill_distribution = Categorical(logits=logits)
        motion_distribution = Normal(motion_mean, 0.15)
        new_log_probability = (
            skill_distribution.log_prob(skill_batch)
            + motion_distribution.log_prob(motion_batch).sum(dim=1)
        )
        ratio = torch.exp(new_log_probability - old_log_probability)
        clipped_ratio = torch.clamp(ratio, 0.8, 1.2)
        policy_loss = -torch.minimum(ratio * advantages, clipped_ratio * advantages).mean()
        entropy = skill_distribution.entropy().mean() + motion_distribution.entropy().sum(dim=1).mean()
        predicted_values = critic(critic_batch)
        value_loss = torch.mean((predicted_values - returns) ** 2)
        loss = policy_loss + 0.5 * value_loss - 0.01 * entropy
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_([*actor.parameters(), *critic.parameters()], 1.0)
        optimizer.step()

    checkpoint_path = Path(args.checkpoint)
    actor.export(checkpoint_path)
    checkpoint_digest = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    report = {
        "schema_version": 1,
        "seed": args.seed,
        "level": args.level,
        "fleet_size": args.fleet_size,
        "steps": args.steps,
        "manifest_digest": manifest.digest,
        "code_version": _code_version(),
        "checkpoint_digest": checkpoint_digest,
        "total_reward": total_reward,
        "reward_terms": dict(sorted(reward_terms.items())),
        "collisions": collisions,
        "central_control_commands": central_commands,
        "ppo": {
            "gamma": 0.99,
            "gae_lambda": 0.95,
            "clip_ratio": 0.20,
            "entropy_coefficient": 0.01,
            "value_coefficient": 0.50,
            "update_epochs": 4,
        },
    }
    _write_json(Path(args.report), report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=int, choices=range(5), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--fleet-size", type=_positive_int, default=1)
    parser.add_argument("--steps", type=_positive_int, required=True)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
