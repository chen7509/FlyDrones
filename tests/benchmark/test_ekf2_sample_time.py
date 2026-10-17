import copy

import numpy as np
import pytest

from flydrones.benchmark import ekf2_shadow


def audit(frames, topics):
    assert hasattr(ekf2_shadow, "audit_state_sample_times")
    return ekf2_shadow.audit_state_sample_times(frames, topics)


def topics(publication=(200_000,), samples=(50_000,)):
    return {name: {"timestamp": np.array(publication, np.int64),
                   "timestamp_sample": np.array(samples, np.int64)}
            for name in ("vehicle_local_position", "vehicle_attitude")}


def test_recent_publication_cannot_hide_stale_state():
    report = audit([210_000_000], topics())
    row = report["records"][0]
    state = row["topics"]["vehicle_local_position"]
    assert state["publication_age_ns"] == 10_000_000
    assert state["sample_age_ns"] == 160_000_000
    assert state["publication_minus_sample_ns"] == 150_000_000
    assert row["publication_timely"] is True
    assert row["sample_timing_usable"] is False
    assert "vehicle_local_position_sample_stale" in row["reasons"]
    assert report["publication_only_false_fresh_count"] == 1
    assert report["eligible_for_live_capture"] is False
    assert report["clock_epoch_qualified"] is False


def test_publication_causality_beats_matching_sample_time():
    report = audit([100_000_000, 200_000_000, 200_000_001],
                   topics((150_000, 250_000), (100_000, 200_000)))
    assert len(report["records"]) == 3
    assert report["records"][0]["topics"]["vehicle_attitude"] is None
    at_boundary, too_old = report["records"][1:]
    assert at_boundary["sample_timing_usable"] is True
    assert at_boundary["topics"]["vehicle_attitude"]["index"] == 0
    assert too_old["sample_timing_usable"] is False


@pytest.mark.parametrize("sample,reason", [
    ((0,), "sample_zero"), ((210_000,), "sample_after_publication"),
])
def test_bad_sample_retained_with_reason(sample, reason):
    row = audit([220_000_000], topics(samples=sample))["records"][0]
    assert row["sample_timing_usable"] is False
    assert f"vehicle_attitude_{reason}" in row["reasons"]


@pytest.mark.parametrize("samples", [(100_000, 100_000), (100_000, 90_000)])
def test_duplicate_or_regressing_selected_sample_is_not_new_state(samples):
    row = audit([160_000_000], topics((100_000, 150_000), samples))["records"][0]
    assert "vehicle_attitude_sample_nonincreasing" in row["reasons"]


def test_empty_topic_preserves_frames_and_sample_skew_is_explicit():
    data = topics(samples=(190_000,))
    data["vehicle_attitude"]["timestamp_sample"] = np.array([130_000], np.int64)
    row = audit([210_000_000], data)["records"][0]
    assert row["sample_skew_ns"] == 60_000_000
    assert "state_sample_skew" in row["reasons"]
    data["vehicle_attitude"] = {key: np.array([], np.int64) for key in data["vehicle_attitude"]}
    row = audit([210_000_000], data)["records"][0]
    assert row["topics"]["vehicle_attitude"] is None
    assert row["sample_skew_ns"] is None


@pytest.mark.parametrize("bad", [np.array([True]), np.array([200_000.]),
    np.array([-1]), np.array([2**63], np.uint64), np.array([[200_000]])])
@pytest.mark.parametrize("field", ["timestamp", "timestamp_sample"])
def test_timestamp_type_shape_range_refusal(bad, field):
    data = topics()
    data["vehicle_attitude"][field] = bad
    with pytest.raises(ValueError, match=field):
        audit([210_000_000], data)


def test_missing_sample_never_falls_back_to_publication():
    data = topics()
    del data["vehicle_attitude"]["timestamp_sample"]
    with pytest.raises(ValueError, match="timestamp_sample"):
        audit([210_000_000], data)


@pytest.mark.parametrize("frames", [[True], [-1], [1., 2.], [2, 1], [1, 1], [2**63], []])
def test_frame_validation(frames):
    with pytest.raises(ValueError, match="frame"):
        audit(frames, topics())


def test_input_not_mutated_and_nonincreasing_publication_refused():
    data = topics((100_000, 200_000), (90_000, 190_000))
    original = copy.deepcopy(data)
    audit([210_000_000], data)
    for name in data:
        for field in data[name]:
            np.testing.assert_array_equal(data[name][field], original[name][field])
    data["vehicle_attitude"]["timestamp"][:] = 100_000
    with pytest.raises(ValueError, match="timestamp"):
        audit([210_000_000], data)


def test_fault_history_cannot_recover_without_a_new_session_or_poison_the_past():
    report = audit([100_000_000, 300_000_000],
                   topics((100_000, 200_000, 300_000), (90_000, 80_000, 290_000)))
    assert report["records"][0]["sample_timing_usable"] is True
    assert report["records"][1]["sample_timing_usable"] is False
    assert "vehicle_attitude_sample_history_invalid" in report["records"][1]["reasons"]


@pytest.mark.parametrize("attitude_us,expected", [(150_000, True), (149_999, False)])
def test_sample_skew_accepts_exact_limit_and_rejects_next_representable_microsecond(
    attitude_us, expected,
):
    data = topics(samples=(200_000,))
    data["vehicle_attitude"]["timestamp_sample"] = np.array([attitude_us], np.int64)
    row = audit([210_000_000], data)["records"][0]
    assert row["sample_timing_usable"] is expected
    assert ("state_sample_skew" in row["reasons"]) is (not expected)
