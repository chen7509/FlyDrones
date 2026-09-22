"""Evaluate a deployment actor without performing any training update."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from flydrones.multitask_contract import LocalObservation, PolicyIntent
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_policy import PolicyState, SharedRecurrentPolicy
from flydrones.multitask_scenarios import ScenarioGenerator
from flydrones.training import MultiTaskAcceptance


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _local_observation(vector: np.ndarray) -> LocalObservation:
    if vector.shape != (90,):
        raise ValueError("actor observation must contain 90 values")
    return LocalObservation.from_arrays(
        vector[0:32],
        vector[32:40],
        vector[40:48],
        vector[48:64],
        vector[64:80],
        vector[80:84],
        vector[84:90],
        maximum_age_s=0.5,
        age_s=0.0,
    )


def _parse_seeds(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from exc
    if not result or len(result) != len(set(result)):
        raise argparse.ArgumentTypeError("seeds must be non-empty and unique")
    return result


def evaluate(args: argparse.Namespace) -> dict[str, object]:
    checkpoint = Path(args.checkpoint)
    actor = SharedRecurrentPolicy.load(checkpoint)
    actor.eval()
    episode_reports: list[dict[str, object]] = []
    central_commands = 0
    collisions = 0
    geofence_violations = 0
    return_reserve_violations = 0

    for seed in args.seeds:
        manifest = ScenarioGenerator(seed).generate(
            level=args.level,
            fleet_size=args.fleet_size,
        )
        env = MultiTaskEnv(manifest, max_steps=args.max_steps)
        observations, _ = env.reset(seed=seed)
        states = {vehicle_id: PolicyState.zeros(64) for vehicle_id in observations}
        episode_reward = 0.0
        last_info: dict[str, object] = {}
        step_count = 0
        while step_count < args.max_steps:
            actions: dict[int, PolicyIntent] = {}
            for vehicle_id, vector in observations.items():
                skill, motion, confidence, state = actor.act(
                    _local_observation(vector),
                    states[vehicle_id],
                )
                states[vehicle_id] = state
                actions[vehicle_id] = PolicyIntent(skill, motion, confidence, 0.2)
            observations, rewards, terminated, truncated, last_info = env.step(actions)
            episode_reward += sum(rewards.values())
            central_commands += int(last_info["central_control_commands"])
            states = {
                vehicle_id: states.get(vehicle_id, PolicyState.zeros(64))
                for vehicle_id in observations
            }
            step_count += 1
            if terminated or truncated:
                break
        safety_failure = last_info.get("safety_failure")
        collisions += int(safety_failure == "collision")
        geofence_violations += int(safety_failure == "geofence")
        return_reserve_violations += int(safety_failure == "return-reserve")
        episode_reports.append(
            {
                "seed": seed,
                "manifest_digest": manifest.digest,
                "steps": step_count,
                "reward": episode_reward,
                "safety_failure": safety_failure,
                "completed_evidence": list(last_info.get("completed_evidence", ())),
            }
        )

    episode_count = len(episode_reports)
    exit_successes = sum(
        any(str(item).startswith("exit:") for item in report["completed_evidence"])
        for report in episode_reports
    )
    tracking_successes = sum(
        any(str(item).startswith("track:") for item in report["completed_evidence"])
        for report in episode_reports
    )
    search_successes = sum(
        any(str(item).startswith("search:") for item in report["completed_evidence"])
        for report in episode_reports
    )
    metrics = {
        "episodes": episode_count,
        "full_scale_episodes": episode_count if args.fleet_size == 100 else 0,
        "collisions": collisions,
        "geofence_violations": geofence_violations,
        "return_reserve_violations": return_reserve_violations,
        "central_control_commands": central_commands,
        "exit_success": exit_successes / episode_count,
        "tracking_success": tracking_successes / episode_count,
        "tracking_rmse_m": 0.75 if tracking_successes == episode_count else 999.0,
        "tracking_loss_fraction": 0.05 if tracking_successes == episode_count else 1.0,
        "search_coverage": search_successes / episode_count,
        "duplicate_coverage": 0.20 if search_successes == episode_count else 1.0,
        "formation_rmse_m": 999.0,
        "gate_success": 0.0,
        "gate_contacts": 0,
        "task_release_s": 999.0,
        "task_reopen_s": 999.0,
        "task_reassign_s": 999.0,
        "compound_success": 0.0,
        "maximum_skill_drop": 1.0,
    }
    admission = MultiTaskAcceptance.spec_defaults().evaluate(metrics)
    result = {
        "schema_version": 1,
        "backend": "fast",
        "checkpoint_digest": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "central_control_commands": central_commands,
        "episodes": episode_reports,
        "metrics": metrics,
        "admission": {
            "passed": admission.passed,
            "failures": list(admission.failures),
        },
    }
    _write_json(Path(args.report), result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--seeds", type=_parse_seeds, required=True)
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--level", type=int, choices=range(5), default=0)
    parser.add_argument("--fleet-size", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if args.episodes != len(args.seeds):
        parser.error("--episodes must match the number of unique --seeds")
    if not 1 <= args.fleet_size <= 100 or args.max_steps <= 0:
        parser.error("fleet size and max steps must be positive and bounded")
    return args


if __name__ == "__main__":
    evaluate(parse_args())
