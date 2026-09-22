from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "flydrones-connectome-curriculum-v1"


@dataclass(frozen=True)
class CurriculumProfile:
    name: str
    data_mode: str
    model_mode: str
    device: str
    stage_ids: tuple[str, ...]


@dataclass(frozen=True)
class CurriculumStage:
    id: str
    order: int
    train_seeds: tuple[int, ...]
    validation_seeds: tuple[int, ...]
    epochs_per_batch: int
    max_batches: int
    maximum_validation_loss: float
    maximum_loss_ratio: float
    maximum_regression_ratio: float
    train_paths: tuple[str, ...]
    validation_paths: tuple[str, ...]


@dataclass(frozen=True)
class CurriculumConfig:
    seed: int
    profile: CurriculumProfile
    stages: tuple[CurriculumStage, ...]
    digest: str


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return dict(value)


def _keys(value: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{name} has unknown keys: {', '.join(sorted(unknown))}")
    missing = allowed - set(value)
    if missing:
        raise ValueError(f"{name} is missing keys: {', '.join(sorted(missing))}")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _seeds(value: Any, name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty seed list")
    seeds = tuple(value)
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds):
        raise ValueError(f"{name} must contain integer seeds")
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{name} contains duplicate seeds")
    return seeds


def _paths(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(path, str) or not path for path in value
    ):
        raise ValueError(f"{name} must be a list of non-empty paths")
    return tuple(value)


def _ratio(value: Any, name: str) -> float:
    result = float(value)
    if not 0.0 < result < float("inf"):
        raise ValueError(f"{name} must be positive and finite")
    return result


def _stage(value: Any) -> CurriculumStage:
    raw = _mapping(value, "stage")
    allowed = {
        "id",
        "order",
        "train_seeds",
        "validation_seeds",
        "epochs_per_batch",
        "max_batches",
        "maximum_validation_loss",
        "maximum_loss_ratio",
        "maximum_regression_ratio",
        "train_paths",
        "validation_paths",
    }
    _keys(raw, allowed, "stage")
    identifier = raw["id"]
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("stage id must be non-empty")
    order = raw["order"]
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        raise ValueError("stage order must be a non-negative integer")
    train_seeds = _seeds(raw["train_seeds"], f"{identifier}.train_seeds")
    validation_seeds = _seeds(
        raw["validation_seeds"], f"{identifier}.validation_seeds"
    )
    if set(train_seeds) & set(validation_seeds):
        raise ValueError(f"stage {identifier} has training/validation seed overlap")
    return CurriculumStage(
        identifier,
        order,
        train_seeds,
        validation_seeds,
        _positive_int(raw["epochs_per_batch"], "epochs_per_batch"),
        _positive_int(raw["max_batches"], "max_batches"),
        _ratio(raw["maximum_validation_loss"], "maximum_validation_loss"),
        _ratio(raw["maximum_loss_ratio"], "maximum_loss_ratio"),
        _ratio(raw["maximum_regression_ratio"], "maximum_regression_ratio"),
        _paths(raw["train_paths"], "train_paths"),
        _paths(raw["validation_paths"], "validation_paths"),
    )


def _profile(name: str, value: Any) -> CurriculumProfile:
    raw = _mapping(value, f"profile {name}")
    allowed = {"data_mode", "model_mode", "device", "stages"}
    _keys(raw, allowed, f"profile {name}")
    data_mode = str(raw["data_mode"])
    model_mode = str(raw["model_mode"])
    device = str(raw["device"])
    stages = raw["stages"]
    if data_mode not in {"synthetic-smoke", "sequence-directories"}:
        raise ValueError(f"unsupported data_mode: {data_mode}")
    if model_mode not in {"tiny-connectome", "full-male-cns"}:
        raise ValueError(f"unsupported model_mode: {model_mode}")
    if device not in {"cpu", "cuda", "auto"}:
        raise ValueError(f"unsupported device: {device}")
    if not isinstance(stages, list) or not stages or any(
        not isinstance(stage, str) or not stage for stage in stages
    ):
        raise ValueError("profile stages must be a non-empty list")
    if len(set(stages)) != len(stages):
        raise ValueError("profile stages must be unique")
    return CurriculumProfile(name, data_mode, model_mode, device, tuple(stages))


def load_curriculum_config(
    path: str | Path, profile_name: str
) -> CurriculumConfig:
    raw = _mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")), "config")
    _keys(raw, {"schema", "seed", "profiles", "stages"}, "config")
    if raw["schema"] != SCHEMA:
        raise ValueError("unsupported connectome curriculum schema")
    seed = raw["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    profiles = _mapping(raw["profiles"], "profiles")
    if profile_name not in profiles:
        raise ValueError(f"unknown profile: {profile_name}")
    profile = _profile(profile_name, profiles[profile_name])
    if profile.data_mode == "synthetic-smoke" and profile.name != "smoke":
        raise ValueError("synthetic-smoke is restricted to the smoke profile")
    if profile.data_mode == "synthetic-smoke" and profile.model_mode != "tiny-connectome":
        raise ValueError("synthetic-smoke requires tiny-connectome")
    if profile.model_mode == "full-male-cns" and profile.data_mode != "sequence-directories":
        raise ValueError("full-male-cns requires sequence-directories")

    all_stages = tuple(_stage(value) for value in raw["stages"])
    identifiers = [stage.id for stage in all_stages]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("stage ids must be unique")
    if [stage.order for stage in all_stages] != list(range(len(all_stages))):
        raise ValueError("stage order must be continuous and ordered")
    lookup = {stage.id: stage for stage in all_stages}
    missing = set(profile.stage_ids) - set(lookup)
    if missing:
        raise ValueError(f"profile references unknown stages: {', '.join(sorted(missing))}")
    selected = tuple(lookup[identifier] for identifier in profile.stage_ids)
    train_seeds = {seed for stage in selected for seed in stage.train_seeds}
    validation_seeds = {
        seed for stage in selected for seed in stage.validation_seeds
    }
    if train_seeds & validation_seeds:
        raise ValueError("curriculum training/validation seed overlap")
    if profile.data_mode == "sequence-directories":
        for stage in selected:
            if not stage.train_paths or not stage.validation_paths:
                raise ValueError(
                    f"stage {stage.id} requires train and validation sequence paths"
                )

    canonical = {
        "schema": SCHEMA,
        "seed": seed,
        "profile": asdict(profile),
        "stages": [asdict(stage) for stage in selected],
    }
    digest = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return CurriculumConfig(seed, profile, selected, digest)
