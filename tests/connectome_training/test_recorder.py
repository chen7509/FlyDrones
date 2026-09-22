import numpy as np
import pytest

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.connectome_training.dataset import SequenceProvenance, load_sequence
from flydrones.connectome_training.recorder import TeacherSequenceRecorder

FORMAL_SEAL = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"


def observation(t: int) -> Observation:
    return Observation(
        t,
        t,
        np.zeros((4, 6, 3), np.uint8),
        np.ones((4, 6), np.float32),
        (),
        (0, 0, 1),
        (0, 0, 0),
        0.0,
        0.0,
        (5, 0, 1),
    )


def provenance(source: str = "training-generator") -> SequenceProvenance:
    return SequenceProvenance("train", 7, "ego@test", "a" * 64, "b" * 64, source)


def test_recorder_converts_only_typed_observation_and_command(tmp_path):
    recorder = TeacherSequenceRecorder(provenance())
    recorder.append(
        observation(50),
        Decision(Command((1, 0, 0), 0.2), 0.01, {"world_truth": [1, 2, 3]}),
        horizon_enu=np.array([[1, 0, 1]], np.float32),
        minimum_clearance_m=0.7,
        terminal=False,
    )
    out = recorder.finish(tmp_path / "sequence")
    loaded = load_sequence(out)
    assert loaded.targets[0].yaw_rate == pytest.approx(0.2)
    assert "world_truth" not in (out / "manifest.json").read_text(encoding="utf-8")


def test_recorder_rejects_time_rollback():
    recorder = TeacherSequenceRecorder(provenance())
    decision = Decision(Command((1, 0, 0), 0.0), 0.01, {})
    recorder.append(
        observation(100),
        decision,
        horizon_enu=np.zeros((1, 3)),
        minimum_clearance_m=1.0,
        terminal=False,
    )
    with pytest.raises(ValueError, match="strictly newer"):
        recorder.append(
            observation(50),
            decision,
            horizon_enu=np.zeros((1, 3)),
            minimum_clearance_m=1.0,
            terminal=False,
        )


def test_formal_evidence_cannot_be_training_source():
    with pytest.raises(ValueError, match="formal comparison evidence"):
        TeacherSequenceRecorder(provenance(f"formal-freeze:{FORMAL_SEAL}"))


def test_non_finite_teacher_command_is_rejected():
    recorder = TeacherSequenceRecorder(provenance())
    bad = Decision(Command((np.nan, 0, 0), 0.0), 0.01, {})
    with pytest.raises(ValueError, match="teacher_velocity_enu"):
        recorder.append(
            observation(50),
            bad,
            horizon_enu=np.zeros((1, 3)),
            minimum_clearance_m=1.0,
            terminal=False,
        )
