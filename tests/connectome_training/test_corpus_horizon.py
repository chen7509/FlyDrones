"""Short teacher trajectories must mark unavailable future points invalid."""

import json

import numpy as np
import pytest

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.connectome_training.dataset import (
    SequenceProvenance,
    load_sequence,
    write_sequence,
)
from flydrones.connectome_training.recorder import TeacherSequenceRecorder


def _observation(t):
    return Observation(t, t, np.zeros((4, 6, 3), np.uint8),
                       np.ones((4, 6), np.float32), (), (0, 0, 1),
                       (0, 0, 0), 0., 0., (5, 0, 1))


def _recorder():
    return TeacherSequenceRecorder(SequenceProvenance(
        "train", 1101, "ego@23a8d5a", "a" * 64, "b" * 64, "generated-training-world"))


def _append(recorder, index, position):
    recorder.append(
        _observation((index + 1) * 50_000_000),
        Decision(Command((.5, 0, 0), 0.), .01,
                 {"reference": {"position_ref": position}}),
        horizon_enu=np.zeros((4, 3)), minimum_clearance_m=.8, terminal=False,
    )


def test_future_reference_horizon_masks_unobserved_tail_and_round_trips(tmp_path):
    recorder = _recorder()
    for index in range(3):
        _append(recorder, index, [float(index + 1), 0., 1.])
    out = recorder.finish_with_reference_horizon(tmp_path / "sequence", points=4)
    loaded = load_sequence(out)
    assert loaded.targets[0].horizon_valid.tolist() == [True, True, True, False]
    assert loaded.targets[-1].horizon_valid.tolist() == [True, False, False, False]
    assert loaded.targets[-1].horizon_enu.shape == (4, 3)
    assert loaded.targets[0].horizon_enu.tolist() == [
        [1., 0., 1.], [2., 0., 1.], [3., 0., 1.], [0., 0., 0.]]
    with np.load(out / "samples.npz") as arrays:
        assert arrays["teacher_horizon_valid"].dtype == np.bool_
    assert json.loads((out / "manifest.json").read_text())["schema"] == (
        "flydrones-connectome-sequence-v2")


def test_v1_writer_still_loads_with_all_valid_horizon(tmp_path):
    recorder = _recorder()
    _append(recorder, 0, [1., 0., 1.])
    out = recorder.finish(tmp_path / "v1")
    assert json.loads((out / "manifest.json").read_text())["schema"] == (
        "flydrones-connectome-sequence-v1")
    assert load_sequence(out).targets[0].horizon_valid.tolist() == [True] * 4
    with np.load(out / "samples.npz") as arrays:
        assert "teacher_horizon_valid" not in arrays.files


def test_nonzero_fake_future_point_is_rejected(tmp_path):
    recorder = _recorder()
    _append(recorder, 0, [1., 0., 1.])
    sequence = load_sequence(recorder.finish_with_reference_horizon(
        tmp_path / "source", points=3))
    sequence.targets[0].horizon_enu[1] = [8., 0., 1.]
    with pytest.raises(ValueError, match="padding"):
        write_sequence(tmp_path / "invalid", sequence)


def test_nonfinite_or_missing_native_reference_is_rejected_for_v2(tmp_path):
    recorder = _recorder()
    with pytest.raises(ValueError, match="reference"):
        _append(recorder, 0, [np.nan, 0., 1.])
    assert recorder.frames == []
    recorder.append(_observation(50), Decision(Command((0, 0, 0), 0), .01, {}),
                    horizon_enu=np.zeros((4, 3)), minimum_clearance_m=1., terminal=False)
    with pytest.raises(ValueError, match="reference"):
        recorder.finish_with_reference_horizon(tmp_path / "missing", points=4)
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("points", [0, -1, 1.5])
def test_invalid_horizon_length_is_rejected(tmp_path, points):
    recorder = _recorder()
    _append(recorder, 0, [1., 0., 1.])
    with pytest.raises(ValueError, match="points"):
        recorder.finish_with_reference_horizon(tmp_path / "bad", points=points)
