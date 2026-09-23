"""Evaluate a deployment actor without performing any training update."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from flydrones.multitask_evaluation import evaluate_manifests
from flydrones.multitask_policy import SharedRecurrentPolicy
from flydrones.multitask_scenarios import ScenarioGenerator
from flydrones.multitask_sitl import MultiTaskSITLAdapter


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    manifests = tuple(
        ScenarioGenerator(seed).generate(
            level=args.level,
            fleet_size=args.fleet_size,
        )
        for seed in args.seeds
    )
    evidence = evaluate_manifests(actor, manifests, max_steps=args.max_steps)
    result = evidence.to_dict()
    result.update({
        "backend": args.backend,
        "backend_metadata": backend_metadata,
        "checkpoint_digest": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
    })
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
