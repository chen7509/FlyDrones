"""Strict curriculum configuration, deterministic scheduling, and atomic state."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import socket
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import yaml

from .multitask_contract import ScenarioManifest, Skill
from .multitask_scenarios import LEVEL_SKILL_COUNTS, ScenarioGenerator
from .training import MultiTaskAcceptance


def _canonical_digest(payload: Mapping[str, object]) -> str:
    data = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(data).hexdigest()


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _integer_tuple(values: object, name: str) -> tuple[int, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"{name} must be a non-empty array")
    result = tuple(_positive_integer(value, name) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} contains duplicates")
    return result


@dataclass(frozen=True)
class CurriculumStage:
    stage_id: str
    index: int
    level: int
    active_skills: tuple[Skill, ...]
    fleets: tuple[int, ...]
    train_seeds: tuple[int, ...]
    eval_seeds: tuple[int, ...]
    regression_seeds: tuple[int, ...]
    steps_per_batch: int
    maximum_batches: int
    patience: int
    thresholds: Mapping[str, float]

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CurriculumStage:
        expected = {
            "id",
            "index",
            "level",
            "active_skills",
            "fleets",
            "train_seeds",
            "eval_seeds",
            "regression_seeds",
            "steps_per_batch",
            "maximum_batches",
            "patience",
            "thresholds",
        }
        if set(values) != expected:
            raise ValueError("curriculum stage keys differ from schema")
        stage_id = values["id"]
        if not isinstance(stage_id, str) or not stage_id:
            raise ValueError("stage id must be a non-empty string")
        index = values["index"]
        level = values["level"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("stage index must be non-negative")
        if isinstance(level, bool) or not isinstance(level, int) or level not in LEVEL_SKILL_COUNTS:
            raise ValueError("stage level must be between zero and four")
        raw_skills = values["active_skills"]
        if not isinstance(raw_skills, (list, tuple)):
            raise ValueError("active_skills must be an array")
        try:
            skills = tuple(Skill(item) for item in raw_skills)
        except (TypeError, ValueError) as exc:
            raise ValueError("active_skills contains an unsupported skill") from exc
        if len(skills) != LEVEL_SKILL_COUNTS[level] or len(set(skills)) != len(skills):
            raise ValueError("active_skills must be unique and match stage level")
        fleets = _integer_tuple(values["fleets"], "fleets")
        if any(fleet > 100 for fleet in fleets):
            raise ValueError("fleet sizes cannot exceed 100")
        train = _integer_tuple(values["train_seeds"], "train_seeds")
        evaluate = _integer_tuple(values["eval_seeds"], "eval_seeds")
        regress = _integer_tuple(values["regression_seeds"], "regression_seeds")
        if set(train) & set(evaluate) or set(train) & set(regress) or set(evaluate) & set(regress):
            raise ValueError("training, evaluation, and regression seeds overlap")
        raw_thresholds = values["thresholds"]
        if not isinstance(raw_thresholds, Mapping) or not raw_thresholds:
            raise ValueError("thresholds must be a non-empty mapping")
        thresholds: dict[str, float] = {}
        for key, value in raw_thresholds.items():
            if not isinstance(key, str) or not key:
                raise ValueError("threshold names must be non-empty")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"threshold {key} must be finite")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"threshold {key} must be finite")
            thresholds[key] = number
        return cls(
            stage_id,
            index,
            level,
            skills,
            fleets,
            train,
            evaluate,
            regress,
            _positive_integer(values["steps_per_batch"], "steps_per_batch"),
            _positive_integer(values["maximum_batches"], "maximum_batches"),
            _positive_integer(values["patience"], "patience"),
            MappingProxyType(dict(sorted(thresholds.items()))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.stage_id,
            "index": self.index,
            "level": self.level,
            "active_skills": [skill.value for skill in self.active_skills],
            "fleets": list(self.fleets),
            "train_seeds": list(self.train_seeds),
            "eval_seeds": list(self.eval_seeds),
            "regression_seeds": list(self.regression_seeds),
            "steps_per_batch": self.steps_per_batch,
            "maximum_batches": self.maximum_batches,
            "patience": self.patience,
            "thresholds": dict(self.thresholds),
        }


@dataclass(frozen=True)
class CurriculumConfig:
    schema_version: int
    seed: int
    algorithm: Mapping[str, object]
    frozen: tuple[str, ...]
    deployment: Mapping[str, object]
    acceptance: MultiTaskAcceptance
    profiles: Mapping[str, tuple[CurriculumStage, ...]]

    @classmethod
    def load(cls, path: str | Path) -> CurriculumConfig:
        values = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(values, Mapping):
            raise ValueError("curriculum config must contain an object")
        return cls.from_dict(values)

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CurriculumConfig:
        expected = {
            "schema_version",
            "seed",
            "algorithm",
            "frozen",
            "deployment",
            "acceptance",
            "profiles",
        }
        if set(values) != expected:
            raise ValueError("curriculum config keys differ from schema")
        if values["schema_version"] != 2:
            raise ValueError("only curriculum schema version 2 is supported")
        seed = values["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        algorithm = values["algorithm"]
        deployment = values["deployment"]
        if not isinstance(algorithm, Mapping) or not isinstance(deployment, Mapping):
            raise ValueError("algorithm and deployment must be mappings")
        raw_frozen = values["frozen"]
        if (
            not isinstance(raw_frozen, (list, tuple))
            or not raw_frozen
            or any(not isinstance(item, str) or not item for item in raw_frozen)
        ):
            raise ValueError("frozen must contain layer names")
        raw_profiles = values["profiles"]
        if not isinstance(raw_profiles, Mapping) or not raw_profiles:
            raise ValueError("profiles must be a non-empty mapping")
        profiles: dict[str, tuple[CurriculumStage, ...]] = {}
        for name, raw_stages in raw_profiles.items():
            if not isinstance(name, str) or not name:
                raise ValueError("profile names must be non-empty")
            if not isinstance(raw_stages, Sequence) or isinstance(raw_stages, (str, bytes)):
                raise ValueError(f"profile {name} must contain stages")
            stages = tuple(CurriculumStage.from_dict(stage) for stage in raw_stages)
            if not stages:
                raise ValueError(f"profile {name} must contain stages")
            if [stage.index for stage in stages] != list(range(len(stages))):
                raise ValueError(f"profile {name} stage indices must be sequential")
            if len({stage.stage_id for stage in stages}) != len(stages):
                raise ValueError(f"profile {name} contains duplicate stage IDs")
            fleet_limit = 5 if name == "smoke" else 20 if name == "desktop" else 100
            if name != "full" and any(
                fleet == 100 for stage in stages for fleet in stage.fleets
            ):
                raise ValueError(f"profile {name} cannot contain 100 aircraft")
            if any(fleet > fleet_limit for stage in stages for fleet in stage.fleets):
                raise ValueError(
                    f"profile {name} cannot contain fleet size above {fleet_limit}"
                )
            profiles[name] = stages
        acceptance = values["acceptance"]
        if not isinstance(acceptance, dict):
            raise ValueError("acceptance must be a mapping")
        return cls(
            2,
            seed,
            MappingProxyType(dict(algorithm)),
            tuple(raw_frozen),
            MappingProxyType(dict(deployment)),
            MultiTaskAcceptance.from_dict(acceptance),
            MappingProxyType(dict(sorted(profiles.items()))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "algorithm": dict(self.algorithm),
            "frozen": list(self.frozen),
            "deployment": dict(self.deployment),
            "acceptance": {
                "minimums": dict(self.acceptance.minimums),
                "maximums": dict(self.acceptance.maximums),
                "zeros": list(self.acceptance.zeros),
            },
            "profiles": {
                name: [stage.to_dict() for stage in stages]
                for name, stages in self.profiles.items()
            },
        }

    @property
    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class CurriculumState:
    schema_version: int
    run_id: str
    config_digest: str
    profile: str
    stage_index: int
    batch_index: int
    global_updates: int
    environment_steps: int
    latest_checkpoint: str | None
    latest_checkpoint_digest: str | None
    best_actor: str | None
    best_score: float | None
    completed_stages: tuple[str, ...]
    failed_attempts: int
    last_committed_batch: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "config_digest": self.config_digest,
            "profile": self.profile,
            "stage_index": self.stage_index,
            "batch_index": self.batch_index,
            "global_updates": self.global_updates,
            "environment_steps": self.environment_steps,
            "latest_checkpoint": self.latest_checkpoint,
            "latest_checkpoint_digest": self.latest_checkpoint_digest,
            "best_actor": self.best_actor,
            "best_score": self.best_score,
            "completed_stages": list(self.completed_stages),
            "failed_attempts": self.failed_attempts,
            "last_committed_batch": self.last_committed_batch,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CurriculumState:
        expected = set(cls(1, "", "", "", 0, 0, 0, 0, None, None, None, None, (), 0, -1).to_dict())
        if set(values) != expected or values.get("schema_version") != 1:
            raise ValueError("curriculum state schema is incompatible")
        return cls(
            1,
            str(values["run_id"]),
            str(values["config_digest"]),
            str(values["profile"]),
            int(values["stage_index"]),
            int(values["batch_index"]),
            int(values["global_updates"]),
            int(values["environment_steps"]),
            None if values["latest_checkpoint"] is None else str(values["latest_checkpoint"]),
            None if values["latest_checkpoint_digest"] is None else str(values["latest_checkpoint_digest"]),
            None if values["best_actor"] is None else str(values["best_actor"]),
            None if values["best_score"] is None else float(values["best_score"]),
            tuple(str(item) for item in values["completed_stages"]),
            int(values["failed_attempts"]),
            int(values["last_committed_batch"]),
        )

    @property
    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


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


class CurriculumStore:
    def __init__(self, output_directory: str | Path) -> None:
        self.output_directory = Path(output_directory)
        self.state_path = self.output_directory / "state.json"
        self._expected_config_digest: str | None = None

    def initialize(
        self,
        config: CurriculumConfig,
        *,
        profile: str = "smoke",
        best_actor: str | None = None,
    ) -> CurriculumState:
        if profile not in config.profiles:
            raise ValueError(f"unknown curriculum profile: {profile}")
        if self.state_path.exists():
            raise FileExistsError(f"curriculum state already exists: {self.state_path}")
        self.output_directory.mkdir(parents=True, exist_ok=True)
        (self.output_directory / "reports").mkdir(exist_ok=True)
        (self.output_directory / "failures").mkdir(exist_ok=True)
        (self.output_directory / "manifests").mkdir(exist_ok=True)
        state = CurriculumState(
            1,
            uuid.uuid4().hex,
            config.digest,
            profile,
            0,
            0,
            0,
            0,
            None,
            None,
            best_actor,
            None,
            (),
            0,
            -1,
        )
        _atomic_json(self.state_path, state.to_dict())
        self._expected_config_digest = config.digest
        return state

    def load(self, config: CurriculumConfig | None = None) -> CurriculumState:
        values = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("curriculum state must contain an object")
        state = CurriculumState.from_dict(values)
        expected = config.digest if config is not None else self._expected_config_digest
        if expected is not None and state.config_digest != expected:
            raise ValueError("curriculum config digest mismatch")
        if state.latest_checkpoint is not None:
            checkpoint = self.output_directory / state.latest_checkpoint
            if not checkpoint.is_file():
                raise ValueError("committed trainer checkpoint is missing")
            if _sha256(checkpoint) != state.latest_checkpoint_digest:
                raise ValueError("committed trainer checkpoint digest mismatch")
        self._expected_config_digest = state.config_digest
        return state

    def commit_batch(
        self,
        previous: CurriculumState,
        *,
        trainer_checkpoint: str | Path,
        report: Mapping[str, object],
        global_updates: int,
        environment_steps: int,
        best_actor: str | Path | None = None,
        best_score: float | None = None,
        stage_completed: bool = False,
    ) -> CurriculumState:
        if self.load().to_dict() != previous.to_dict():
            raise ValueError("curriculum state changed before batch commit")
        source = Path(trainer_checkpoint)
        if not source.is_file():
            raise ValueError("trainer checkpoint is missing")
        latest = self.output_directory / "latest-trainer.pt"
        checkpoint_tmp = latest.with_suffix(latest.suffix + ".tmp")
        shutil.copyfile(source, checkpoint_tmp)
        os.replace(checkpoint_tmp, latest)
        report_path = self.output_directory / "reports" / (
            f"batch-{previous.stage_index}-{previous.batch_index}.json"
        )
        _atomic_json(report_path, report)
        actor_name = previous.best_actor
        if best_actor is not None:
            actor_source = Path(best_actor)
            actor_destination = self.output_directory / "best-actor.pt"
            actor_tmp = actor_destination.with_suffix(actor_destination.suffix + ".tmp")
            shutil.copyfile(actor_source, actor_tmp)
            os.replace(actor_tmp, actor_destination)
            actor_name = actor_destination.name
        completed = previous.completed_stages
        stage_index = previous.stage_index
        batch_index = previous.batch_index + 1
        if stage_completed:
            completed = (*completed, str(previous.stage_index))
            stage_index += 1
            batch_index = 0
        state = CurriculumState(
            1,
            previous.run_id,
            previous.config_digest,
            previous.profile,
            stage_index,
            batch_index,
            int(global_updates),
            int(environment_steps),
            latest.name,
            _sha256(latest),
            actor_name,
            previous.best_score if best_score is None else float(best_score),
            completed,
            previous.failed_attempts,
            previous.last_committed_batch + 1,
        )
        _atomic_json(self.state_path, state.to_dict())
        return state


class RunLock:
    def __init__(self, output_directory: str | Path) -> None:
        self.path = Path(output_directory) / ".curriculum.lock"
        self.token = uuid.uuid4().hex
        self._held = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return ctypes.get_last_error() == 5
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def acquire(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": time.time(),
            "token": self.token,
        }
        while True:
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
            except FileExistsError:
                try:
                    existing = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise RuntimeError("curriculum output is locked") from None
                if (
                    existing.get("host") == socket.gethostname()
                    and not self._pid_alive(int(existing.get("pid", -1)))
                ):
                    self.path.unlink(missing_ok=True)
                    continue
                raise RuntimeError("curriculum output is locked") from None
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
            self._held = True
            return self

    def release(self) -> None:
        if not self._held:
            return
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if existing.get("token") == self.token:
            self.path.unlink(missing_ok=True)
        self._held = False

    def __enter__(self) -> RunLock:
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]
    score: float


def promotion_decision(
    *,
    current: Mapping[str, object],
    baselines: Mapping[str, float],
    regressions: Mapping[str, float],
    maximum_drop: float,
) -> PromotionDecision:
    if not math.isfinite(maximum_drop) or maximum_drop < 0.0:
        raise ValueError("maximum_drop must be finite and non-negative")
    reasons: list[str] = []
    if current.get("admission_passed") is not True:
        reasons.append("current-admission")
    for skill in sorted(baselines):
        baseline = float(baselines[skill])
        regression = regressions.get(skill)
        if regression is None or not math.isfinite(float(regression)):
            reasons.append(f"missing-regression:{skill}")
        elif baseline - float(regression) > maximum_drop:
            reasons.append(f"skill-regression:{skill}")
    score = float(current.get("success", -math.inf))
    if not math.isfinite(score):
        reasons.append("non-finite-score")
        score = -math.inf
    return PromotionDecision(not reasons, tuple(reasons), score)


def manifest_for_batch(
    config: CurriculumConfig,
    profile: str,
    *,
    stage_index: int,
    batch_index: int,
) -> ScenarioManifest:
    try:
        stage = config.profiles[profile][stage_index]
    except (KeyError, IndexError) as exc:
        raise ValueError("unknown curriculum stage") from exc
    if isinstance(batch_index, bool) or not isinstance(batch_index, int) or batch_index < 0:
        raise ValueError("batch_index must be non-negative")
    seed = stage.train_seeds[batch_index % len(stage.train_seeds)]
    fleet = stage.fleets[batch_index % len(stage.fleets)]
    return ScenarioGenerator(seed).generate(
        level=stage.level,
        fleet_size=fleet,
        active_skills=stage.active_skills,
    )
