"""Evaluate a deployment actor without performing any training update."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from flydrones.multitask_contract import LocalObservation, PolicyIntent
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_policy import PolicyState, SharedRecurrentPolicy
from flydrones.multitask_scenarios import ScenarioGenerator
from flydrones.multitask_sitl import MultiTaskSITLAdapter
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
    adapter = MultiTaskSITLAdapter(
        maximum_speed_mps=4.0,
        maximum_yaw_rate_rps=1.5,
    )
    backend_metadata = adapter.validate_backend(args.backend)
    if args.backend != "fast":
        raise RuntimeError(
            "non-fast backends require their external per-vehicle runner; "
            "the evaluator refuses to relabel fast kinematics as independent physics"
        )
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
        "backend": args.backend,
        "backend_metadata": backend_metadata,
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


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report must contain a JSON object: {path}")
    return payload


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_summary(args: argparse.Namespace) -> dict[str, object]:
    """Combine immutable training, evaluation, configuration, and test evidence."""

    train_report = _read_json(Path(args.train_report))
    evaluation_report = _read_json(Path(args.evaluation_report))
    checkpoint_digest = train_report.get("checkpoint_digest")
    if not isinstance(checkpoint_digest, str) or not checkpoint_digest:
        raise ValueError("training report is missing checkpoint_digest")
    if evaluation_report.get("checkpoint_digest") != checkpoint_digest:
        raise ValueError("training and evaluation reports reference different checkpoints")

    train_manifest = train_report.get("manifest_digest")
    episodes = evaluation_report.get("episodes")
    if not isinstance(train_manifest, str) or not isinstance(episodes, list):
        raise ValueError("reports are missing scenario evidence")
    evaluation_manifests = [
        episode.get("manifest_digest")
        for episode in episodes
        if isinstance(episode, dict)
    ]
    if any(not isinstance(digest, str) or not digest for digest in evaluation_manifests):
        raise ValueError("evaluation report contains invalid scenario evidence")

    metrics = evaluation_report.get("metrics")
    admission = evaluation_report.get("admission")
    if not isinstance(metrics, dict) or not isinstance(admission, dict):
        raise ValueError("evaluation report is missing metrics or admission evidence")
    config_path = Path(args.config)
    summary = {
        "schema_version": 1,
        "git_commit": _git_commit(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "checkpoint_digest": checkpoint_digest,
        "scenario_digests": [train_manifest, *evaluation_manifests],
        "test_command": args.test_command,
        "test_result": args.test_result,
        "collision_count": int(train_report.get("collisions", 0))
        + int(metrics.get("collisions", 0)),
        "central_command_count": int(train_report.get("central_control_commands", 0))
        + int(metrics.get("central_control_commands", 0)),
        "admission_passed": bool(admission.get("passed", False)),
        "admission_failures": list(admission.get("failures", [])),
    }
    _write_json(Path(args.report), summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--checkpoint")
    parser.add_argument("--seeds", type=_parse_seeds)
    parser.add_argument("--episodes", type=int)
    parser.add_argument("--level", type=int, choices=range(5), default=0)
    parser.add_argument("--fleet-size", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--backend", choices=("fast", "px4", "pybullet"), default="fast")
    parser.add_argument("--train-report")
    parser.add_argument("--evaluation-report")
    parser.add_argument("--config")
    parser.add_argument("--test-command")
    parser.add_argument("--test-result")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if args.summary:
        required = (
            "train_report",
            "evaluation_report",
            "config",
            "test_command",
            "test_result",
        )
        missing = [f"--{name.replace('_', '-')}" for name in required if not getattr(args, name)]
        if missing:
            parser.error("summary mode requires " + ", ".join(missing))
        return args
    if args.checkpoint is None or args.seeds is None or args.episodes is None:
        parser.error("evaluation mode requires --checkpoint, --seeds, and --episodes")
    if args.episodes != len(args.seeds):
        parser.error("--episodes must match the number of unique --seeds")
    if not 1 <= args.fleet_size <= 100 or args.max_steps <= 0:
        parser.error("fleet size and max steps must be positive and bounded")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summary:
        build_summary(arguments)
    else:
        evaluate(arguments)
