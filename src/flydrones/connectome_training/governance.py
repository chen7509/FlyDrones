from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Iterable, Mapping

from .dataset import SequenceProvenance
from .recorder import reject_formal_evidence


def validate_dataset_partitions(
    train: Iterable[SequenceProvenance],
    validation: Iterable[SequenceProvenance],
) -> None:
    train_rows = list(train)
    validation_rows = list(validation)
    for expected, rows in (("train", train_rows), ("val", validation_rows)):
        for provenance in rows:
            reject_formal_evidence(provenance)
            if provenance.split != expected:
                raise ValueError(
                    f"{expected} partition contains split={provenance.split!r}"
                )
    train_seeds = {row.seed for row in train_rows}
    validation_seeds = {row.seed for row in validation_rows}
    train_worlds = {row.world_sha256 for row in train_rows}
    validation_worlds = {row.world_sha256 for row in validation_rows}
    if train_seeds & validation_seeds:
        raise ValueError("training and validation seed overlap")
    if train_worlds & validation_worlds:
        raise ValueError("training and validation world hash overlap")


@dataclass(frozen=True)
class CurriculumGate:
    episodes: int
    minimum_success_rate: float
    maximum_collision_rate: float
    minimum_clearance_m: float
    maximum_validation_loss: float


def evaluate_gate(
    gate: CurriculumGate, metrics: Mapping[str, float]
) -> tuple[bool, tuple[str, ...]]:
    required = {
        "episodes": gate.episodes,
        "success_rate": gate.minimum_success_rate,
        "collision_rate": gate.maximum_collision_rate,
        "minimum_clearance_m": gate.minimum_clearance_m,
        "validation_loss": gate.maximum_validation_loss,
    }
    missing = [name for name in required if name not in metrics]
    if missing:
        raise ValueError(f"curriculum metrics missing: {', '.join(missing)}")
    values = {name: float(metrics[name]) for name in required}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("curriculum metrics contain non-finite values")
    failures = []
    if values["episodes"] < gate.episodes:
        failures.append("episodes")
    if values["success_rate"] < gate.minimum_success_rate:
        failures.append("success_rate")
    if values["collision_rate"] > gate.maximum_collision_rate:
        failures.append("collision_rate")
    if values["minimum_clearance_m"] < gate.minimum_clearance_m:
        failures.append("minimum_clearance_m")
    if values["validation_loss"] > gate.maximum_validation_loss:
        failures.append("validation_loss")
    return not failures, tuple(failures)
