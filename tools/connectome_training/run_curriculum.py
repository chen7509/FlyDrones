from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from flydrones.connectome_training.curriculum import run_curriculum
from flydrones.connectome_training.curriculum_config import load_curriculum_config
from flydrones.connectome_training.curriculum_session import (
    ConnectomeCurriculumSession,
)
from flydrones.connectome_training.model import DYNAMICS_FORMATS, TOPOLOGY_FORMATS
from flydrones.connectome_training.role_comparison import run_role_comparison
from flydrones.connectome_training.training_roles import DEFAULT_LEARNING_PROFILE, ROLE_PROFILES


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a resumable offline connectome curriculum.")
    parser.add_argument("--config", default="configs/connectome_curriculum_v1.yaml")
    parser.add_argument("--profile", choices=("smoke", "desktop", "full"), default="smoke")
    parser.add_argument("--output", default="results/connectome-curriculum-smoke")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--max-batches", type=_positive_int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--learning-rate", type=float, default=0.03)
    roles = parser.add_mutually_exclusive_group()
    roles.add_argument("--learning-profile", choices=tuple(ROLE_PROFILES), default=DEFAULT_LEARNING_PROFILE)
    roles.add_argument(
        "--compare-learning-roles",
        action="store_true",
        help="Run a fresh one-shot internal three-role comparison; requires --max-batches.",
    )
    parser.add_argument("--topology-format", choices=TOPOLOGY_FORMATS, default="coo_reference")
    parser.add_argument("--dynamics-format", choices=DYNAMICS_FORMATS, default="clipped-euler-v1")
    parser.add_argument("--truncate-steps", type=_positive_int, default=4)
    parser.add_argument("--connectome", default="data/malecns_full.npz")
    parser.add_argument(
        "--parameters",
        default="results/connectome-training/stage-b/full-initialization",
    )
    return parser.parse_args()


def _restart(output: Path) -> None:
    if not output.exists():
        return
    if (output / "run.lock").exists():
        raise RuntimeError(f"curriculum output is already locked: {output / 'run.lock'}")
    resolved = output.resolve()
    if resolved == Path.cwd().resolve() or resolved.parent == resolved:
        raise ValueError("refusing to restart an unsafe output path")
    ignore_policy = None
    ignore_path = resolved / ".gitignore"
    if ignore_path.is_file():
        ignore_policy = ignore_path.read_text(encoding="utf-8")
    shutil.rmtree(resolved)
    if ignore_policy is not None:
        resolved.mkdir(parents=True)
        (resolved / ".gitignore").write_text(ignore_policy, encoding="utf-8")


def _write_summary(output: Path, state, evidence_class: str) -> None:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((output / "reports").glob("*.json"))]
    stage_results = {
        report["stage_id"]: {
            "validation_loss": report["current_metrics"]["validation_loss"],
            "gate_failures": report["gate_failures"],
            "regression_failures": report["regression_failures"],
            "promoted": report["promoted"],
        }
        for report in reports
    }
    summary = {
        "schema": "flydrones-connectome-curriculum-summary-v1",
        "evidence_class": evidence_class,
        "repository_artifact_scope": "summary-only",
        "measured_batches": len(reports),
        "total_training_wall_s": sum(float(report["train_metrics"]["elapsed_wall_s"]) for report in reports),
        "peak_process_memory_bytes": max(
            (int(report["train_metrics"]["peak_process_memory_bytes"]) for report in reports),
            default=0,
        ),
        "peak_cuda_memory_bytes": max(
            (int(report["train_metrics"]["peak_cuda_memory_bytes"]) for report in reports),
            default=0,
        ),
        "stage_results": stage_results,
        **asdict(state),
    }
    temporary = output / "summary.json.writing"
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output / "summary.json")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    compare = getattr(args, "compare_learning_roles", False)
    if compare and args.restart:
        raise ValueError("role comparison cannot restart or resume an experiment")
    if compare and args.max_batches is None:
        raise ValueError("role comparison requires --max-batches")
    if args.restart:
        _restart(output)
    config = load_curriculum_config(args.config, args.profile)
    if compare:
        result = run_role_comparison(
            config,
            output,
            max_batches=args.max_batches,
            device=args.device,
            learning_rate=args.learning_rate,
            truncate_steps=args.truncate_steps,
            connectome_path=args.connectome,
            parameters_path=args.parameters,
            topology_format=args.topology_format,
            dynamics_format=args.dynamics_format,
        )
        print(
            json.dumps(
                {"output": str(output), "status": result["status"], "all_curricula_complete": result["all_curricula_complete"]}
            )
        )
        if any(row["state"]["status"] == "FAILED" for row in result["variants"]):
            raise SystemExit(2)
        return
    session = ConnectomeCurriculumSession(
        config,
        device=args.device,
        learning_rate=args.learning_rate,
        learning_profile=args.learning_profile,
        topology_format=getattr(args, "topology_format", "coo_reference"),
        dynamics_format=getattr(args, "dynamics_format", "clipped-euler-v1"),
        truncate_steps=args.truncate_steps,
        connectome_path=args.connectome,
        parameters_path=args.parameters,
    )
    state = run_curriculum(
        config,
        output,
        session,
        max_batches=args.max_batches,
    )
    evidence_class = (
        "synthetic-connectome-curriculum-smoke"
        if config.profile.data_mode == "synthetic-smoke"
        else "offline-complete-connectome-sequence-curriculum"
    )
    _write_summary(output, state, evidence_class)
    print(
        json.dumps(
            {
                "output": str(output),
                "status": state.status,
                "completed_stages": list(state.completed_stages),
                "model_identity": state.model_identity,
            }
        )
    )
    if state.status == "FAILED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
