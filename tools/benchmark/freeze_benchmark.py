#!/usr/bin/env python3
"""Seal controller inputs and accepted development-run evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.provenance import freeze_files, seal_manifest, sha256_file


DEVELOPMENT_RESULTS = {
    '1701:fly_raw': 'results/fly-ego-comparison/development/episodes/1701/fly_raw/attempt-15/result.json',
    '1701:fly_guided': 'results/fly-ego-comparison/development/episodes/1701/fly_guided/attempt-1/result.json',
    '1701:ego': 'results/fly-ego-comparison/development/episodes/1701/ego/attempt-4/result.json',
    '1702:fly_raw': 'results/fly-ego-comparison/development/episodes/1702/fly_raw/attempt-1/result.json',
    '1702:fly_guided': 'results/fly-ego-comparison/development/episodes/1702/fly_guided/attempt-1/result.json',
    '1702:ego': 'results/fly-ego-comparison/development/episodes/1702/ego/attempt-1/result.json',
    '1703:fly_raw': 'results/fly-ego-comparison/development/episodes/1703/fly_raw/attempt-1/result.json',
    '1703:fly_guided': 'results/fly-ego-comparison/development/episodes/1703/fly_guided/attempt-1/result.json',
    '1703:ego': 'results/fly-ego-comparison/development/episodes/1703/ego/attempt-1/result.json',
}


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def frozen_inputs() -> list[Path]:
    paths = list((ROOT / 'src/flydrones').rglob('*.py'))
    paths += [
        path for path in (ROOT / 'tools/benchmark').rglob('*')
        if path.is_file() and (path.suffix in {'.py', '.sh'} or path.name == 'Dockerfile.ego')
    ]
    paths += [
        ROOT / 'configs/fly_ego_benchmark.yaml',
        ROOT / 'configs/forest-trained-v2.yaml',
        ROOT / 'data/malecns_full.npz',
        ROOT / 'results/fly-training/connectome-distillation-v2/readout_candidate.json',
        ROOT / 'pyproject.toml',
    ]
    paths += [path for path in (ROOT / 'assets/gazebo').rglob('*') if path.is_file()]
    return sorted(set(paths))


def development_evidence() -> dict:
    evidence = {}
    for key, relative in DEVELOPMENT_RESULTS.items():
        path = ROOT / relative
        result = json.loads(path.read_text(encoding='utf-8'))
        if result['status'] in {'infrastructure_error', 'controller_error'}:
            raise ValueError(f'development result is not valid: {relative}')
        records = [record for record in result['world_control_records'] if record.get('phase') != 'startup']
        deltas = {record['sim_ns_after_run'] - record['sim_ns_before'] for record in records}
        if deltas != {50_000_000} or len(records) != len(result['decisions']):
            raise ValueError(f'non-exact development stepping: {relative}')
        if not result.get('contact_truth_available') or not result.get('offboard_evidence'):
            raise ValueError(f'missing development evidence: {relative}')
        evidence[key] = {
            'path': relative.replace('\\', '/'),
            'sha256': sha256_file(path),
            'status': result['status'],
            'elapsed_sim_s': result['elapsed_sim_s'],
            'minimum_clearance_m': result['minimum_clearance_m'],
            'contact_truth': result['contact_truth'],
            'decisions': len(result['decisions']),
        }
    dynamic = ROOT / 'results/fly-ego-comparison/development/dynamic-probe/episode-2/result.json'
    result = json.loads(dynamic.read_text(encoding='utf-8'))
    pose_records = [record for record in result['world_control_records'] if record.get('method') == 'set_pose']
    if result['status'] != 'timeout' or result['elapsed_sim_s'] != .1 or len(pose_records) != 2:
        raise ValueError('dynamic/wind development probe did not pass')
    evidence['dynamic_wind_probe'] = {
        'path': str(dynamic.relative_to(ROOT)).replace('\\', '/'),
        'sha256': sha256_file(dynamic),
        'status': result['status'],
        'elapsed_sim_s': result['elapsed_sim_s'],
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'results/fly-ego-comparison/freeze/manifest.json')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'refusing to overwrite freeze manifest: {args.output}')
    ego_root = Path.home() / 'fly-ego-benchmark/ego_ws/src/ego-planner-swarm'
    px4_root = Path.home() / 'PX4-Autopilot'
    image_id = command('docker', 'image', 'inspect', 'fly-ego-benchmark:humble', '--format', '{{.Id}}')
    manifest = seal_manifest({
        'phase': 'freeze',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'protocol': {
            'controllers': ['fly_raw', 'fly_guided', 'ego'],
            'development_seeds': [1701, 1702, 1703],
            'formal_families': ['forest', 'corridor', 'mixed', 'disturbed'],
            'worlds_per_family': 5,
            'formal_world_count': 20,
            'formal_episode_count': 60,
            'no_post_freeze_tuning': True,
        },
        'files': freeze_files(frozen_inputs(), ROOT),
        'development': development_evidence(),
        'dependencies': {
            'ego_repository': 'https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git',
            'ego_commit': command('git', '-C', str(ego_root), 'rev-parse', 'HEAD'),
            'ego_status_porcelain': command('git', '-C', str(ego_root), 'status', '--porcelain'),
            'ego_image_id': image_id,
            'px4_commit': command('git', '-C', str(px4_root), 'rev-parse', 'HEAD'),
            'px4_submodules': command(
                'git', '-C', str(px4_root), 'submodule', 'status',
                'Tools/simulation/gz', 'src/modules/mavlink/mavlink',
                'src/modules/uxrce_dds_client/Micro-XRCE-DDS-Client',
            ),
            'pymavlink_commit': command(
                'git', '-C', str(px4_root / 'src/modules/mavlink/mavlink/pymavlink'),
                'rev-parse', 'HEAD',
            ),
            'python': sys.version,
            'platform': platform.platform(),
            'gazebo': command('gz', 'sim', '--versions'),
            'docker': command('docker', 'version', '--format', '{{.Server.Version}}'),
        },
        'model': {
            'neurons': 166700,
            'connections': 25582837,
            'sha256': sha256_file(ROOT / 'data/malecns_full.npz'),
        },
        'known_limitations': [
            'The pinned upstream ROS 2 traj_server uses an unattached wall clock; raw stamps are retained while adapter freshness is anchored to the latest delivered observation simulation time.',
            'Full-connectome inference is slower than real time, so Gazebo is stopped during controller computation.',
        ],
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(args.output)
    print(json.dumps({'manifest': str(args.output), 'sha256': manifest['manifest_sha256']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
