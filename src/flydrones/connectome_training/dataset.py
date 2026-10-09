from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np

SCHEMA = "flydrones-connectome-sequence-v1"
SCHEMA_V2 = "flydrones-connectome-sequence-v2"
SCHEMA_V3 = "flydrones-connectome-sequence-v3"
INPUT_ARRAY_KEYS = (
    "sim_ns",
    "frame_ns",
    "rgb",
    "depth_m",
    "position_enu",
    "velocity_enu",
    "yaw",
    "yaw_rate",
    "goal_enu",
)


@dataclass(frozen=True)
class SequenceProvenance:
    split: str
    seed: int
    teacher: str
    world_sha256: str
    config_sha256: str
    source: str


@dataclass
class SequenceFrame:
    sim_ns: int
    frame_ns: int
    rgb: np.ndarray
    depth_m: np.ndarray
    position_enu: np.ndarray
    velocity_enu: np.ndarray
    yaw: float
    yaw_rate: float
    goal_enu: np.ndarray
    depth_valid: np.ndarray | None = None


@dataclass
class TeacherTarget:
    velocity_enu: np.ndarray
    yaw_rate: float
    horizon_enu: np.ndarray
    minimum_clearance_m: float
    terminal: bool
    horizon_valid: np.ndarray | None = None


@dataclass
class TrainingSequence:
    provenance: SequenceProvenance
    frames: list[SequenceFrame]
    targets: list[TeacherTarget]


def _finite(name: str, value: np.ndarray) -> None:
    if not np.isfinite(value).all():
        raise ValueError(f"{name} contains non-finite values")


def _finite_float32(name: str, value: object) -> None:
    """Reject finite source values that overflow the on-disk float32 contract."""
    array = np.asarray(value)
    _finite(name, array)
    with np.errstate(over="ignore"):
        stored = np.asarray(array, dtype=np.float32)
    _finite(name, stored)


def _validate(sequence: TrainingSequence) -> None:
    if not sequence.frames or len(sequence.frames) != len(sequence.targets):
        raise ValueError("frames and targets must have the same non-zero length")
    times = np.asarray([frame.sim_ns for frame in sequence.frames], np.int64)
    if np.any(np.diff(times) <= 0):
        raise ValueError("frames require strictly increasing sim_ns")
    masked = [frame.depth_valid is not None for frame in sequence.frames]
    if any(masked) and not all(masked):
        raise ValueError("mixed depth validity modes")
    masked_sequence = all(masked)
    if masked_sequence and any(target.horizon_valid is None for target in sequence.targets):
        raise ValueError("v3 depth validity requires teacher_horizon_valid")
    for frame in sequence.frames:
        if frame.frame_ns > frame.sim_ns:
            raise ValueError("frame_ns cannot be newer than sim_ns")
        if masked_sequence:
            depth = np.asarray(frame.depth_m)
            rgb = np.asarray(frame.rgb)
            valid = np.asarray(frame.depth_valid)
            if (depth.dtype != np.float32 or depth.ndim != 2
                    or not all(depth.shape) or rgb.dtype != np.uint8
                    or rgb.shape != (*depth.shape, 3)):
                raise ValueError("v3 depth geometry or depth_m dtype invalid")
            if np.any(np.isinf(depth)) or np.any(depth <= 0):
                raise ValueError("v3 depth_m contains invalid values")
            expected = np.isfinite(depth) & (depth > 0)
            if (valid.dtype != np.bool_ or valid.shape != depth.shape
                    or not np.array_equal(valid, expected)):
                raise ValueError("depth_valid mask invalid")
        else:
            _finite_float32("depth_m", frame.depth_m)
        for name in ("position_enu", "velocity_enu", "goal_enu"):
            _finite_float32(name, getattr(frame, name))
        _finite_float32("yaw", frame.yaw)
        _finite_float32("yaw_rate", frame.yaw_rate)
    for target in sequence.targets:
        _finite_float32("teacher_velocity_enu", target.velocity_enu)
        horizon = np.asarray(target.horizon_enu)
        _finite_float32("teacher_horizon_enu", horizon)
        if horizon.ndim != 2 or horizon.shape[1] != 3 or horizon.shape[0] < 1:
            raise ValueError("teacher_horizon_enu shape invalid")
        if target.horizon_valid is not None:
            valid = np.asarray(target.horizon_valid)
            if (valid.dtype != np.bool_ or valid.shape != (horizon.shape[0],)
                    or not valid[0] or np.any(np.diff(valid.astype(np.int8)) > 0)):
                raise ValueError("teacher_horizon_valid mask invalid")
            if np.any(horizon[~valid] != 0):
                raise ValueError("invalid teacher horizon padding")
        _finite_float32("teacher_yaw_rate", target.yaw_rate)
        _finite_float32("teacher_minimum_clearance_m", target.minimum_clearance_m)
    if any(target.horizon_valid is not None for target in sequence.targets) and any(
            target.horizon_valid is None for target in sequence.targets):
        raise ValueError("mixed v1/v2 teacher horizons")


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _arrays(sequence: TrainingSequence) -> dict[str, np.ndarray]:
    arrays = {
        "sim_ns": np.asarray([frame.sim_ns for frame in sequence.frames], np.int64),
        "frame_ns": np.asarray(
            [frame.frame_ns for frame in sequence.frames], np.int64
        ),
        "rgb": np.stack(
            [np.asarray(frame.rgb, np.uint8) for frame in sequence.frames]
        ),
        "depth_m": np.stack(
            [np.asarray(frame.depth_m, np.float32) for frame in sequence.frames]
        ),
        "position_enu": np.stack(
            [np.asarray(frame.position_enu, np.float32) for frame in sequence.frames]
        ),
        "velocity_enu": np.stack(
            [np.asarray(frame.velocity_enu, np.float32) for frame in sequence.frames]
        ),
        "yaw": np.asarray([frame.yaw for frame in sequence.frames], np.float32),
        "yaw_rate": np.asarray(
            [frame.yaw_rate for frame in sequence.frames], np.float32
        ),
        "goal_enu": np.stack(
            [np.asarray(frame.goal_enu, np.float32) for frame in sequence.frames]
        ),
        "teacher_velocity_enu": np.stack(
            [np.asarray(target.velocity_enu, np.float32) for target in sequence.targets]
        ),
        "teacher_yaw_rate": np.asarray(
            [target.yaw_rate for target in sequence.targets], np.float32
        ),
        "teacher_horizon_enu": np.stack(
            [np.asarray(target.horizon_enu, np.float32) for target in sequence.targets]
        ),
        "teacher_minimum_clearance_m": np.asarray(
            [target.minimum_clearance_m for target in sequence.targets], np.float32
        ),
        "teacher_terminal": np.asarray(
            [target.terminal for target in sequence.targets], np.bool_
        ),
    }
    if sequence.targets[0].horizon_valid is not None:
        arrays["teacher_horizon_valid"] = np.stack(
            [np.asarray(target.horizon_valid, np.bool_) for target in sequence.targets]
        )
    if sequence.frames[0].depth_valid is not None:
        arrays["depth_valid"] = np.stack(
            [np.asarray(frame.depth_valid, np.bool_) for frame in sequence.frames]
        )
    return arrays


