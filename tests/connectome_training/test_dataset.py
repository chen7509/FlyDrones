import json

import numpy as np
import pytest

from flydrones.connectome_training.dataset import (
    INPUT_ARRAY_KEYS,
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    load_sequence,
    write_sequence,
)


def frame(t: int) -> SequenceFrame:
    return SequenceFrame(
        sim_ns=t,
        frame_ns=t,
        rgb=np.zeros((4, 6, 3), np.uint8),
        depth_m=np.ones((4, 6), np.float32),
        position_enu=np.array([0, 0, 1], np.float32),
        velocity_enu=np.zeros(3, np.float32),
        yaw=0.0,
        yaw_rate=0.0,
        goal_enu=np.array([5, 0, 1], np.float32),
    )


def target() -> TeacherTarget:
    return TeacherTarget(
        velocity_enu=np.array([1, 0, 0], np.float32),
        yaw_rate=0.0,
        horizon_enu=np.array([[1, 0, 1], [2, 0, 1]], np.float32),
        minimum_clearance_m=0.8,
        terminal=False,
    )


def provenance() -> SequenceProvenance:
    return SequenceProvenance(
        split="train",
        seed=101,
        teacher="ego@23a8d5a",
        world_sha256="a" * 64,
        config_sha256="b" * 64,
        source="generated-training-world",
    )


def test_round_trip_uses_exact_student_allowlist(tmp_path):
    sequence = TrainingSequence(
        provenance(),
        [frame(50_000_000), frame(100_000_000)],
        [target(), target()],
    )
    out = write_sequence(tmp_path / "episode", sequence)
    loaded = load_sequence(out)
    assert loaded.provenance == sequence.provenance
    assert np.array_equal(loaded.frames[1].rgb, sequence.frames[1].rgb)
    with np.load(out / "samples.npz") as arrays:
        assert set(arrays.files) == set(INPUT_ARRAY_KEYS) | {
            "teacher_velocity_enu",
            "teacher_yaw_rate",
            "teacher_horizon_enu",
            "teacher_minimum_clearance_m",
            "teacher_terminal",
        }
        assert not any(
            "obstacle" in key or "contact" in key or "truth" in key
            for key in arrays.files
        )
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "flydrones-connectome-sequence-v1"
    assert len(manifest["samples_sha256"]) == 64


def test_duplicate_sim_time_is_rejected(tmp_path):
    sequence = TrainingSequence(
        provenance(), [frame(50), frame(50)], [target(), target()]
    )
    with pytest.raises(ValueError, match="strictly increasing sim_ns"):
        write_sequence(tmp_path / "episode", sequence)


def test_non_finite_depth_names_the_field(tmp_path):
    bad = frame(50)
    bad.depth_m[0, 0] = np.nan
    with pytest.raises(ValueError, match="depth_m contains non-finite"):
        write_sequence(
            tmp_path / "episode", TrainingSequence(provenance(), [bad], [target()])
        )
