#!/usr/bin/env python3
"""Align structured upstream initialization diagnostics to saved image times."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

FRAME = re.compile(r'FD_INIT_FRAME t=([\d.]+) db=(\d+)(?![\w.])')
DISP = re.compile(r'FD_INIT_DISP newest=([-\d.]+) old=(\d+) new=(\d+) stage=(\w+)(?![\w.])')
STAGES = {'no_feature_time', 'insufficient_time', 'insufficient_features', 'ready'}


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_init_feature_trace(log_text: str, states: list[dict]) -> list[dict]:
    """Require one disparity decision per attempted frame; retain absent attempts."""
    if not states or any(row.get('initialized') not in ('0', '1') for row in states):
        raise ValueError('invalid OpenVINS states')
    state_ns = [int(row['image_ns']) for row in states]
    if any(b <= a for a, b in zip(state_ns, state_ns[1:])):
        raise ValueError('nonincreasing OpenVINS image times')
    first_initialized = next((i for i, row in enumerate(states)
                              if row['initialized'] == '1'), None)
    if first_initialized is None or first_initialized == 0 or any(
            row['initialized'] != '1' for row in states[first_initialized:]):
        raise ValueError('missing or unstable initialization')
    attempted: dict[int, dict] = {}
    pending: int | None = None
    previous = -1
    for line in log_text.splitlines():
        frame = FRAME.search(line)
        disparity = DISP.search(line)
        if 'FD_INIT_' in line and (frame is not None) == (disparity is not None):
            raise ValueError('malformed initialization diagnostic')
        if frame:
            if pending is not None:
                raise ValueError('attempt missing disparity diagnostic')
            timestamp_ns = round(float(frame.group(1)) * 1e9)
            if timestamp_ns <= previous or timestamp_ns in attempted:
                raise ValueError('duplicate or out-of-order initialization frame')
            attempted[timestamp_ns] = {
                'db_features': int(frame.group(2)), 'old_features': None,
                'new_features': None, 'newest_feature_s': None, 'stage': None,
            }
            pending, previous = timestamp_ns, timestamp_ns
        elif disparity:
            if pending is None:
                raise ValueError('disparity diagnostic without image attempt')
            newest, old, new, stage = (float(disparity.group(1)), int(disparity.group(2)),
                                       int(disparity.group(3)), disparity.group(4))
            if stage not in STAGES or (stage == 'ready' and (old < 15 or new < 15)) or (
                    stage == 'insufficient_features' and old >= 15 and new >= 15):
                raise ValueError('inconsistent disparity diagnostic')
            attempted[pending].update({
                'old_features': old, 'new_features': new,
                'newest_feature_s': newest, 'stage': stage,
            })
            pending = None
    if pending is not None or not attempted:
        raise ValueError('missing complete initialization diagnostics')
    relevant = set(state_ns[:first_initialized + 1])
    if not set(attempted).issubset(relevant):
        raise ValueError('initialization diagnostic lacks matching state image')
    rows = []
    for index in range(first_initialized + 1):
        timestamp_ns = state_ns[index]
        diagnostic = attempted.get(timestamp_ns)
        rows.append({
            'image_ns': timestamp_ns, 'image_s': timestamp_ns * 1e-9,
            'initialized': states[index]['initialized'] == '1',
            'attempted': diagnostic is not None,
            **(diagnostic or {'db_features': None, 'old_features': None,
                              'new_features': None, 'newest_feature_s': None,
                              'stage': None}),
        })
    # try_to_initialize runs in a worker thread. The runner may first observe
    # initialized() on a later camera row than the one that launched the worker.
    last_attempt = next(row for row in reversed(rows) if row['attempted'])
    if last_attempt['stage'] != 'ready':
        raise ValueError('successful initialization has no feature-ready attempt')
    return rows


def summarize_feature_phases(rows: list[dict], prearm_start_s: float,
                             prearm_end_s: float) -> dict:
    if not rows or not prearm_start_s < prearm_end_s:
        raise ValueError('invalid feature phase boundaries')
    result = {}
    for name, selected in (
        ('before_prearm', [row for row in rows if row['image_s'] < prearm_start_s]),
        ('prearm', [row for row in rows if prearm_start_s <= row['image_s'] <= prearm_end_s]),
        ('after_prearm_to_init', [row for row in rows if row['image_s'] > prearm_end_s]),
    ):
        attempts = [row for row in selected if row['attempted']]
        counts = Counter(row['stage'] for row in attempts)
        result[name] = {
            'image_count': len(selected), 'attempts': len(attempts),
            'no_attempt_images': len(selected) - len(attempts),
            'stages': dict(sorted(counts.items())),
            'median_db_features': statistics.median(row['db_features'] for row in attempts)
            if attempts else None,
            'max_old_features': max((row['old_features'] for row in attempts), default=None),
            'max_new_features': max((row['new_features'] for row in attempts), default=None),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--states', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--episode-result', type=Path, required=True)
    parser.add_argument('--baseline-states-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit('output exists; preserve prior feature audit')
    state_hash = _sha(args.states)
    if state_hash != args.baseline_states_sha256:
        raise ValueError('instrumented states differ from frozen baseline')
    with args.states.open(newline='', encoding='utf-8') as stream:
        states = list(csv.DictReader(stream))
    episode = json.loads(args.episode_result.read_text(encoding='utf-8'))
    prearm = episode['development_prearm_stationary']
    if prearm.get('status') != 'completed':
        raise ValueError('prearm evidence incomplete')
    rows = parse_init_feature_trace(args.log.read_text(encoding='utf-8', errors='replace'), states)
    phases = summarize_feature_phases(rows, prearm['start_sim_ns'] * 1e-9,
                                      prearm['end_sim_ns'] * 1e-9)
    summary = {
        'schema': 'flydrones-openvins-init-feature-trace-v1',
        'states_sha256': state_hash, 'log_sha256': _sha(args.log),
        'episode_result_sha256': _sha(args.episode_result),
        'first_initialized_s': rows[-1]['image_s'],
        'last_attempt_s': next(row['image_s'] for row in reversed(rows) if row['attempted']),
        'total_preinitialization_images': len(rows),
        'total_attempts': sum(row['attempted'] for row in rows),
        'phases': phases,
    }
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / 'frame-trace.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with (args.output_dir / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2)
        stream.write('\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
