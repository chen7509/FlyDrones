"""Versioned normalized depth validity, without training authorization."""

import json

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
from flydrones.connectome_training.features import (
    FEATURE_NAMES,
    MASKED_FEATURE_NAMES,
    feature_profile_for_names,
    frame_features,
    sequence_tensors,
)


def frame(depth: np.ndarray, mask: np.ndarray | None) -> SequenceFrame:
    return SequenceFrame(
        sim_ns=100,
        frame_ns=100,
        rgb=np.zeros((*depth.shape, 3), np.uint8),
        depth_m=depth,
        position_enu=np.array([0.0, 0.0, 1.0], np.float32),
        velocity_enu=np.zeros(3, np.float32),
        yaw=0.0,
        yaw_rate=0.0,
        goal_enu=np.array([5.0, 0.0, 1.0], np.float32),
        depth_valid=mask,
    )


def sequence(depth: np.ndarray, mask: np.ndarray | None, *, horizon=True) -> TrainingSequence:
    target = TeacherTarget(
        velocity_enu=np.zeros(3, np.float32),
        yaw_rate=0.0,
        horizon_enu=np.array([[1.0, 0.0, 1.0]], np.float32),
        minimum_clearance_m=0.8,
        terminal=False,
        horizon_valid=np.array([True]) if horizon else None,
    )
    provenance = SequenceProvenance("train", 1101, "ego@pinned", "a" * 64, "b" * 64,
                                    "development-capture")
    return TrainingSequence(provenance, [frame(depth, mask)], [target])


def test_v3_round_trip_preserves_nan_and_exact_mask(tmp_path):
    depth = np.array([[1.0, np.nan, 2.0]], np.float32)
    mask = np.array([[True, False, True]], np.bool_)
    out = write_sequence(tmp_path / "v3", sequence(depth, mask))
    assert json.loads((out / "manifest.json").read_text())["schema"] == (
        "flydrones-connectome-sequence-v3"
    )
    with np.load(out / "samples.npz", allow_pickle=False) as arrays:
        assert arrays["depth_valid"].dtype == np.bool_
        assert np.array_equal(arrays["depth_valid"][0], mask)
        assert np.isnan(arrays["depth_m"][0, 0, 1])
        assert "teacher_horizon_valid" in arrays.files
    restored = load_sequence(out)
    assert np.array_equal(restored.frames[0].depth_valid, mask)
    assert np.isnan(restored.frames[0].depth_m[0, 1])


def test_all_invalid_frame_round_trips_as_evidence(tmp_path):
    depth = np.full((1, 3), np.nan, np.float32)
    out = write_sequence(tmp_path / "all-invalid", sequence(depth, np.zeros((1, 3), bool)))
    restored = load_sequence(out)
    assert np.isnan(restored.frames[0].depth_m).all()
    assert not restored.frames[0].depth_valid.any()


def test_v3_rejects_infinite_depth_even_if_mask_marks_it_invalid(tmp_path):
    depth = np.array([[1.0, np.inf, np.nan]], np.float32)
    mask = np.array([[True, False, False]], np.bool_)
    with pytest.raises(ValueError, match="depth"):
        write_sequence(tmp_path / "invalid", sequence(depth, mask))
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("mask", [
    np.array([[1, 0, 1]], np.uint8),
    np.array([True, False, True], np.bool_),
    np.array([[True, True, True]], np.bool_),
    np.array([[False, False, True]], np.bool_),
])
def test_wrong_depth_mask_is_rejected_before_output(tmp_path, mask):
    depth = np.array([[1.0, np.nan, 2.0]], np.float32)
    with pytest.raises(ValueError, match="depth_valid"):
        write_sequence(tmp_path / "rejected", sequence(depth, mask))
    assert not (tmp_path / "rejected").exists()


def test_mask_requires_horizon_validity_before_output(tmp_path):
    depth = np.ones((1, 3), np.float32)
    with pytest.raises(ValueError, match="horizon_valid"):
        write_sequence(tmp_path / "rejected", sequence(depth, np.ones((1, 3), bool),
                                                      horizon=False))
    assert not (tmp_path / "rejected").exists()


def test_v3_requires_float32_depth_and_matching_rgb_geometry(tmp_path):
    depth = np.ones((1, 3), np.float64)
    with pytest.raises(ValueError, match="depth_m"):
        write_sequence(tmp_path / "wrong-dtype", sequence(depth, np.ones((1, 3), bool)))
    data = sequence(np.ones((1, 3), np.float32), np.ones((1, 3), bool))
    data.frames[0].rgb = np.zeros((1, 4, 3), np.uint8)
    with pytest.raises(ValueError, match="depth geometry"):
        write_sequence(tmp_path / "wrong-rgb", data)


