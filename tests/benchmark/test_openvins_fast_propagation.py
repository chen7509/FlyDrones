import bisect
import copy

import numpy as np
import pytest

from tools.benchmark.audit_openvins_fast_propagation import audit_records

FRAMES = [2_600_000_000, 2_700_000_000, 2_800_000_000]
IMU = list(range(2_548_000_000, 2_804_000_001, 4_000_000))


def records():
    rows = []
    for t in range(FRAMES[0], FRAMES[-1] + 1, 20_000_000):
        j = bisect.bisect_left(FRAMES, t) - 1
        camera = FRAMES[j] if j >= 0 else None
        ready = camera is not None
        rows.append(dict(target_ns=t, last_camera_ns=camera,
                         available_imu_ns=IMU[bisect.bisect_right(IMU, t)],
                         filter_time_s=camera / 1e9 if ready else -1.0, camera_imu_offset_s=0.0,
                         internal_initialized=ready, public_initialized=False, success=ready,
                         filter_unchanged=True, propagation_wall_s=0.001,
                         state13=[0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0] if ready else None,
                         covariance12=np.eye(12).tolist() if ready else None))
    return rows


def audit(rows):
    return audit_records(rows, FRAMES, IMU, 2_620_000_000, 2_780_000_000)


def test_complete_native_stream_is_screened_not_fusion_ready():
    result = audit(records())
    assert result['prearm_screen_passed']
    assert result['prearm_targets'] == 9
    assert result['successful_targets'] == 10
    assert not result['eligible_for_px4_fusion']


@pytest.mark.parametrize('change', [
    {'target_ns': 2_630_000_000}, {'last_camera_ns': 2_700_000_000},
    {'available_imu_ns': 2_620_000_000}, {'available_imu_ns': 2_625_000_000},
    {'camera_imu_offset_s': .001}, {'filter_unchanged': False}, {'success': 1},
    {'state13': [float('nan')] * 13}, {'covariance12': [[1]]},
    {'propagation_wall_s': -1}, {'extra': 0},
])
def test_forged_metadata_and_bad_arrays_rejected(change):
    rows = records()
    rows[1].update(change)
    with pytest.raises(ValueError):
        audit(rows)


@pytest.mark.parametrize('kind', ['negative', 'asymmetric', 'quaternion'])
def test_bad_covariance_and_quaternion_rejected(kind):
    rows = records()
    if kind == 'negative':
        rows[1]['covariance12'][0][0] = -1
    elif kind == 'asymmetric':
        rows[1]['covariance12'][0][1] = 0.4
    else:
        rows[1]['state13'][:4] = [0, 0, 0, 0]
    with pytest.raises(ValueError):
        audit(rows)


def test_missing_duplicate_and_reordered_targets_rejected():
    original = records()
    for rows in (original[:-1], original[:1] + original, list(reversed(original))):
        with pytest.raises(ValueError):
            audit(rows)


def test_propagation_failure_is_retained_and_closes_window():
    rows = records()
    rows[1].update(success=False, state13=None, covariance12=None)
    result = audit(rows)
    assert not result['prearm_screen_passed']
    assert result['rows'][1]['reasons'] == ['propagation_failed']


def test_stale_or_future_filter_cannot_pass():
    for time in (2.0, 3.0):
        rows = records()
        rows[1]['filter_time_s'] = time
        assert not audit(rows)['prearm_screen_passed']


def test_success_without_initialization_and_forged_nulls_rejected():
    rows = records()
    rows[1]['internal_initialized'] = False
    with pytest.raises(ValueError):
        audit(rows)
    rows = records()
    rows[0]['state13'] = copy.deepcopy(rows[1]['state13'])
    with pytest.raises(ValueError):
        audit(rows)


def test_invalid_input_clock_and_uncovered_window_rejected():
    with pytest.raises(ValueError):
        audit_records(records(), FRAMES, IMU[:-1], 2_620_000_000, 2_800_000_000)
    with pytest.raises(ValueError):
        audit_records(records(), FRAMES, IMU, 2_620_000_000, 2_820_000_000)
