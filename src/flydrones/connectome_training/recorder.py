from __future__ import annotations

from pathlib import Path

import numpy as np

from flydrones.benchmark.contract import Decision, Observation

from .dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    write_sequence,
)

FORMAL_FREEZE_SEAL = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"


def reject_formal_evidence(provenance: SequenceProvenance) -> None:
    source = provenance.source.lower()
    if "formal" in source or FORMAL_FREEZE_SEAL in source:
        raise ValueError("formal comparison evidence cannot be used as training data")


class TeacherSequenceRecorder:
    def __init__(self, provenance: SequenceProvenance):
        reject_formal_evidence(provenance)
        self.provenance = provenance
        self.frames: list[SequenceFrame] = []
        self.targets: list[TeacherTarget] = []

    def append(
        self,
        obs: Observation,
        decision: Decision,
        *,
        horizon_enu: np.ndarray,
        minimum_clearance_m: float,
        terminal: bool,
    ) -> None:
        if self.frames and obs.sim_ns <= self.frames[-1].sim_ns:
            raise ValueError("observation sim_ns must be strictly newer")
        velocity = np.asarray(decision.command.velocity_enu, np.float32)
        if not np.isfinite(velocity).all():
            raise ValueError("teacher_velocity_enu contains non-finite values")
        self.frames.append(
            SequenceFrame(
                obs.sim_ns,
                obs.frame_ns,
                np.array(obs.rgb, copy=True),
                np.array(obs.depth_m, copy=True),
                np.asarray(obs.position, np.float32),
                np.asarray(obs.velocity, np.float32),
                float(obs.yaw),
                float(obs.yaw_rate),
                np.asarray(obs.goal, np.float32),
            )
        )
        self.targets.append(
            TeacherTarget(
                velocity,
                float(decision.command.yaw_rate),
                np.asarray(horizon_enu, np.float32),
                float(minimum_clearance_m),
                bool(terminal),
            )
        )

    def finish(self, path: str | Path) -> Path:
        return write_sequence(
            path, TrainingSequence(self.provenance, self.frames, self.targets)
        )