def test_masked_and_unmasked_frames_cannot_mix(tmp_path):
    depth = np.ones((1, 3), np.float32)
    data = sequence(depth, np.ones((1, 3), bool))
    later = frame(depth, None)
    later.sim_ns = later.frame_ns = 200
    data.frames.append(later)
    data.targets.append(data.targets[0])
    with pytest.raises(ValueError, match="mixed depth validity"):
        write_sequence(tmp_path / "rejected", data)
    assert not (tmp_path / "rejected").exists()


def test_v3_sample_hash_tampering_is_rejected(tmp_path):
    depth = np.array([[1.0, np.nan, 2.0]], np.float32)
    out = write_sequence(tmp_path / "v3", sequence(depth, np.array([[True, False, True]])))
    samples = out / "samples.npz"
    with samples.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_sequence(out)


def test_old_feature_adapter_refuses_even_all_valid_v3_depth():
    depth = np.ones((1, 3), np.float32)
    with pytest.raises(ValueError, match="masked depth feature profile not implemented"):
        frame_features(frame(depth, np.ones((1, 3), bool)))


def test_masked_feature_profile_uses_only_measured_depth_and_exposes_coverage():
    depth = np.array([[1.0, np.nan, 2.0, 4.0, np.nan, np.nan]], np.float32)
    mask = np.isfinite(depth)
    sample = frame(depth, mask)
    expected = [1.0, 1.0 / 3.0, 0.0, 0.5, 1.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.25]
    assert len(MASKED_FEATURE_NAMES) == 15
    assert MASKED_FEATURE_NAMES[3:6] == (
        "depth_valid_left", "depth_valid_center", "depth_valid_right",
    )
    assert frame_features(sample, profile="depth-mask-v3") == pytest.approx(expected)
    assert sequence_tensors(sequence(depth, mask), profile="depth-mask-v3")[0][0, 0] == (
        pytest.approx(expected)
    )


def test_feature_order_selects_exact_version_without_relabeling():
    assert feature_profile_for_names(FEATURE_NAMES) == "legacy-v1"
    assert feature_profile_for_names(MASKED_FEATURE_NAMES) == "depth-mask-v3"
    with pytest.raises(ValueError, match="feature order"):
        feature_profile_for_names(tuple(reversed(MASKED_FEATURE_NAMES)))


def test_masked_feature_profile_refuses_wholly_missing_depth():
    depth = np.full((1, 6), np.nan, np.float32)
    with pytest.raises(ValueError, match="valid pixel"):
        frame_features(frame(depth, np.zeros((1, 6), np.bool_)), profile="depth-mask-v3")


@pytest.mark.parametrize("depth,mask", [
    (np.array([[1.0, np.inf, 2.0]], np.float32), np.array([[True, False, True]])),
    (np.array([[1.0, np.nan, 2.0]], np.float32), np.array([[True, True, True]])),
    (np.array([[1.0, np.nan, 2.0]], np.float64), np.array([[True, False, True]])),
    (np.array([[1.0, np.nan, 2.0]], np.float32), np.array([[1, 0, 1]], np.uint8)),
])
def test_masked_feature_profile_rejects_invalid_geometry_or_mask(depth, mask):
    with pytest.raises(ValueError, match="depth|mask"):
        frame_features(frame(depth, mask), profile="depth-mask-v3")


def test_masked_feature_profile_rejects_invalid_rgb_or_state():
    depth = np.ones((1, 3), np.float32)
    sample = frame(depth, np.ones((1, 3), np.bool_))
    sample.rgb = np.zeros((1, 3, 3), np.float32)
    with pytest.raises(ValueError, match="rgb|mask"):
        frame_features(sample, profile="depth-mask-v3")
    sample.rgb = np.zeros((1, 3, 3), np.uint8)
    sample.velocity_enu[0] = np.inf
    with pytest.raises(ValueError, match="state"):
        frame_features(sample, profile="depth-mask-v3")


def test_unmasked_legacy_schema_is_unchanged(tmp_path):
    depth = np.ones((1, 3), np.float32)
    data = sequence(depth, None)
    out = write_sequence(tmp_path / "v2", data)
    assert json.loads((out / "manifest.json").read_text())["schema"] == (
        "flydrones-connectome-sequence-v2"
    )
    assert load_sequence(out).frames[0].depth_valid is None
