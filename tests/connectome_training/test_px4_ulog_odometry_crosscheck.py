"""Synthetic same-message comparison; a match cannot authenticate PX4."""

from dataclasses import dataclass, replace

import numpy as np
import pytest

from flydrones.connectome_training.px4_ros2_source_journal import OfflineOdometryGeometry
from flydrones.connectome_training.px4_ulog_odometry_crosscheck import compare_odometry_to_ulog


def _geometry(index: int) -> OfflineOdometryGeometry:
    return OfflineOdometryGeometry(
        run_id="synthetic-px4", journal_sequence=index,
        journal_sha256="a" * 64, publisher_gid_hex="ab" * 24,
        rmw_implementation="rmw_cyclonedds_cpp",
        rmw_source_timestamp_ns=index * 1_000_000,
        rmw_received_timestamp_ns=index * 1_000_000 + 1,
        rmw_publication_sequence=index, rmw_reception_sequence=index,
        sample_us=index * 10_000, publication_us=index * 10_000 + 10,
        receipt_monotonic_ns=index * 10_000_000,
        pose_frame=1, velocity_frame=1,
        position_ned_m=(1.25 + index, -2.5, 3.75),
        q_body_to_ned_wxyz=(1., 0., 0., 0.),
        velocity_ned_m_s=(0.125, -0.25, 0.375),
        omega_body_frd_rad_s=(0.01, 0.02, 0.03),
        position_variance_m2=(0.1, 0.2, 0.3),
        orientation_variance_rad2=(0.01, 0.02, 0.03),
        velocity_variance_m2_s2=(0.4, 0.5, 0.6),
        reset_counter=0, quality=0, cdr_sha256="b" * 64,
    )


_ARRAYS = {
    "position": "position_ned_m", "q": "q_body_to_ned_wxyz",
    "velocity": "velocity_ned_m_s", "angular_velocity": "omega_body_frd_rad_s",
    "position_variance": "position_variance_m2",
    "orientation_variance": "orientation_variance_rad2",
    "velocity_variance": "velocity_variance_m2_s2",
}


@dataclass(frozen=True)
class Dataset:
    name: str
    multi_id: int
    data: dict


def _datasets(events):
    data = {
        "timestamp": np.array([e.publication_us for e in events], np.uint64),
        "timestamp_sample": np.array([e.sample_us for e in events], np.uint64),
        "pose_frame": np.array([e.pose_frame for e in events], np.uint8),
        "velocity_frame": np.array([e.velocity_frame for e in events], np.uint8),
        "reset_counter": np.array([e.reset_counter for e in events], np.uint8),
        "quality": np.array([e.quality for e in events], np.int8),
    }
    for name, attribute in _ARRAYS.items():
        for axis in range(len(getattr(events[0], attribute))):
            data[f"{name}[{axis}]"] = np.array(
                [getattr(e, attribute)[axis] for e in events], np.float32)
    return [Dataset(name="vehicle_odometry", multi_id=0, data=data)]


def test_two_matching_rows_are_only_structural_parity():
    events = (_geometry(1), _geometry(2))
    result = compare_odometry_to_ulog(events, _datasets(events))
    assert result.reason == "matching_samples_only"
    assert result.matched_samples == 2
    assert result.matching_samples_only is True
    assert result.source_authenticated is False
    assert result.capture_eligible is False
    assert result.training_eligible is False


@pytest.mark.parametrize("mutation,reason", [
    (lambda rows: [], "vehicle_odometry_not_logged"),
    (lambda rows: rows + rows, "odometry_instance_ambiguous"),
    (lambda rows: [replace(rows[0], data={**rows[0].data,
       "timestamp_sample": np.array((10_000, 15_000), np.uint64)})], "missing_logged_sample"),
    (lambda rows: [replace(rows[0], data={**rows[0].data,
       "reset_counter": np.array((0, 1), np.uint8)})], "field_mismatch:reset_counter"),
    (lambda rows: [replace(rows[0], data={**rows[0].data,
       "position[1]": np.array((-2.5, -2.25), np.float32)})], "field_mismatch:position[1]"),
    (lambda rows: [replace(rows[0], data={**rows[0].data,
       "velocity[2]": np.array((0.375, np.nan), np.float32)})], "invalid_float:velocity[2]"),
])
def test_mismatch_or_missing_topic_is_a_refusal(mutation, reason):
    events = (_geometry(1), _geometry(2))
    result = compare_odometry_to_ulog(events, mutation(_datasets(events)))
    assert result.reason == reason
    assert result.matching_samples_only is False
    assert result.source_authenticated is False


def test_journal_identity_or_reset_change_refuses():
    events = (_geometry(1), replace(_geometry(2), reset_counter=1))
    result = compare_odometry_to_ulog(events, _datasets(events))
    assert result.reason == "journal_reset_changed"
    assert result.matching_samples_only is False


@pytest.mark.parametrize("field", [
    "pose_frame", "velocity_frame", "quality",
])
def test_scalar_change_refuses(field):
    events = (_geometry(1), _geometry(2))
    datasets = _datasets(events)
    changed = datasets[0].data.copy()
    changed[field] = changed[field].copy()
    changed[field][1] = 2 if field != "quality" else 1
    result = compare_odometry_to_ulog(events, [replace(datasets[0], data=changed)])
    assert result.reason == f"field_mismatch:{field}"


@pytest.mark.parametrize("array", list(_ARRAYS))
def test_each_float_array_requires_exact_float32_bits(array):
    events = (_geometry(1), _geometry(2))
    datasets = _datasets(events)
    field = f"{array}[0]"
    changed = datasets[0].data.copy()
    changed[field] = changed[field].copy()
    changed[field][1] = np.nextafter(changed[field][1], np.float32(np.inf))
    result = compare_odometry_to_ulog(events, [replace(datasets[0], data=changed)])
    assert result.reason == f"field_mismatch:{field}"


def test_extra_ulog_rows_are_reported_without_continuity_claim():
    events = (_geometry(1), _geometry(2), _geometry(3))
    result = compare_odometry_to_ulog(events[:2], _datasets(events))
    assert result.reason == "matching_samples_only"
    assert result.unmatched_ulog_samples == 1
    assert result.capture_eligible is False


def test_malformed_journal_digest_is_refused():
    events = (replace(_geometry(1), journal_sha256=None), _geometry(2))
    result = compare_odometry_to_ulog(events, _datasets(events))
    assert result.reason == "journal_identity_invalid"


def test_later_cdr_digest_shape_is_refused():
    events = (_geometry(1), replace(_geometry(2), cdr_sha256=None))
    result = compare_odometry_to_ulog(events, _datasets(events))
    assert result.reason == "journal_identity_invalid"


def test_malformed_rmw_identity_is_refused_without_array_exception():
    events = (
        replace(_geometry(1), rmw_implementation=np.array(["rmw", "one"])),
        replace(_geometry(2), rmw_implementation=np.array(["rmw", "two"])),
    )
    result = compare_odometry_to_ulog(events, _datasets(events))
    assert result.reason == "journal_identity_invalid"
