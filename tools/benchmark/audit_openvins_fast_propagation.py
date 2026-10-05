"""Audit native 50 Hz inertial predictions; never grants PX4 fusion permission."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from tools.benchmark.audit_openvins_state_diagnostics import _array, _finite

PERIOD_NS = 20_000_000
FLAGS = ('internal_initialized', 'public_initialized', 'success', 'filter_unchanged')
TIMES = ('filter_time_s', 'camera_imu_offset_s', 'propagation_wall_s')
FIELDS = {'target_ns', 'last_camera_ns', 'available_imu_ns', *FLAGS, *TIMES, 'state13', 'covariance12'}


def _clock(values):
    return (bool(values) and all(type(t) is int and t > 0 for t in values)
            and all(b > a for a, b in zip(values, values[1:])))


def audit_records(records, camera_ns, imu_ns, start_ns, end_ns):
    if (not _clock(camera_ns) or not _clock(imu_ns)
            or type(start_ns) is not int or type(end_ns) is not int
            or not camera_ns[0] <= start_ns < end_ns <= camera_ns[-1]
            or imu_ns[0] > camera_ns[0] or imu_ns[-1] <= camera_ns[-1]
            or any(b - a > 4_000_000 for a, b in zip(imu_ns, imu_ns[1:]))):
        raise ValueError('invalid frozen clocks or window')
    targets = list(range(camera_ns[0], camera_ns[-1] + 1, PERIOD_NS))
    if targets[-1] != camera_ns[-1] or len(records) != len(targets):
        raise ValueError('incomplete target grid')
    screened = []
    seen_internal = False
    for row, target in zip(records, targets):
        j = bisect.bisect_left(camera_ns, target) - 1
        last_camera = camera_ns[j] if j >= 0 else None
        available_imu = imu_ns[bisect.bisect_right(imu_ns, target)]
        if (set(row) != FIELDS or type(row['target_ns']) is not int or row['target_ns'] != target
                or row['last_camera_ns'] != last_camera
                or (last_camera is not None and type(row['last_camera_ns']) is not int)
                or type(row['available_imu_ns']) is not int or row['available_imu_ns'] != available_imu
                or any(type(row[k]) is not bool for k in FLAGS)
                or any(not _finite(row[k]) for k in TIMES)
                or row['camera_imu_offset_s'] != 0 or row['propagation_wall_s'] < 0
                or not row['filter_unchanged']
                or (row['public_initialized'] and not row['internal_initialized'])
                or (seen_internal and not row['internal_initialized'])):
            raise ValueError('invalid propagation metadata or clock/reset evidence')
        seen_internal |= row['internal_initialized']
        reasons = []
        if not row['success']:
            if row['state13'] is not None or row['covariance12'] is not None:
                raise ValueError('failed propagation must have null state/covariance')
            reasons.append('propagation_failed' if row['internal_initialized'] else 'not_initialized')
        else:
            if not row['internal_initialized'] or last_camera is None:
                raise ValueError('propagation success without initialization/camera')
            state = _array(row['state13'], (13,))
            covariance = _array(row['covariance12'], (12, 12))
            try:
                with np.errstate(over='raise', invalid='raise'):
                    norm = float(np.linalg.norm(state[:4]))
                    eigenvalues = np.linalg.eigvalsh(covariance)
            except (FloatingPointError, np.linalg.LinAlgError) as exc:
                raise ValueError('invalid propagation numerical range') from exc
            if (not math.isfinite(norm) or abs(norm - 1) > .01
                    or not np.allclose(covariance, covariance.T, atol=1e-8, rtol=0)
                    or not np.all(np.isfinite(eigenvalues)) or eigenvalues.min() < -1e-8):
                raise ValueError('invalid native quaternion/covariance')
            if (not 0 < target * 1e-9 - row['filter_time_s'] <= .1 + 1e-9
                    or abs(row['filter_time_s'] - last_camera * 1e-9) > 1e-9):
                reasons.append('filter_time_mismatch')
        if last_camera is None or not 0 < target - last_camera <= 100_000_000:
            reasons.append('visual_age')
        if not 0 < available_imu - target <= 4_000_000:
            reasons.append('imu_boundary_age')
        screened.append({'target_ns': target, 'success': row['success'], 'screen_passed': not reasons,
                         'reasons': reasons, 'public_initialized': row['public_initialized']})
    window = [r for r in screened if start_ns <= r['target_ns'] <= end_ns]
    return {'schema': 'flydrones-fast-propagation-audit-v1',
            'scope': 'offline native inertial prediction integrity; no live arrival or fusion qualification',
            'targets': len(targets), 'successful_targets': sum(r['success'] for r in screened),
            'first_success_ns': next((r['target_ns'] for r in screened if r['success']), None),
            'prearm_targets': len(window),
            'prearm_screen_passed': bool(window) and all(r['screen_passed'] for r in window),
            'prearm_public_initialized_targets': sum(r['public_initialized'] for r in window),
            'eligible_for_px4_fusion': False,
            'native_velocity_frame': 'IMU/body, not global',
            'covariance_limitations': 'upstream fast discrete approximation; angular-rate correlations incomplete; not calibrated',
            'rows': screened}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('diagnostics', 'frames', 'imu', 'episode-result', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError('audit output exists')
    rows = [json.loads(line) for line in args.diagnostics.read_text().splitlines()]
    def timestamps(path, key, multiplier):
        with path.open() as stream:
            return [int(r[key]) * multiplier for r in csv.DictReader(stream)]
    window = json.loads(args.episode_result.read_text())['development_prearm_stationary']
    if window['status'] != 'completed':
        raise ValueError('prearm capture incomplete')
    result = audit_records(rows, timestamps(args.frames, 'timestamp_ns', 1),
                           timestamps(args.imu, 'timestamp_us', 1000), window['start_sim_ns'], window['end_sim_ns'])
    result['source_sha256'] = {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
                               for name in ('diagnostics', 'frames', 'imu', 'episode_result')}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
