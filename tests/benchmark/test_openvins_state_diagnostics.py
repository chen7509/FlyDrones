import copy

import numpy as np
import pytest

from tools.benchmark.audit_openvins_state_diagnostics import audit_records


def row(t=16_000_000_000):
    return dict(
        image_ns=t,
        internal_initialized=True,
        public_initialized=False,
        initializer_time_s=3.604,
        state_time_s=t / 1e9,
        last_regular_update_s=-1.0,
        zupt_flag_latched=True,
        has_moved_since_zupt=False,
        quaternion_xyzw=[1.0, 0.0, 0.0, 0.0],
        position=[0.0, 0.0, 0.0],
        velocity=[0.0, 0.0, 0.0],
        imu_covariance=np.eye(15).tolist(),
        feed_camera_wall_s=0.001,
    )


def audit(rows):
    return audit_records(rows, [16_000_000_000, 16_100_000_000], 16_000_000_000, 16_100_000_000)


def test_internal_prearm_state_can_be_screened_without_claiming_fusion():
    result = audit([row(), row(16_100_000_000)])
    assert result["prearm_screen_passed"]
    assert result["public_initialized_frames"] == 0
    assert result["internal_initialized_frames"] == 2
    assert result["eligible_for_px4_fusion"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"velocity": [float("nan"), 0, 0]},
        {"internal_initialized": 1},
        {"unknown": 1},
        {"quaternion_xyzw": [0, 0, 0, 0]},
        {"imu_covariance": [[1.0]]},
        {"initializer_time_s": float("inf")},
        {"feed_camera_wall_s": -1},
        {"public_initialized": True},
        {"position": None},
    ],
)
def test_reject_malformed_values(change):
    bad = row()
    bad.update(change)
    with pytest.raises(ValueError):
        audit([bad, row(16_100_000_000)])


@pytest.mark.parametrize("kind", ["negative", "asymmetric"])
def test_reject_invalid_covariance(kind):
    bad = row()
    if kind == "negative":
        bad["imu_covariance"][0][0] = -1
    else:
        bad["imu_covariance"][0][1] = 0.2
    with pytest.raises(ValueError):
        audit([bad, row(16_100_000_000)])


@pytest.mark.parametrize("delta", [-0.051, 0.051])
def test_stale_and_future_state_fail_screen(delta):
    bad = row()
    bad["state_time_s"] += delta
    assert not audit([bad, row(16_100_000_000)])["prearm_screen_passed"]


def test_lost_initialization_or_reset_is_rejected():
    bad = row(16_100_000_000)
    bad["internal_initialized"] = False
    with pytest.raises(ValueError):
        audit([row(), bad])
    bad = row(16_100_000_000)
    bad["initializer_time_s"] = 4.0
    with pytest.raises(ValueError):
        audit([row(), bad])


def test_missing_duplicate_and_reordered_rows_are_rejected():
    for records in ([row()], [row(), row()], [row(16_100_000_000), row()]):
        with pytest.raises(ValueError):
            audit(records)


def test_uninitialized_sentinel_is_not_healthy():
    bad = row()
    bad.update(
        internal_initialized=False,
        initializer_time_s=-1.0,
        state_time_s=-1.0,
        zupt_flag_latched=False,
        quaternion_xyzw=None,
        position=None,
        velocity=None,
        imu_covariance=None,
    )
    assert not audit([bad, row(16_100_000_000)])["prearm_screen_passed"]
    forged = copy.deepcopy(bad)
    forged["velocity"] = [0, 0, 0]
    with pytest.raises(ValueError):
        audit([forged, row(16_100_000_000)])


def test_large_frame_gap_cannot_pass_continuity_screen():
    result = audit_records([row(), row(16_200_000_000)], [16_000_000_000, 16_200_000_000], 16_000_000_000, 16_200_000_000)
    assert not result["prearm_screen_passed"]


def test_exact_fifty_ms_age_boundary_passes_diagnostic_screen():
    first = row()
    first["state_time_s"] -= 0.05
    assert audit([first, row(16_100_000_000)])["prearm_screen_passed"]


def pending_row():
    pending = row()
    pending.update(
        internal_initialized=False,
        state_time_s=3.604,
        zupt_flag_latched=False,
        quaternion_xyzw=None,
        position=None,
        velocity=None,
        imu_covariance=None,
    )
    return pending


def test_completed_initializer_handoff_is_recorded_but_not_healthy():
    result = audit([pending_row(), row(16_100_000_000)])
    assert result["first_initializer_handoff_image_ns"] == 16_000_000_000
    assert result["first_internal_image_ns"] == 16_100_000_000
    assert result["rows"][0]["reasons"] == ["initializer_handoff_pending"]
    assert not result["prearm_screen_passed"]
    assert not result["eligible_for_px4_fusion"]


@pytest.mark.parametrize(
    "change",
    [
        {"state_time_s": 4.0},
        {"initializer_time_s": 17.0, "state_time_s": 17.0},
        {"zupt_flag_latched": True},
        {"velocity": [0, 0, 0]},
    ],
)
def test_forged_handoff_rejected(change):
    pending = pending_row()
    pending.update(change)
    with pytest.raises(ValueError):
        audit([pending, row(16_100_000_000)])


def test_handoff_cannot_repeat_or_change_initializer():
    second = pending_row()
    second["image_ns"] = 16_100_000_000
    with pytest.raises(ValueError):
        audit([pending_row(), second])
    second = row(16_100_000_000)
    second["initializer_time_s"] = 4.0
    with pytest.raises(ValueError):
        audit([pending_row(), second])


@pytest.mark.parametrize("regular_s", [-0.5, -1.0, 14.0])
def test_regular_update_clock_cannot_regress_or_use_partial_sentinel(regular_s):
    first, second = row(), row(16_100_000_000)
    first.update(public_initialized=True, last_regular_update_s=15.0)
    second.update(public_initialized=regular_s >= 0, last_regular_update_s=regular_s)
    with pytest.raises(ValueError):
        audit([first, second])


def test_missing_window_endpoint_even_when_frame_manifest_is_truncated_fails():
    times = list(range(15_700_000_000, 19_700_000_001, 100_000_000))
    complete = audit_records([row(t) for t in times], times, 15_680_000_000, 19_700_000_000)
    assert complete["prearm_screen_passed"] and complete["prearm_frame_count"] == 41
    for incomplete in (times[:-1], times[1:]):
        assert not audit_records([row(t) for t in incomplete], incomplete, 15_680_000_000, 19_700_000_000)["prearm_screen_passed"]


def test_movement_latch_cannot_regress_without_reset_evidence():
    first = row()
    first["has_moved_since_zupt"] = True
    with pytest.raises(ValueError):
        audit([first, row(16_100_000_000)])
