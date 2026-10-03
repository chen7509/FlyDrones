#!/usr/bin/env python3
"""Strictly pair read-only OpenVINS half-window track histograms with init attempts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
from pathlib import Path

from tools.benchmark.audit_openvins_init_feature_trace import parse_init_feature_trace

FIELDS = ('db', 'tracks', 'old0', 'old1', 'old2', 'new0', 'new1', 'new2',
          'both2', 'old_max', 'new_max')
PATTERN = re.compile(r'newest=([\d.]+) ' + ' '.join(rf'{field}=(\d+)' for field in FIELDS))
COUNTED_STAGES = {'insufficient_features', 'ready'}


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_track_count_trace(log_text: str, feature_rows: list[dict]) -> list[dict]:
    """Reject missing, duplicated or impossible histograms and mismatched disparity counts."""
    required = {int(row['image_ns']): row for row in feature_rows
                if row['attempted'] and row['stage'] in COUNTED_STAGES}
    if not required:
        raise ValueError('no countable initialization attempts')
    found: dict[int, dict] = {}
    for line in log_text.splitlines():
        if 'FD_TRACK_COUNTS' not in line:
            continue
        marker = 'FD_TRACK_COUNTS '
        if line.count(marker) != 1:
            raise ValueError('malformed track-count marker')
        match = PATTERN.fullmatch(line.split(marker, 1)[1].strip())
        if match is None:
            raise ValueError('malformed track-count fields')
        stamp_ns = round(float(match.group(1)) * 1e9)
        if stamp_ns in found or stamp_ns not in required:
            raise ValueError('duplicate or unexpected track-count time')
        data = dict(zip(FIELDS, (int(value) for value in match.groups()[1:])))
        tracks = data['tracks']
        before_cleanup = required[stamp_ns].get('db_features')
        if type(before_cleanup) is not int or data['db'] > before_cleanup:
            raise ValueError('database grew during initialization cleanup')
        if (tracks < data['db'] or tracks != sum(data[k] for k in ('old0', 'old1', 'old2'))
                or tracks != sum(data[k] for k in ('new0', 'new1', 'new2'))
                or data['both2'] > min(data['old2'], data['new2'])
                or (data['old2'] > 0) != (data['old_max'] >= 2)
                or (data['new2'] > 0) != (data['new_max'] >= 2)
                or data['old2'] != required[stamp_ns]['old_features']
                or data['new2'] != required[stamp_ns]['new_features']):
            raise ValueError('track counts disagree with upstream disparity or histogram')
        found[stamp_ns] = {
            'image_ns': stamp_ns,
            'db_before_cleanup': before_cleanup,
            'db_removed_by_cleanup': before_cleanup - data['db'],
            **data,
        }
    if set(found) != set(required):
        raise ValueError('missing track-count rows')
    return [found[stamp] for stamp in sorted(found)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--states', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--episode-result', type=Path, required=True)
    parser.add_argument('--previous-states-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit('refusing existing track eligibility audit')
    with args.states.open(newline='', encoding='utf-8') as stream:
        states = list(csv.DictReader(stream))
    log_text = args.log.read_text(encoding='utf-8', errors='replace')
    features = parse_init_feature_trace(log_text, states)
    counts = parse_track_count_trace(log_text, features)
    episode = json.loads(args.episode_result.read_text(encoding='utf-8'))
    prearm = episode['development_prearm_stationary']
    if prearm['status'] != 'completed':
        raise ValueError('incomplete prearm episode')
    start, end = prearm['start_sim_ns'], prearm['end_sim_ns']
    window = [row for row in counts if start <= row['image_ns'] <= end]
    if not window:
        raise ValueError('no prearm count rows')
    state_hash = _sha(args.states)
    summary = {
        'schema': 'flydrones-openvins-track-eligibility-v1',
        'scope': 'one instrumented offline replay; no PX4 VIO fusion',
        'states_sha256': state_hash,
        'previous_states_sha256': args.previous_states_sha256,
        'states_byte_identical_to_previous': state_hash == args.previous_states_sha256,
        'log_sha256': _sha(args.log),
        'episode_result_sha256': _sha(args.episode_result),
        'attempt_count': len(counts),
        'prearm_attempt_count': len(window),
        'prearm_first': window[0],
        'prearm_last': window[-1],
        'prearm_max_old2': max(row['old2'] for row in window),
        'prearm_max_new2': max(row['new2'] for row in window),
        'prearm_median_counts': {
            field: statistics.median(row[field] for row in window)
            for field in ('db_before_cleanup', 'db_removed_by_cleanup', *FIELDS)
        },
    }
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / 'counts.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=counts[0])
        writer.writeheader()
        writer.writerows(counts)
    with (args.output_dir / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2)
        stream.write('\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
