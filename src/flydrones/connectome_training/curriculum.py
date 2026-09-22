from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .curriculum_config import CurriculumConfig, CurriculumStage
from .curriculum_state import CurriculumState, RunLock, StateStore


class TrainingSession(Protocol):
    model_identity: str

    def train_batch(
        self, stage: CurriculumStage, seed: int
    ) -> Mapping[str, object]: ...

    def evaluate(self, stage: CurriculumStage) -> Mapping[str, object]: ...

    def save_checkpoint(self, path: Path, metadata: dict) -> None: ...

    def restore_checkpoint(self, path: Path) -> None: ...


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _artifact_path(root: Path, parent: str, stem: str, suffix: str = "") -> Path:
    directory = root / parent
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(10_000):
        candidate = directory / f"{stem}-attempt-{attempt:03d}{suffix}"
        if not candidate.exists() and not candidate.with_name(
            candidate.name + ".writing"
        ).exists():
            return candidate
    raise RuntimeError(f"too many orphan artifacts for {stem}")


def _metrics(value: Mapping[str, object]) -> dict[str, float | bool]:
    required = {
        "validation_loss",
        "initial_validation_loss",
        "parameters_finite",
    }
    missing = required - set(value)
    if missing:
        raise ValueError(f"evaluation metrics missing: {', '.join(sorted(missing))}")
    validation_loss = float(value["validation_loss"])
    initial_loss = float(value["initial_validation_loss"])
    if not math.isfinite(validation_loss) or not math.isfinite(initial_loss):
        raise ValueError("evaluation losses must be finite")
    if validation_loss < 0 or initial_loss <= 0:
        raise ValueError("evaluation losses have invalid range")
    return {
        "validation_loss": validation_loss,
        "initial_validation_loss": initial_loss,
        "parameters_finite": bool(value["parameters_finite"]),
    }


def _gate(stage: CurriculumStage, metrics: Mapping[str, object]) -> list[str]:
    parsed = _metrics(metrics)
    failures = []
    if not parsed["parameters_finite"]:
        failures.append("parameters_finite")
    validation_loss = float(parsed["validation_loss"])
    initial_loss = float(parsed["initial_validation_loss"])
    if validation_loss > stage.maximum_validation_loss:
        failures.append("maximum_validation_loss")
    if validation_loss / initial_loss > stage.maximum_loss_ratio:
        failures.append("maximum_loss_ratio")
    return failures


def _initial_state(config: CurriculumConfig, model_identity: str) -> CurriculumState:
    return CurriculumState(
        run_id=uuid4().hex,
        config_digest=config.digest,
        profile=config.profile.name,
        status="COMMITTED",
        stage_index=0,
        batch_index=0,
        global_updates=0,
        environment_steps=0,
        latest_checkpoint=None,
        best_checkpoint=None,
        best_score=None,
        completed_stages=(),
        failed_attempts=0,
        last_committed_batch=None,
        baseline_losses={},
        model_identity=model_identity,
    )


