"""Run one resumable PPO batch in the fast compound-task simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import torch

from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_scenarios import ScenarioGenerator
from flydrones.multitask_trainer import PPOTrainer, gae_targets


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


def _gae_targets(
    samples: list[Mapping[str, object]],
    *,
    gamma: float,
    gae_lambda: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Backward-compatible public wrapper for per-vehicle GAE."""
    return gae_targets(samples, gamma=gamma, gae_lambda=gae_lambda)


def _training_config_digest(args: argparse.Namespace) -> str:
    payload = {
        "schema_version": 1,
        "level": args.level,
        "seed": args.seed,
        "fleet_size": args.fleet_size,
        "learning_rate": args.learning_rate,
        "device": args.device,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def train(args: argparse.Namespace) -> dict[str, object]:
    manifest = ScenarioGenerator(args.seed).generate(
        level=args.level,
        fleet_size=args.fleet_size,
    )
    environment = MultiTaskEnv(manifest, max_steps=max(args.steps, 16))
    environment.reset(seed=args.seed)
    critic_dimension = int(environment.critic_observation().shape[0])
    config_digest = _training_config_digest(args)
    actor_path = Path(args.checkpoint)
    trainer_path = (
        Path(args.trainer_checkpoint)
        if args.trainer_checkpoint
        else actor_path.with_suffix(actor_path.suffix + ".trainer.pt")
    )
    if args.resume:
        if not trainer_path.is_file():
            raise FileNotFoundError(f"trainer checkpoint does not exist: {trainer_path}")
        trainer = PPOTrainer.load(
            trainer_path,
            device=args.device,
            config_digest=config_digest,
        )
    else:
        trainer = PPOTrainer(
            seed=args.seed,
            critic_input_dimension=critic_dimension,
            device=args.device,
            learning_rate=args.learning_rate,
        )
    batch = trainer.train_batch(manifest, steps=args.steps)
    trainer.save(
        trainer_path,
        config_digest=config_digest,
        state_digest=manifest.digest,
    )
    trainer.export_actor(actor_path)
    checkpoint_digest = hashlib.sha256(actor_path.read_bytes()).hexdigest()
    report = {
        "schema_version": 2,
        "seed": args.seed,
        "level": args.level,
        "fleet_size": args.fleet_size,
        "steps": args.steps,
        "manifest_digest": manifest.digest,
        "code_version": _code_version(),
        "checkpoint_digest": checkpoint_digest,
        "trainer_checkpoint_digest": hashlib.sha256(
            trainer_path.read_bytes()
        ).hexdigest(),
        "config_digest": config_digest,
        "global_updates": trainer.global_updates,
        "environment_steps": trainer.environment_steps,
        **batch.to_dict(),
        "ppo": {
            "gamma": trainer.gamma,
            "gae_lambda": trainer.gae_lambda,
            "clip_ratio": trainer.clip_ratio,
            "entropy_coefficient": trainer.entropy_coefficient,
            "value_coefficient": trainer.value_coefficient,
            "update_epochs": trainer.update_epochs,
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
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--trainer-checkpoint")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
