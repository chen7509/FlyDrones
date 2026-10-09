from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.benchmark.ego import track_reference, validate_reference

from .capture_input import CaptureInputEvidence, validate_capture_input
from .corpus_config import CorpusConfig
from .dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    _finite_float32,
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
        self.references: list[np.ndarray | None] = []

    def append(
        self,
        obs: Observation,
        decision: Decision,
        *,
        horizon_enu: np.ndarray,
        minimum_clearance_m: float,
        terminal: bool,
    ) -> None:
        self._append(
            obs, decision, horizon_enu=horizon_enu,
            minimum_clearance_m=minimum_clearance_m, terminal=terminal,
            depth_valid=None,
        )

    def append_capture_checked(
        self,
        backend: object,
        obs: Observation,
        evidence: CaptureInputEvidence,
        config: CorpusConfig,
        decision: Decision,
        *,
        minimum_clearance_m: float,
        terminal: bool,
    ) -> None:
        """Bind gate-checked input and a same-time EGO reference; not live attestation."""
        if self.frames and self.frames[0].depth_valid is None:
            raise ValueError("mixed checked and legacy recorder modes")
        if not isinstance(obs, Observation):
            raise ValueError("capture observation invalid")
        if (not isinstance(obs.rgb, np.ndarray) or obs.rgb.dtype != np.uint8
                or not isinstance(obs.depth_m, np.ndarray)
                or obs.depth_m.dtype != np.float32):
            raise ValueError("RGB-D depth frame invalid")
        snapshot = deepcopy(obs)
        validate_capture_input(backend, snapshot, evidence, config)
        if (not isinstance(decision, Decision) or not isinstance(decision.evidence, dict)
                or decision.evidence.get("controller") != "ego"):
            raise ValueError("EGO decision evidence missing")
        reference = validate_reference(
            decision.evidence.get("reference"),
            observation_sim_ns=snapshot.sim_ns, max_age_ns=0,
        )
        gain = decision.evidence.get("tracking_gain")
        if (type(gain) not in (int, float) or not np.isfinite(gain) or gain < 0):
            raise ValueError("EGO tracking gain invalid")
        expected_command = track_reference(
            tuple(reference["position_ref"]), tuple(reference["velocity_ref"]),
            snapshot.position, reference["yaw_rate"], gain,
        )
        if not isinstance(decision.command, Command):
            raise ValueError("EGO command invalid")
        actual_velocity = np.asarray(decision.command.velocity_enu)
        actual_yaw_rate = decision.command.yaw_rate
        if (actual_velocity.shape != (3,) or actual_velocity.dtype.kind not in "iuf"
                or not np.isfinite(actual_velocity).all()
                or isinstance(actual_yaw_rate, bool)
                or not isinstance(actual_yaw_rate, (int, float, np.integer, np.floating))
                or not np.isfinite(actual_yaw_rate)
                or not np.allclose(actual_velocity,
                                   expected_command.velocity_enu, rtol=0, atol=1e-9)
                or not np.isclose(actual_yaw_rate,
                                  expected_command.yaw_rate, rtol=0, atol=1e-9)):
            raise ValueError("EGO command does not match received reference")
        if (type(terminal) is not bool or isinstance(minimum_clearance_m, bool)
                or not isinstance(minimum_clearance_m, (int, float, np.integer, np.floating))
                or not np.isfinite(minimum_clearance_m) or minimum_clearance_m < 0):
            raise ValueError("capture clearance or terminal invalid")
        position_ref = np.asarray(reference["position_ref"], np.float32)
        if not np.isfinite(position_ref).all():
            raise ValueError("EGO reference position invalid after float32 conversion")
        stable_reference = {
            key: list(value) if isinstance(value, list) else value
            for key, value in reference.items()
        }
        stable_decision = replace(decision, evidence={"reference": stable_reference})
        self._append(
            snapshot, stable_decision, horizon_enu=position_ref[None, :],
            minimum_clearance_m=minimum_clearance_m, terminal=terminal,
            depth_valid=np.isfinite(snapshot.depth_m) & (snapshot.depth_m > 0),
        )

    def _append(
        self,
        obs: Observation,
        decision: Decision,
        *,
        horizon_enu: np.ndarray,
        minimum_clearance_m: float,
        terminal: bool,
        depth_valid: np.ndarray | None,
    ) -> None:
        if self.frames and (self.frames[0].depth_valid is None) != (depth_valid is None):
            raise ValueError("mixed checked and legacy recorder modes")
        if self.frames and obs.sim_ns <= self.frames[-1].sim_ns:
            raise ValueError("observation sim_ns must be strictly newer")
        for name, value in (
            ("position_enu", obs.position),
            ("velocity_enu", obs.velocity),
            ("goal_enu", obs.goal),
            ("yaw", obs.yaw),
            ("yaw_rate", obs.yaw_rate),
            ("teacher_velocity_enu", decision.command.velocity_enu),
            ("teacher_yaw_rate", decision.command.yaw_rate),
            ("teacher_horizon_enu", horizon_enu),
            ("teacher_minimum_clearance_m", minimum_clearance_m),
        ):
            _finite_float32(name, value)
        velocity = np.array(decision.command.velocity_enu, dtype=np.float32, copy=True)
        if not np.isfinite(velocity).all():
            raise ValueError("teacher_velocity_enu contains non-finite values")
        reference = decision.evidence.get("reference")
        position_ref = None
        if reference is not None:
            if not isinstance(reference, dict) or "position_ref" not in reference:
                raise ValueError("teacher reference position missing")
            try:
                position_ref = np.asarray(reference["position_ref"], np.float32)
            except (TypeError, ValueError) as exc:
                raise ValueError("teacher reference position invalid") from exc
            if position_ref.shape != (3,) or not np.isfinite(position_ref).all():
                raise ValueError("teacher reference position invalid")
        frame = SequenceFrame(
            obs.sim_ns,
            obs.frame_ns,
            np.array(obs.rgb, copy=True),
            np.array(obs.depth_m, copy=True),
            np.array(obs.position, dtype=np.float32, copy=True),
            np.array(obs.velocity, dtype=np.float32, copy=True),
            float(obs.yaw),
            float(obs.yaw_rate),
            np.array(obs.goal, dtype=np.float32, copy=True),
            None if depth_valid is None else np.array(depth_valid, copy=True),
        )
        target = TeacherTarget(
            velocity,
            float(decision.command.yaw_rate),
            np.array(horizon_enu, dtype=np.float32, copy=True),
            float(minimum_clearance_m),
            bool(terminal),
        )
        for name, value in (
            ("position_enu", frame.position_enu),
            ("velocity_enu", frame.velocity_enu),
            ("goal_enu", frame.goal_enu),
            ("yaw", frame.yaw),
            ("yaw_rate", frame.yaw_rate),
            ("teacher_velocity_enu", target.velocity_enu),
            ("teacher_yaw_rate", target.yaw_rate),
            ("teacher_horizon_enu", target.horizon_enu),
            ("teacher_minimum_clearance_m", target.minimum_clearance_m),
        ):
            _finite_float32(name, value)
        self.frames.append(frame)
        self.targets.append(target)
        self.references.append(None if position_ref is None else position_ref.copy())

    def finish(self, path: str | Path) -> Path:
        return write_sequence(
            path, TrainingSequence(self.provenance, self.frames, self.targets)
        )

    def finish_with_reference_horizon(self, path: Path, *, points: int) -> Path:
        """Save observed EGO reference positions without inventing future points."""
        if type(points) is not int or points < 1:
            raise ValueError("points must be a positive integer")
        if not self.references or any(reference is None for reference in self.references):
            raise ValueError("native teacher reference missing")
        targets = []
        for index, target in enumerate(self.targets):
            available = min(points, len(self.references) - index)
            horizon = np.zeros((points, 3), np.float32)
            horizon[:available] = np.stack(self.references[index:index + available])
            valid = np.zeros(points, np.bool_)
            valid[:available] = True
            targets.append(replace(target, horizon_enu=horizon, horizon_valid=valid))
        return write_sequence(path, TrainingSequence(self.provenance, self.frames, targets))