def run_curriculum(
    config: CurriculumConfig,
    output: str | Path,
    session: TrainingSession,
    *,
    max_batches: int | None = None,
) -> CurriculumState:
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive")
    root = Path(output)
    with RunLock(root):
        store = StateStore(root, config.digest)
        state = store.load() or _initial_state(config, session.model_identity)
        if state.model_identity != session.model_identity:
            raise ValueError("curriculum model identity mismatch")
        if state.status in {"COMPLETE", "FAILED"}:
            return state
        if state.latest_checkpoint is not None:
            session.restore_checkpoint(root / state.latest_checkpoint)

        executed = 0
        while state.stage_index < len(config.stages):
            if max_batches is not None and executed >= max_batches:
                return state
            stage = config.stages[state.stage_index]
            batch = state.batch_index
            seed = stage.train_seeds[batch % len(stage.train_seeds)]
            train_metrics = dict(session.train_batch(stage, seed))
            updates = int(train_metrics.get("updates", 0))
            environment_steps = int(train_metrics.get("environment_steps", 0))
            if updates < 0 or environment_steps < 0:
                raise ValueError("training counters must be non-negative")

            current = _metrics(session.evaluate(stage))
            gate_failures = _gate(stage, current)
            regression = {}
            regression_failures = []
            if not gate_failures:
                for completed in state.completed_stages:
                    completed_stage = next(
                        item for item in config.stages if item.id == completed
                    )
                    result = _metrics(session.evaluate(completed_stage))
                    regression[completed] = result
                    baseline = state.baseline_losses[completed]
                    if (
                        float(result["validation_loss"])
                        > baseline * stage.maximum_regression_ratio
                    ):
                        regression_failures.append(completed)

            stem = f"stage-{state.stage_index:03d}-{stage.id}-batch-{batch:03d}"
            checkpoint = _artifact_path(root, "checkpoints", stem)
            session.save_checkpoint(
                checkpoint,
                {
                    "run_id": state.run_id,
                    "config_digest": config.digest,
                    "model_identity": session.model_identity,
                    "stage_id": stage.id,
                    "stage_index": state.stage_index,
                    "batch_index": batch,
                    "seed": seed,
                },
            )
            checkpoint_relative = _relative(root, checkpoint)
            promoted = not gate_failures and not regression_failures
            completed_stages = state.completed_stages
            baseline_losses = dict(state.baseline_losses)
            best_checkpoint = state.best_checkpoint
            best_score = state.best_score
            failed_attempts = state.failed_attempts
            next_stage = state.stage_index
            next_batch = batch + 1
            latest_checkpoint = checkpoint_relative
            status = "COMMITTED"

            if promoted:
                completed_stages = (*completed_stages, stage.id)
                baseline_losses[stage.id] = float(current["validation_loss"])
                best_checkpoint = checkpoint_relative
                best_score = -float(current["validation_loss"])
                next_stage += 1
                next_batch = 0
                if next_stage == len(config.stages):
                    status = "COMPLETE"
            else:
                failed_attempts += 1
                if regression_failures:
                    if best_checkpoint is None:
                        raise RuntimeError("regression rollback requires a best checkpoint")
                    session.restore_checkpoint(root / best_checkpoint)
                    latest_checkpoint = best_checkpoint
                if next_batch >= stage.max_batches:
                    status = "FAILED"

            report_path = _artifact_path(root, "reports", stem, ".json")
            _write_json(
                report_path,
                {
                    "schema": "flydrones-connectome-curriculum-batch-v1",
                    "run_id": state.run_id,
                    "config_digest": config.digest,
                    "model_identity": session.model_identity,
                    "stage_id": stage.id,
                    "stage_index": state.stage_index,
                    "batch_index": batch,
                    "seed": seed,
                    "train_metrics": train_metrics,
                    "current_metrics": current,
                    "gate_failures": gate_failures,
                    "regression_metrics": regression,
                    "regression_failures": regression_failures,
                    "candidate_checkpoint": checkpoint_relative,
                    "promoted": promoted,
                },
            )
            state = CurriculumState(
                run_id=state.run_id,
                config_digest=config.digest,
                profile=config.profile.name,
                status=status,
                stage_index=next_stage,
                batch_index=next_batch,
                global_updates=state.global_updates + updates,
                environment_steps=state.environment_steps + environment_steps,
                latest_checkpoint=latest_checkpoint,
                best_checkpoint=best_checkpoint,
                best_score=best_score,
                completed_stages=completed_stages,
                failed_attempts=failed_attempts,
                last_committed_batch=f"{stage.id}:{batch}",
                baseline_losses=baseline_losses,
                model_identity=session.model_identity,
            )
            store.commit(state)
            executed += 1
            if status in {"COMPLETE", "FAILED"}:
                return state
        return state
