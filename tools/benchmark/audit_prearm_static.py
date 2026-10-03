#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Audit saved prearm RGB/IMU and EKF2 velocity against OpenVINS initialization."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.camera_info_capture import verify_camera_info_capture
from flydrones.benchmark.rgb_capture import verify_rgb_manifest
from flydrones.benchmark.ulog_capture import verify_episode_ulog_evidence
from tools.benchmark.audit_openvins_imu_init import (
    extract_static_init,
    score_ekf_init_velocity,
)


def _coverage(stamps: list[float], start_s: float, end_s: float,
              *, max_gap_s: float) -> dict:
    if len(stamps) < 2 or any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError('sensor timestamps invalid')
    selected = [value for value in stamps if start_s <= value <= end_s]
    max_gap = max((b - a for a, b in zip(selected, selected[1:])), default=float('inf'))
    passed = (len(selected) >= 2 and selected[0] - start_s <= max_gap_s
              and end_s - selected[-1] <= max_gap_s and max_gap <= max_gap_s)
    return {'count': len(selected), 'first_s': selected[0] if selected else None,
            'last_s': selected[-1] if selected else None,
            'max_gap_s': max_gap if np.isfinite(max_gap) else None, 'passed': passed}


def assess_prearm_windows(result: dict, frame_ns: list[int], imu_us: list[int],
                          local_position: dict, init_s: float) -> tuple[dict, dict]:
    """Score the final 2 s of the prearm hold and 2 s before VIO init separately."""
    if (any(result.get(key) is not True for key in (
            'rgb_capture_accepted', 'camera_info_capture_accepted',
            'px4_ulog_capture_accepted')) or result.get('evidence_failures')):
        raise ValueError('incomplete raw capture evidence')
    prearm = result.get('development_prearm_stationary')
    if not isinstance(prearm, dict) or prearm.get('status') != 'completed':
        raise ValueError('incomplete prearm window')
    start_ns, end_ns = prearm.get('start_sim_ns'), prearm.get('end_sim_ns')
    if (type(start_ns) is not int or type(end_ns) is not int or
            not 4. <= (end_ns - start_ns) * 1e-9 <= 4.1):
        raise ValueError('invalid prearm simulation duration')
    full_start_s, end_s = start_ns * 1e-9, end_ns * 1e-9
    start_s = end_s - 2.
    frames_s = [value * 1e-9 for value in frame_ns]
    imu_s = [value * 1e-6 for value in imu_us]
    frame_full = _coverage(frames_s, full_start_s, end_s, max_gap_s=.2)
    imu_full = _coverage(imu_s, full_start_s, end_s, max_gap_s=.02)
    frame_prearm = _coverage(frames_s, start_s, end_s, max_gap_s=.2)
    imu_prearm = _coverage(imu_s, start_s, end_s, max_gap_s=.02)
    frame_init = _coverage(frames_s, init_s - 2., init_s, max_gap_s=.2)
    imu_init = _coverage(imu_s, init_s - 2., init_s, max_gap_s=.02)
    prearm_rows, prearm_velocity = score_ekf_init_velocity(local_position, start_s, end_s)
    init_rows, init_velocity = score_ekf_init_velocity(local_position, init_s - 2., init_s)
    return {
        'schema': 'flydrones-openvins-prearm-static-audit-v1',
        'velocity_reference': 'PX4 EKF2 fusion, not independent physical truth',
        'prearm_start_s': start_ns * 1e-9, 'prearm_end_s': end_s,
        'prearm_scored_start_s': start_s, 'first_initialized_s': init_s,
        'initialization_inside_prearm': start_ns * 1e-9 <= init_s <= end_s,
        'full_prearm_sensor_coverage': {
            'rgb': frame_full, 'imu': imu_full,
            'passed': frame_full['passed'] and imu_full['passed'],
        },
        'prearm_sensor_coverage': {
            'rgb': frame_prearm, 'imu': imu_prearm,
            'passed': frame_prearm['passed'] and imu_prearm['passed'],
        },
        'initialization_sensor_coverage': {
            'rgb': frame_init, 'imu': imu_init,
            'passed': frame_init['passed'] and imu_init['passed'],
        },
        'prearm_static_window': prearm_velocity,
        'initialization_window': init_velocity,
    }, {'prearm': prearm_rows, 'initialization': init_rows}


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode', type=Path, required=True)
    parser.add_argument('--states', type=Path, required=True)
    parser.add_argument('--replay-stdout', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit('output directory exists; preserve earlier audit')
    episode = args.episode.resolve()
    result_path = episode / 'result.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    verify_episode_ulog_evidence(episode, result)
    rgb = verify_rgb_manifest(episode)
    verify_camera_info_capture(episode)
    if len(result['px4_ulogs']) != 1:
        raise ValueError('expected exactly one ULog')
    from pyulog import ULog

    ulog_path = episode / result['px4_ulogs'][0]['path']
    ulog = ULog(str(ulog_path))
    local = ulog.get_dataset('vehicle_local_position').data
    imu = ulog.get_dataset('sensor_combined').data
    with args.states.open(newline='', encoding='utf-8') as stream:
        states = list(csv.DictReader(stream))
    init = extract_static_init(args.replay_stdout.read_text(encoding='utf-8', errors='replace'),
                               states)
    summary, windows = assess_prearm_windows(
        result, [item['frame_ns'] for item in rgb['frames']],
        [int(item) for item in imu['timestamp']], local, init['first_initialized_s'])
    summary.update({
        'source_sha256': {name: _sha(path) for name, path in {
            'result': result_path, 'rgb_manifest': episode / 'rgb-capture-manifest.json',
            'ulog': ulog_path, 'states': args.states, 'replay_stdout': args.replay_stdout,
        }.items()},
        'openvins_initialization': init,
        'prearm_speed_below_0_1_mps': summary['prearm_static_window']['median_speed_m_s'] < .1,
        'initialization_speed_below_0_1_mps': summary['initialization_window']['median_speed_m_s'] < .1,
    })
    args.output_dir.mkdir(parents=True)
    for name, rows in windows.items():
        with (args.output_dir / f'{name}-velocity.csv').open('x', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    with (args.output_dir / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
