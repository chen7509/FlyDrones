"""Resumable recurrent PPO training through the same reflex and safety path."""

from __future__ import annotations

import hashlib
import math
import os
import pickle
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.distributions import Categorical, Normal

from .multitask_contract import PolicyIntent, ScenarioManifest, Skill
from .multitask_env import MultiTaskEnv
from .multitask_policy import (
    CentralizedCritic,
    SafetyArbiter,
    SafetyProjector,
    SharedRecurrentPolicy,
)
from .multitask_reflex import ReflexDecision, ReflexEvidence

_DIGEST = re.compile(r"[0-9a-f]{64}")


def _validate_digest(value: str, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _state_dict_digest(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        values = tensor.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(values.dtype).encode())
        digest.update(repr(tuple(values.shape)).encode())
        digest.update(values.numpy().tobytes())
    return digest.hexdigest()


def gae_targets(
    samples: list[Mapping[str, object]],
    *,
    gamma: float,
    gae_lambda: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute GAE without crossing vehicle trajectory boundaries."""
    advantages = torch.zeros(len(samples), dtype=torch.float32)
    by_vehicle: dict[int, list[int]] = {}
    for index, sample in enumerate(samples):
        by_vehicle.setdefault(int(sample["vehicle_id"]), []).append(index)
    for indices in by_vehicle.values():
        gae = torch.tensor(0.0)
        next_value = torch.tensor(0.0)
        for index in reversed(indices):
            sample = samples[index]
            value = torch.as_tensor(sample["value"], dtype=torch.float32)
            mask = 0.0 if bool(sample["done"]) else 1.0
            delta = float(sample["reward"]) + gamma * next_value * mask - value
            gae = delta + gamma * gae_lambda * mask * gae
            advantages[index] = gae
            next_value = value
    values = torch.stack(
        [torch.as_tensor(sample["value"], dtype=torch.float32) for sample in samples]
    )
    return advantages, advantages + values


class _FailClosedReflex:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, observation) -> ReflexDecision:
        self.calls += 1
        return ReflexDecision(
            PolicyIntent(
                Skill.YIELD_RETURN_LAND,
                (0.0, 0.0, 0.0, 0.0),
                1.0,
                0.2,
            ),
            ReflexEvidence("unavailable", 0, 0, 0, self.calls, 0.0),
        )


@dataclass(frozen=True)
class TrainerCheckpoint:
    schema_version: int
    config_digest: str
    curriculum_state_digest: str
    critic_input_dimension: int
    global_updates: int
    environment_steps: int
    critic_resets: int


@dataclass(frozen=True)
class BatchTrainingReport:
    manifest_digest: str
    steps: int
    actor_samples: int
    critic_samples: int
    total_reward: float
    reward_terms: Mapping[str, float]
    collisions: int
    central_control_commands: int
    safety_overrides: int
    critic_reset: bool
    male_cns_backend: str
    male_cns_fallbacks: int

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_digest": self.manifest_digest,
            "steps": self.steps,
            "actor_samples": self.actor_samples,
            "critic_samples": self.critic_samples,
            "total_reward": self.total_reward,
            "reward_terms": dict(sorted(self.reward_terms.items())),
            "collisions": self.collisions,
            "central_control_commands": self.central_control_commands,
            "safety_overrides": self.safety_overrides,
            "critic_reset": self.critic_reset,
            "male_cns_backend": self.male_cns_backend,
            "male_cns_fallbacks": self.male_cns_fallbacks,
        }


class PPOTrainer:
    schema_version = 1

    def __init__(
        self,
        *,
        seed: int,
        critic_input_dimension: int,
        device: str = "cpu",
        learning_rate: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_ratio: float = 0.20,
        entropy_coefficient: float = 0.01,
        value_coefficient: float = 0.50,
        update_epochs: int = 4,
        reflex_factory: Callable[[int, ScenarioManifest], object] | None = None,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        if critic_input_dimension <= 0:
            raise ValueError("critic_input_dimension must be positive")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA device requested but unavailable")
        if not math.isfinite(learning_rate) or learning_rate <= 0.0:
            raise ValueError("learning_rate must be positive")
        if update_epochs <= 0:
            raise ValueError("update_epochs must be positive")
        self.seed = seed
        self.device = torch.device(device)
        self.learning_rate = float(learning_rate)
        self.gamma = float(gamma)
        self.gae_lambda = float(gae_lambda)
        self.clip_ratio = float(clip_ratio)
        self.entropy_coefficient = float(entropy_coefficient)
        self.value_coefficient = float(value_coefficient)
        self.update_epochs = int(update_epochs)
        self.reflex_factory = reflex_factory or (
            lambda _vehicle_id, _manifest: _FailClosedReflex()
        )
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.use_deterministic_algorithms(True)
        self.actor = SharedRecurrentPolicy().to(self.device)
        self.critic_input_dimension = int(critic_input_dimension)
        self.critic = CentralizedCritic(self.critic_input_dimension).to(self.device)
        self.actor_optimizer = torch.optim.Adam(
            self.actor.parameters(), lr=self.learning_rate
        )
        self.critic_optimizer = torch.optim.Adam(
            self.critic.parameters(), lr=self.learning_rate
        )
        self.global_updates = 0
        self.environment_steps = 0
        self.critic_resets = 0
        self._capture_random_state()

    def _capture_random_state(self) -> None:
        self._python_random_state = random.getstate()
        self._numpy_random_state = np.random.get_state()
        self._torch_random_state = torch.get_rng_state().clone()
        self._cuda_random_states = (
            [state.clone() for state in torch.cuda.get_rng_state_all()]
            if torch.cuda.is_available()
            else []
        )

    def _activate_random_state(self) -> None:
        random.setstate(self._python_random_state)
        np.random.set_state(self._numpy_random_state)
        torch.set_rng_state(self._torch_random_state)
        if torch.cuda.is_available() and self._cuda_random_states:
            torch.cuda.set_rng_state_all(self._cuda_random_states)

    def actor_digest(self) -> str:
        return _state_dict_digest(self.actor.state_dict())

    def critic_digest(self) -> str:
        return _state_dict_digest(self.critic.state_dict())

    def random_state_digest(self) -> str:
        payload = (
            self._python_random_state,
            self._numpy_random_state,
            self._torch_random_state.numpy().tobytes(),
            tuple(state.cpu().numpy().tobytes() for state in self._cuda_random_states),
        )
        return hashlib.sha256(pickle.dumps(payload, protocol=5)).hexdigest()

    def _ensure_critic_dimension(self, dimension: int) -> bool:
        if dimension == self.critic_input_dimension:
            return False
        self.critic_input_dimension = dimension
        self.critic = CentralizedCritic(dimension).to(self.device)
        self.critic_optimizer = torch.optim.Adam(
            self.critic.parameters(), lr=self.learning_rate
        )
        self.critic_resets += 1
        return True

    def train_batch(
        self, manifest: ScenarioManifest, *, steps: int
    ) -> BatchTrainingReport:
        if not isinstance(manifest, ScenarioManifest):
            raise TypeError("manifest must be a ScenarioManifest")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
            raise ValueError("steps must be positive")
        self._activate_random_state()
        episode_seed = manifest.seed + self.global_updates
        env = MultiTaskEnv(manifest, max_steps=max(steps, 16))
        observations, _ = env.reset(seed=episode_seed)
        critic_reset = self._ensure_critic_dimension(
            int(env.critic_observation().shape[0])
        )
        hidden = {
            vehicle_id: torch.zeros(64, dtype=torch.float32, device=self.device)
            for vehicle_id in observations
        }
        bridges = {
            vehicle_id: self.reflex_factory(vehicle_id, manifest)
            for vehicle_id in observations
        }
        arbiters = {
            vehicle_id: SafetyArbiter(SafetyProjector())
            for vehicle_id in observations
        }
        samples: list[dict[str, object]] = []
        total_reward = 0.0
        collisions = 0
        central_commands = 0
        reward_terms: dict[str, float] = {}
        backend_sources: set[str] = set()
        completed_fallback_calls = 0
        current_fallback_calls = {vehicle_id: 0 for vehicle_id in observations}
        safety_overrides = 0

        for batch_step in range(steps):
            actions: dict[int, PolicyIntent] = {}
            pending: dict[int, dict[str, object]] = {}
            critic_vector = torch.tensor(
                env.critic_observation(), dtype=torch.float32, device=self.device
            )
            with torch.no_grad():
                value = self.critic(critic_vector.unsqueeze(0))[0]
            for vehicle_id in sorted(observations):
                local = env.local_observation(vehicle_id)
                decision = bridges[vehicle_id].evaluate(local)
                backend_sources.add(decision.evidence.source)
                current_fallback_calls[vehicle_id] = decision.evidence.fallback_calls
                final = arbiters[vehicle_id].preflight(
                    env.safety_snapshot(vehicle_id),
                    reflex_override=decision.intent,
                )
                actor_executed = final is None
                stored: dict[str, object] = {
                    "vehicle_id": vehicle_id,
                    "critic_observation": critic_vector.detach().cpu(),
                    "value": value.detach().cpu(),
                    "actor_executed": actor_executed,
                }
                if actor_executed:
                    observation_tensor = torch.tensor(
                        local.actor_vector(), dtype=torch.float32, device=self.device
                    ).reshape(1, 1, -1)
                    hidden_tensor = hidden[vehicle_id].reshape(1, 1, -1)
                    with torch.no_grad():
                        logits, motion_mean, confidence, next_hidden = self.actor(
                            observation_tensor, hidden_tensor
                        )
                        logits = self.actor.mask_skill_logits(
                            logits, observation_tensor[:, -1, :]
                        )
                    skill_distribution = Categorical(logits=logits[0])
                    motion_distribution = Normal(motion_mean[0], 0.15)
                    skill_index = skill_distribution.sample()
                    raw_motion = motion_distribution.sample()
                    bounded_motion = torch.clamp(raw_motion, -1.0, 1.0)
                    old_log_probability = (
                        skill_distribution.log_prob(skill_index)
                        + motion_distribution.log_prob(raw_motion).sum()
                    )
                    proposed = PolicyIntent(
                        tuple(Skill)[int(skill_index.item())],
                        tuple(
                            float(item)
                            for item in bounded_motion.detach().cpu().numpy()
                        ),  # type: ignore[arg-type]
                        float(confidence[0].item()),
                        0.2,
                    )
                    final = arbiters[vehicle_id].resolve(
                        proposed,
                        env.safety_snapshot(vehicle_id),
                        now=(self.environment_steps + batch_step) * env.dt,
                    )
                    actor_executed = not final.overrode
                    stored.update(
                        {
                            "observation": observation_tensor[0, 0].detach().cpu(),
                            "hidden": hidden_tensor[0, 0].detach().cpu(),
                            "skill": skill_index.detach().cpu(),
                            "motion": raw_motion.detach().cpu(),
                            "old_log_probability": old_log_probability.detach().cpu(),
                            "actor_executed": actor_executed,
                        }
                    )
                    hidden[vehicle_id] = next_hidden[0, 0].detach()
                if final is None:
                    raise RuntimeError("safety arbitration did not produce a final action")
                if final.overrode:
                    env.record_safety_override(final.reason)
                    safety_overrides += 1
                actions[vehicle_id] = final.intent
                pending[vehicle_id] = stored

            next_observations, rewards, terminated, truncated, info = env.step(actions)
            central_commands += int(info["central_control_commands"])
            collisions += int(info["safety_failure"] == "collision")
            for vehicle_id, reward in rewards.items():
                total_reward += float(reward)
                for name, amount in info["reward_terms"][vehicle_id].items():
                    reward_terms[name] = reward_terms.get(name, 0.0) + float(amount)
                sample = pending[vehicle_id]
                sample.update(
                    {
                        "reward": float(reward),
                        "done": bool(
                            terminated
                            or truncated
                            or vehicle_id not in next_observations
                        ),
                    }
                )
                samples.append(sample)
            observations = next_observations
            hidden = {
                vehicle_id: hidden.get(
                    vehicle_id,
                    torch.zeros(64, dtype=torch.float32, device=self.device),
                )
                for vehicle_id in observations
            }
            if terminated or truncated:
                completed_fallback_calls += sum(current_fallback_calls.values())
                observations, _ = env.reset(seed=episode_seed + batch_step + 1)
                hidden = {
                    vehicle_id: torch.zeros(
                        64, dtype=torch.float32, device=self.device
                    )
                    for vehicle_id in observations
                }
                bridges = {
                    vehicle_id: self.reflex_factory(vehicle_id, manifest)
                    for vehicle_id in observations
                }
                arbiters = {
                    vehicle_id: SafetyArbiter(SafetyProjector())
                    for vehicle_id in observations
                }
                current_fallback_calls = {
                    vehicle_id: 0 for vehicle_id in observations
                }

        advantages, returns = gae_targets(
            samples, gamma=self.gamma, gae_lambda=self.gae_lambda
        )
        if len(advantages) > 1:
            advantages = (advantages - advantages.mean()) / (
                advantages.std(unbiased=False) + 1e-8
            )
        critic_batch = torch.stack(
            [torch.as_tensor(sample["critic_observation"]) for sample in samples]
        ).to(self.device)
        return_batch = returns.to(self.device)
        actor_indices = [
            index for index, sample in enumerate(samples) if sample["actor_executed"]
        ]

        for _epoch in range(self.update_epochs):
            predicted_values = self.critic(critic_batch)
            value_loss = torch.mean((predicted_values - return_batch) ** 2)
            self.critic_optimizer.zero_grad()
            (self.value_coefficient * value_loss).backward()
            torch.nn.utils.clip_grad_norm_(self.critic.parameters(), 1.0)
            self.critic_optimizer.step()

            if actor_indices:
                observation_batch = torch.stack(
                    [torch.as_tensor(samples[index]["observation"]) for index in actor_indices]
                ).to(self.device)
                hidden_batch = torch.stack(
                    [torch.as_tensor(samples[index]["hidden"]) for index in actor_indices]
                ).to(self.device).unsqueeze(0)
                skill_batch = torch.stack(
                    [torch.as_tensor(samples[index]["skill"]) for index in actor_indices]
                ).long().to(self.device)
                motion_batch = torch.stack(
                    [torch.as_tensor(samples[index]["motion"]) for index in actor_indices]
                ).to(self.device)
                old_log_probability = torch.stack(
                    [
                        torch.as_tensor(samples[index]["old_log_probability"])
                        for index in actor_indices
                    ]
                ).float().to(self.device)
                actor_advantages = advantages[actor_indices].to(self.device)
                logits, motion_mean, _confidence, _next_hidden = self.actor(
                    observation_batch.unsqueeze(1), hidden_batch
                )
                logits = self.actor.mask_skill_logits(logits, observation_batch)
                skill_distribution = Categorical(logits=logits)
                motion_distribution = Normal(motion_mean, 0.15)
                new_log_probability = (
                    skill_distribution.log_prob(skill_batch)
                    + motion_distribution.log_prob(motion_batch).sum(dim=1)
                )
                ratio = torch.exp(new_log_probability - old_log_probability)
                clipped_ratio = torch.clamp(
                    ratio, 1.0 - self.clip_ratio, 1.0 + self.clip_ratio
                )
                policy_loss = -torch.minimum(
                    ratio * actor_advantages, clipped_ratio * actor_advantages
                ).mean()
                entropy = (
                    skill_distribution.entropy().mean()
                    + motion_distribution.entropy().sum(dim=1).mean()
                )
                actor_loss = policy_loss - self.entropy_coefficient * entropy
                self.actor_optimizer.zero_grad()
                actor_loss.backward()
                torch.nn.utils.clip_grad_norm_(self.actor.parameters(), 1.0)
                self.actor_optimizer.step()

        self.global_updates += 1
        self.environment_steps += steps
        self._capture_random_state()
        return BatchTrainingReport(
            manifest_digest=manifest.digest,
            steps=steps,
            actor_samples=len(actor_indices),
            critic_samples=len(samples),
            total_reward=total_reward,
            reward_terms=reward_terms,
            collisions=collisions,
            central_control_commands=central_commands,
            safety_overrides=safety_overrides,
            critic_reset=critic_reset,
            male_cns_backend=(
                ",".join(sorted(backend_sources)) if backend_sources else "unavailable"
            ),
            male_cns_fallbacks=(
                completed_fallback_calls + sum(current_fallback_calls.values())
            ),
        )

    def save(
        self,
        path: str | Path,
        *,
        config_digest: str,
        state_digest: str,
    ) -> Path:
        config = _validate_digest(config_digest, "config_digest")
        state = _validate_digest(state_digest, "state_digest")
        payload = {
            "schema_version": self.schema_version,
            "actor_state_dict": self.actor.state_dict(),
            "critic_state_dict": self.critic.state_dict(),
            "actor_optimizer_state_dict": self.actor_optimizer.state_dict(),
            "critic_optimizer_state_dict": self.critic_optimizer.state_dict(),
            "actor_metadata": {
                "schema_version": self.actor.schema_version,
                "input_dimension": self.actor.input_dimension,
                "hidden_dimension": self.actor.hidden_dimension,
                "skill_dimension": self.actor.skill_dimension,
            },
            "critic_input_dimension": self.critic_input_dimension,
            "global_updates": self.global_updates,
            "environment_steps": self.environment_steps,
            "critic_resets": self.critic_resets,
            "seed": self.seed,
            "hyperparameters": {
                "learning_rate": self.learning_rate,
                "gamma": self.gamma,
                "gae_lambda": self.gae_lambda,
                "clip_ratio": self.clip_ratio,
                "entropy_coefficient": self.entropy_coefficient,
                "value_coefficient": self.value_coefficient,
                "update_epochs": self.update_epochs,
            },
            "random_states": {
                "python": self._python_random_state,
                "numpy": self._numpy_random_state,
                "torch_cpu": self._torch_random_state,
                "torch_cuda": self._cuda_random_states,
            },
            "config_digest": config,
            "curriculum_state_digest": state,
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        torch.save(payload, temporary)
        os.replace(temporary, destination)
        return destination

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        device: str,
        config_digest: str,
        reflex_factory: Callable[[int, ScenarioManifest], object] | None = None,
    ) -> PPOTrainer:
        expected_digest = _validate_digest(config_digest, "config_digest")
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        required = {
            "schema_version",
            "actor_state_dict",
            "critic_state_dict",
            "actor_optimizer_state_dict",
            "critic_optimizer_state_dict",
            "actor_metadata",
            "critic_input_dimension",
            "global_updates",
            "environment_steps",
            "critic_resets",
            "seed",
            "hyperparameters",
            "random_states",
            "config_digest",
            "curriculum_state_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("trainer checkpoint fields are incomplete or unsupported")
        if payload["schema_version"] != cls.schema_version:
            raise ValueError("trainer checkpoint schema is incompatible")
        if payload["config_digest"] != expected_digest:
            raise ValueError("trainer checkpoint config digest mismatch")
        metadata = payload["actor_metadata"]
        expected_metadata = {
            "schema_version": SharedRecurrentPolicy.schema_version,
            "input_dimension": SharedRecurrentPolicy.input_dimension,
            "hidden_dimension": SharedRecurrentPolicy.hidden_dimension,
            "skill_dimension": SharedRecurrentPolicy.skill_dimension,
        }
        if metadata != expected_metadata:
            raise ValueError("trainer checkpoint actor metadata is incompatible")
        hyper = payload["hyperparameters"]
        trainer = cls(
            seed=int(payload["seed"]),
            critic_input_dimension=int(payload["critic_input_dimension"]),
            device=device,
            learning_rate=float(hyper["learning_rate"]),
            gamma=float(hyper["gamma"]),
            gae_lambda=float(hyper["gae_lambda"]),
            clip_ratio=float(hyper["clip_ratio"]),
            entropy_coefficient=float(hyper["entropy_coefficient"]),
            value_coefficient=float(hyper["value_coefficient"]),
            update_epochs=int(hyper["update_epochs"]),
            reflex_factory=reflex_factory,
        )
        trainer.actor.load_state_dict(payload["actor_state_dict"])
        trainer.critic.load_state_dict(payload["critic_state_dict"])
        trainer.actor_optimizer.load_state_dict(payload["actor_optimizer_state_dict"])
        trainer.critic_optimizer.load_state_dict(payload["critic_optimizer_state_dict"])
        trainer.global_updates = int(payload["global_updates"])
        trainer.environment_steps = int(payload["environment_steps"])
        trainer.critic_resets = int(payload["critic_resets"])
        states = payload["random_states"]
        trainer._python_random_state = states["python"]
        trainer._numpy_random_state = states["numpy"]
        trainer._torch_random_state = states["torch_cpu"].clone()
        trainer._cuda_random_states = [
            state.clone() for state in states["torch_cuda"]
        ]
        return trainer

    def export_actor(self, path: str | Path) -> Path:
        destination = Path(path)
        self.actor.export(destination)
        return destination
