"""Actual small NPZ production decoding, no NN/optimizer/target process."""

from collections import Counter

import numpy as np
import pytest

from flydrones.connectome_training.dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    load_sequence,
    write_sequence,
)
from tools.benchmark.software_process_boundary import install


@pytest.fixture(autouse=True)
def no_child_backend(monkeypatch):
    install(monkeypatch)


def sequence(version, count=4):
    frames = []
    targets = []
    for i in range(count):
        depth = np.full((4, 6), i + 1, dtype=np.float32)
        mask = None
        if version == 3:
            depth[0, 0] = np.nan
            mask = np.isfinite(depth)
        frames.append(
            SequenceFrame(
                (i + 1) * 50_000_000,
                (i + 1) * 50_000_000,
                np.full((4, 6, 3), i, np.uint8),
                depth,
                np.array([i, 0, 1], np.float32),
                np.array([1, 0, 0], np.float32),
                0.1 * i,
                0.2,
                np.array([9, 0, 1], np.float32),
                mask,
            )
        )
        horizon = np.array([[i + 1, 0, 1], [0, 0, 0]], np.float32)
        targets.append(
            TeacherTarget(
                np.array([1, 0, 0], np.float32),
                0.2,
                horizon,
                0.8,
                i == count - 1,
                np.array([True, False]) if version >= 2 else None,
            )
        )
    return TrainingSequence(
        SequenceProvenance("train", 101, "ego@fixture", "a" * 64, "b" * 64, "synthetic-software-fixture"), frames, targets
    )


def count_real_npz_decodes(path, monkeypatch):
    with np.load(path / "samples.npz", allow_pickle=False) as archive:
        cls = type(archive)
        keys = set(archive.files)
    original = cls.__getitem__
    counts = Counter()

    def decode(self, key):
        counts[key] += 1
        return original(self, key)

    monkeypatch.setattr(cls, "__getitem__", decode)
    return keys, counts


@pytest.mark.parametrize("version", [1, 2, 3])
def test_real_compressed_member_is_decoded_once_per_sequence(tmp_path, monkeypatch, version):
    original = sequence(version)
    path = write_sequence(tmp_path / "sequence", original)
    keys, counts = count_real_npz_decodes(path, monkeypatch)
    actual = load_sequence(path)
    assert counts == Counter({key: 1 for key in keys}), dict(counts)
    assert actual.provenance == original.provenance
    for frame, expected, target, label in zip(actual.frames, original.frames, actual.targets, original.targets):
        np.testing.assert_equal(frame.rgb, expected.rgb)
        np.testing.assert_equal(frame.depth_m, expected.depth_m)
        np.testing.assert_equal(frame.position_enu, expected.position_enu)
        np.testing.assert_equal(target.horizon_enu, label.horizon_enu)
        if version == 3:
            np.testing.assert_equal(frame.depth_valid, expected.depth_valid)
        if version >= 2:
            np.testing.assert_equal(target.horizon_valid, label.horizon_valid)
    actual.frames[0].rgb[:] = 255
    assert not np.any(actual.frames[1].rgb == 255)
    actual.targets[0].horizon_enu[:] = 99
    assert not np.any(actual.targets[1].horizon_enu == 99)


def test_count_mismatch_does_not_decode_large_image_members(tmp_path, monkeypatch):
    import json

    path = write_sequence(tmp_path / "sequence", sequence(3))
    manifest = path / "manifest.json"
    value = json.loads(manifest.read_bytes())
    value["samples"] += 1
    manifest.write_text(json.dumps(value))
    _, counts = count_real_npz_decodes(path, monkeypatch)
    with pytest.raises(ValueError, match="sample count"):
        load_sequence(path)
    assert counts == Counter(sim_ns=1)


def test_full_decoded_image_stack_is_released_before_next_member(tmp_path, monkeypatch):
    import weakref

    path = write_sequence(tmp_path / "sequence", sequence(3))
    with np.load(path / "samples.npz", allow_pickle=False) as archive:
        cls = type(archive)
    original = cls.__getitem__
    previous = []

    def decode(self, key):
        if previous:
            assert previous[0]() is None, "previous full member retained while decoding next"
        value = original(self, key)
        if key != "sim_ns":
            previous[:] = [weakref.ref(value)]
        return value

    monkeypatch.setattr(cls, "__getitem__", decode)
    result = load_sequence(path)
    assert previous[0]() is None
    assert all(frame.rgb.flags.owndata and frame.depth_m.flags.owndata for frame in result.frames)


def test_member_decode_error_closes_actual_archive(tmp_path, monkeypatch):
    path = write_sequence(tmp_path / "sequence", sequence(3))
    original = np.load
    closed = []

    class FailureContext:
        def __init__(self, archive):
            self.archive = archive
            self.files = archive.files

        def __enter__(self):
            self.archive.__enter__()
            return self

        def __exit__(self, *error):
            result = self.archive.__exit__(*error)
            closed.append(self.archive.zip is None)
            return result

        def __getitem__(self, key):
            if key == "rgb":
                raise ValueError("actual decode failure protocol")
            return self.archive[key]

    monkeypatch.setattr(np, "load", lambda *a, **k: FailureContext(original(*a, **k)))
    with pytest.raises(ValueError, match="actual decode failure protocol"):
        load_sequence(path)
    assert closed == [True]