def write_sequence(path: str | Path, sequence: TrainingSequence) -> Path:
    _validate(sequence)
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    if path.exists() or temporary.exists():
        raise FileExistsError(path if path.exists() else temporary)
    temporary.mkdir(parents=True)
    samples = temporary / "samples.npz"
    np.savez_compressed(samples, **_arrays(sequence))
    manifest = {
        "schema": (SCHEMA_V3 if sequence.frames[0].depth_valid is not None else
                   SCHEMA_V2 if sequence.targets[0].horizon_valid is not None else SCHEMA),
        "provenance": asdict(sequence.provenance),
        "samples": len(sequence.frames),
        "samples_sha256": _digest(samples),
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(path)
    return path


def load_sequence(path: str | Path) -> TrainingSequence:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    samples = path / "samples.npz"
    if (set(manifest) != {"schema", "provenance", "samples", "samples_sha256"}
            or manifest.get("schema") not in (SCHEMA, SCHEMA_V2, SCHEMA_V3)):
        raise ValueError("unsupported training sequence schema")
    if manifest.get("samples_sha256") != _digest(samples):
        raise ValueError("samples.npz hash mismatch")
    required = set(INPUT_ARRAY_KEYS) | {
        "teacher_velocity_enu",
        "teacher_yaw_rate",
        "teacher_horizon_enu",
        "teacher_minimum_clearance_m",
        "teacher_terminal",
    }
    if manifest["schema"] in (SCHEMA_V2, SCHEMA_V3):
        required.add("teacher_horizon_valid")
    if manifest["schema"] == SCHEMA_V3:
        required.add("depth_valid")
    with np.load(samples, allow_pickle=False) as arrays:
        if set(arrays.files) != required:
            raise ValueError("samples.npz keys do not match the student/teacher contract")
        sample_count = int(arrays["sim_ns"].shape[0])
        if manifest["samples"] != sample_count:
            raise ValueError("sequence sample count mismatch")
        frames = [
            SequenceFrame(
                int(arrays["sim_ns"][i]),
                int(arrays["frame_ns"][i]),
                arrays["rgb"][i].copy(),
                arrays["depth_m"][i].copy(),
                arrays["position_enu"][i].copy(),
                arrays["velocity_enu"][i].copy(),
                float(arrays["yaw"][i]),
                float(arrays["yaw_rate"][i]),
                arrays["goal_enu"][i].copy(),
                (arrays["depth_valid"][i].copy()
                 if manifest["schema"] == SCHEMA_V3 else None),
            )
            for i in range(sample_count)
        ]
        targets = [
            TeacherTarget(
                arrays["teacher_velocity_enu"][i].copy(),
                float(arrays["teacher_yaw_rate"][i]),
                arrays["teacher_horizon_enu"][i].copy(),
                float(arrays["teacher_minimum_clearance_m"][i]),
                bool(arrays["teacher_terminal"][i]),
                (arrays["teacher_horizon_valid"][i].copy()
                 if manifest["schema"] in (SCHEMA_V2, SCHEMA_V3) else
                 np.ones(arrays["teacher_horizon_enu"][i].shape[0], np.bool_)),
            )
            for i in range(sample_count)
        ]
    sequence = TrainingSequence(
        SequenceProvenance(**manifest["provenance"]), frames, targets
    )
    _validate(sequence)
    return sequence
