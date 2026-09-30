"""Run, resume, or safely restart guarded multi-task curriculum training."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import torch

from flydrones.malecns_policy import MaleCNSPolicy
from flydrones.mission_contract import MissionContract
from flydrones.mission_validation import (
    MissionValidationRunner,
    MissionValidationScenario,
)
from flydrones.multitask_curriculum import (
    CurriculumConfig,
    CurriculumStage,
    CurriculumStore,
    RunLock,
    manifest_for_batch,
    promotion_decision,
)
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_evaluation import evaluate_manifests
from flydrones.multitask_policy import SharedRecurrentPolicy
from flydrones.multitask_reflex import GeometricReflexBridge, MaleCNSReflexBridge
from flydrones.multitask_scenarios import ScenarioGenerator
from flydrones.multitask_summary import write_summary
from flydrones.multitask_trainer import PPOTrainer


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_output(requested: Path, *, restart: bool) -> Path:
    if restart and requested.exists() and any(requested.iterdir()):
        if not (requested / "state.json").is_file():
            raise ValueError(
                "--restart refuses a non-empty directory without curriculum state"
            )
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        return requested / f"restart-{stamp}-{uuid.uuid4().hex[:8]}"
    if not restart and requested.exists() and any(requested.iterdir()):
        if not (requested / "state.json").is_file():
            raise ValueError("output directory is non-empty but has no curriculum state")
    return requested


def _device(requested: str) -> str:
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but unavailable")
    return requested


def _reflex_factory(args: argparse.Namespace) -> Callable | None:
    provided = any(
        value is not None
        for value in (
            args.malecns_connectome,
            args.malecns_config,
            args.malecns_readout,
        )
    )
    if args.reflex_backend == "conventional":
        if provided:
            raise ValueError("MaleCNS paths cannot be used with conventional reflexes")
        return lambda _vehicle_id, _manifest: GeometricReflexBridge()
    if args.reflex_backend == "fail-closed":
        if provided:
            raise ValueError("MaleCNS paths require --reflex-backend malecns")
        return None
    if args.malecns_connectome is None and args.malecns_config is None:
        raise ValueError("the malecns backend requires connectome and config paths")
    if args.malecns_connectome is None or args.malecns_config is None:
        raise ValueError(
            "--malecns-connectome and --malecns-config must be supplied together"
        )

    connectome = Path(args.malecns_connectome)
    brain_config = Path(args.malecns_config)
    readout = None if args.malecns_readout is None else Path(args.malecns_readout)
    for path in (connectome, brain_config, readout):
        if path is not None and not path.is_file():
            raise FileNotFoundError(f"MaleCNS input does not exist: {path}")

    def build(vehicle_id, manifest):
        policy = MaleCNSPolicy.from_files(
            connectome,
            brain_config,
            readout,
            seed=int(manifest.seed) * 1000 + int(vehicle_id),
        )
        return MaleCNSReflexBridge(policy, require_live=True)

    return build


def _mission_contract() -> MissionContract:
    return MissionContract.from_dict(
        {
            "schema_version": 1,
            "mission_id": "curriculum-validation",
            "mission_type": "search_confirm_rally",
            "area_polygon_m": [[0, 0], [40, 0], [40, 40], [0, 40]],
            "search_cell_size_m": 20,
            "target_classes": ["person"],
            "confirmation_quorum": 2,
            "rally_position_m": [50, 20, 20],
            "deadline_s": 60,
            "safety": {
                "maximum_speed_mps": 8,
                "minimum_separation_m": 3,
                "geofence_margin_m": 5,
                "minimum_battery_return_pct": 30,
            },
        }
    )


def _evaluation_manifests(
    stage: CurriculumStage, seeds: Sequence[int]
) -> list:
    manifests = []
    for index, seed in enumerate(seeds):
        fleet = stage.fleets[index % len(stage.fleets)]
        manifests.append(
            ScenarioGenerator(seed).generate(
                level=stage.level,
                fleet_size=fleet,
                active_skills=stage.active_skills,
            )
        )
    return manifests


def _thresholds_pass(stage: CurriculumStage, metrics: Mapping[str, float]) -> tuple[bool, list[str]]:
    maximum_names = {
        "collisions",
        "geofence_violations",
        "return_reserve_violations",
        "central_control_commands",
        "gate_contacts",
        "tracking_rmse_m",
        "tracking_loss_fraction",
        "duplicate_coverage",
        "formation_rmse_m",
    }
    failures: list[str] = []
    for name, threshold in stage.thresholds.items():
        value = metrics.get(name)
        if value is None or not math.isfinite(float(value)):
            failures.append(f"missing-or-non-finite:{name}")
        elif name in maximum_names and float(value) > threshold:
            failures.append(f"maximum:{name}")
        elif name not in maximum_names and float(value) < threshold:
            failures.append(f"minimum:{name}")
    for name in (
        "collisions",
        "geofence_violations",
        "return_reserve_violations",
        "central_control_commands",
        "gate_contacts",
    ):
        value = metrics.get(name)
        if value is None or not math.isfinite(float(value)) or float(value) != 0.0:
            failures.append(f"safety:{name}")
    return not failures, failures


def _success_score(stage: CurriculumStage, metrics: Mapping[str, float]) -> float:
    positive_outcomes = {
        "exit_success",
        "tracking_success",
        "search_coverage",
        "gate_success",
        "compound_success",
    }
    candidates = [
        float(metrics[name])
        for name in stage.thresholds
        if name in metrics and name in positive_outcomes
    ]
    if candidates:
        return min(candidates)

    error_quality = [
        max(0.0, min(1.0, 1.0 - float(metrics[name]) / threshold))
        for name, threshold in stage.thresholds.items()
        if name in metrics and threshold > 0.0
    ]
    return min(error_quality, default=0.0)


def _mission_evidence(seed: int) -> tuple[list[dict[str, object]], bool]:
    runner = MissionValidationRunner(_mission_contract(), vehicle_count=5)
    low = runner.run(
        MissionValidationScenario.low_battery(seed=seed, vehicle_id=1, at_s=5.0)
    )
    partition = runner.run(
        MissionValidationScenario.partition_with_stale_replay(seed=seed + 1)
    )
    passed = (
        low.task_release_s is not None
        and low.task_release_s <= 3.0
        and low.task_reopen_s is not None
        and low.task_reopen_s <= 3.2
        and low.task_reassign_s is not None
        and low.task_reassign_s <= 5.0
        and low.maximum_simultaneous_owners <= 1
        and low.safety_violations == 0
        and low.central_control_commands == 0
        and partition.stale_messages_accepted == 0
        and partition.safety_violations == 0
        and partition.central_control_commands == 0
    )
    return [low.to_dict(), partition.to_dict()], passed


def _load_baselines(output: Path) -> dict[str, float]:
    path = output / "baselines.json"
    if not path.is_file():
        return {}
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("baseline evidence must contain an object")
    return {str(key): float(value) for key, value in values.items()}


def _regression_evidence(
    config: CurriculumConfig,
    profile: str,
    completed_stages: Sequence[str],
    actor,
    reflex_factory: Callable | None,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    stages = config.profiles[profile]
    for completed in completed_stages:
        index = int(completed)
        stage = stages[index]
        evidence = evaluate_manifests(
            actor,
            _evaluation_manifests(stage, stage.regression_seeds),
            reflex_factory=reflex_factory,
            max_steps=max(16, stage.steps_per_batch),
        )
        scores[stage.stage_id] = _success_score(stage, evidence.metrics)
    return scores


def _new_trainer(
    config: CurriculumConfig,
    manifest,
    *,
    device: str,
    reflex_factory: Callable | None,
) -> PPOTrainer:
    environment = MultiTaskEnv(manifest, max_steps=16)
    environment.reset(seed=manifest.seed)
    critic_dimension = int(environment.critic_observation().shape[0])
    options = dict(config.algorithm)
    options.pop("name", None)
    return PPOTrainer(
        seed=config.seed,
        critic_input_dimension=critic_dimension,
        device=device,
        reflex_factory=reflex_factory,
        **options,
    )


def _record_failure(output: Path, exc: BaseException) -> None:
    try:
        payload = {
            "schema_version": 1,
            "type": type(exc).__name__,
            "message": str(exc),
            "time_ns": time.time_ns(),
        }
        _atomic_json(output / "failures" / f"failure-{time.time_ns()}.json", payload)
    except OSError:
        pass


def run(args: argparse.Namespace) -> dict[str, object]:
    requested = Path(args.output).resolve()
    output = _resolve_output(requested, restart=args.restart)
    config = CurriculumConfig.load(args.config)
    device = _device(args.device)
    reflex_factory = _reflex_factory(args)
    committed = 0

    try:
        with RunLock(output):
            store = CurriculumStore(output)
            settings_path = output / "run-settings.json"
            settings = {
                "schema_version": 1,
                "reflex_backend": args.reflex_backend,
            }
            if store.state_path.is_file():
                if settings_path.is_file():
                    committed_settings = json.loads(
                        settings_path.read_text(encoding="utf-8")
                    )
                    if committed_settings != settings:
                        raise ValueError(
                            "reflex backend differs from committed run settings"
                        )
                elif args.reflex_backend != "fail-closed":
                    raise ValueError(
                        "existing run has no compatible reflex backend setting"
                    )
                else:
                    _atomic_json(settings_path, settings)
                state = store.load(config)
                if state.profile != args.profile:
                    raise ValueError("curriculum profile differs from committed state")
                if args.restart:
                    raise ValueError("restart target unexpectedly contains state")
                trainer = PPOTrainer.load(
                    output / str(state.latest_checkpoint),
                    device=device,
                    config_digest=config.digest,
                    reflex_factory=reflex_factory,
                )
            else:
                _atomic_json(settings_path, settings)
                first_manifest = manifest_for_batch(
                    config, args.profile, stage_index=0, batch_index=0
                )
                trainer = _new_trainer(
                    config,
                    first_manifest,
                    device=device,
                    reflex_factory=reflex_factory,
                )
                initial_actor = output / "best-actor.pt"
                trainer.export_actor(initial_actor)
                state = store.initialize(
                    config, profile=args.profile, best_actor=initial_actor.name
                )

            while committed < args.max_batches:
                stages = config.profiles[state.profile]
                if state.stage_index >= len(stages):
                    break
                stage = stages[state.stage_index]
                if state.batch_index >= stage.maximum_batches:
                    break
                manifest = manifest_for_batch(
                    config,
                    state.profile,
                    stage_index=state.stage_index,
                    batch_index=state.batch_index,
                )
                manifest_path = output / "manifests" / (
                    f"batch-{state.stage_index}-{state.batch_index}.json"
                )
                _atomic_json(manifest_path, manifest.to_dict())
                training = trainer.train_batch(manifest, steps=stage.steps_per_batch)
                candidates = output / ".candidates"
                trainer_path = candidates / (
                    f"trainer-{state.stage_index}-{state.batch_index}.pt"
                )
                actor_path = candidates / (
                    f"actor-{state.stage_index}-{state.batch_index}.pt"
                )
                trainer.save(
                    trainer_path,
                    config_digest=config.digest,
                    state_digest=state.digest,
                )
                trainer.export_actor(actor_path)
                evaluation_actor = SharedRecurrentPolicy.load(actor_path)
                evaluation = evaluate_manifests(
                    evaluation_actor,
                    _evaluation_manifests(stage, stage.eval_seeds),
                    reflex_factory=reflex_factory,
                    max_steps=max(16, stage.steps_per_batch),
                )
                missions, mission_passed = _mission_evidence(
                    config.seed + state.last_committed_batch + 1
                )
                thresholds_passed, threshold_failures = _thresholds_pass(
                    stage, evaluation.metrics
                )
                live_backend = (
                    evaluation.male_cns_backend == "malecns-v1.0-live"
                    and evaluation.male_cns_fallbacks == 0
                    and evaluation.reflex_calls == evaluation.local_decisions
                )
                curriculum_gate = thresholds_passed and mission_passed
                baselines = _load_baselines(output)
                regressions = _regression_evidence(
                    config,
                    state.profile,
                    state.completed_stages,
                    evaluation_actor,
                    reflex_factory,
                )
                decision = promotion_decision(
                    current={
                        "admission_passed": curriculum_gate,
                        "success": _success_score(stage, evaluation.metrics),
                    },
                    baselines=baselines,
                    regressions=regressions,
                    maximum_drop=float(config.deployment["maximum_skill_drop"]),
                )
                curriculum_eligible = (
                    decision.promote and state.batch_index + 1 >= stage.patience
                )
                deployment_eligible = curriculum_eligible and live_backend
                reasons = list(decision.reasons)
                if decision.promote and not curriculum_eligible:
                    reasons.append("patience")
                if curriculum_eligible and not live_backend:
                    reasons.append("male-cns-backend")
                report = {
                    "schema_version": 1,
                    "run_id": state.run_id,
                    "profile": state.profile,
                    "stage_id": stage.stage_id,
                    "stage_index": state.stage_index,
                    "batch_index": state.batch_index,
                    "manifest": manifest.to_dict(),
                    "manifest_digest": manifest.digest,
                    "config_digest": config.digest,
                    "trainer_checkpoint_digest": _sha256(trainer_path),
                    "candidate_actor_digest": _sha256(actor_path),
                    "training": training.to_dict(),
                    "evaluation": evaluation.to_dict(),
                    "mission_validation": missions,
                    "promotion": {
                        "promoted": deployment_eligible,
                        "curriculum_advanced": curriculum_eligible,
                        "reasons": reasons,
                        "threshold_failures": threshold_failures,
                        "mission_passed": mission_passed,
                        "live_malecns": live_backend,
                        "regressions": regressions,
                        "score": decision.score,
                    },
                }
                _atomic_json(
                    output
                    / "reports"
                    / f"regression-{state.stage_index}-{state.batch_index}.json",
                    {
                        "schema_version": 1,
                        "baselines": baselines,
                        "regressions": regressions,
                        "maximum_drop": config.deployment["maximum_skill_drop"],
                    },
                )
                if curriculum_eligible:
                    updated = dict(baselines)
                    updated[stage.stage_id] = decision.score
                    _atomic_json(output / "baselines.json", updated)
                previous_stage = state.stage_index
                state = store.commit_batch(
                    state,
                    trainer_checkpoint=trainer_path,
                    report=report,
                    global_updates=trainer.global_updates,
                    environment_steps=trainer.environment_steps,
                    best_actor=actor_path if deployment_eligible else None,
                    best_score=decision.score if deployment_eligible else None,
                    stage_completed=curriculum_eligible,
                )
                committed += 1
                if args.stop_after_stage and state.stage_index != previous_stage:
                    break

        return {
            "output_directory": str(output),
            "batches_committed": committed,
            "last_committed_batch": state.last_committed_batch,
            "stage_index": state.stage_index,
            "batch_index": state.batch_index,
            "device": device,
        }
    except BaseException as exc:
        _record_failure(output, exc)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", choices=("smoke", "desktop", "full"), default="smoke")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--restart", action="store_true")
    parser.add_argument("--max-batches", type=_positive_int, default=1)
    parser.add_argument("--stop-after-stage", action="store_true")
    parser.add_argument("--malecns-connectome")
    parser.add_argument("--malecns-config")
    parser.add_argument("--malecns-readout")
    parser.add_argument(
        "--reflex-backend",
        choices=("fail-closed", "conventional", "malecns"),
        default="fail-closed",
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--verification-record")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        parsed = parse_args()
        if parsed.summary:
            if parsed.verification_record is None:
                raise ValueError("--summary requires --verification-record")
            destination = write_summary(
                parsed.config, parsed.output, parsed.verification_record
            )
            print(json.dumps({"summary": str(destination)}, sort_keys=True))
        else:
            print(json.dumps(run(parsed), sort_keys=True))
    except BaseException as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
