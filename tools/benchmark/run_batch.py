#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Run the frozen 60-episode comparison sequentially and resumably."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.provenance import sha256_file, verify_sealed_manifest
from flydrones.benchmark.runner import verify_freeze_manifest


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temporary.replace(path)


def prepare_job_directories(episode_dir: Path, log_dir: Path) -> None:
    """Keep subprocess logs separate so run_episode can reserve its own output."""
    if episode_dir.exists():
        raise FileExistsError(f'partial episode output already exists: {episode_dir}')
    log_dir.mkdir(parents=True, exist_ok=False)


def start_ego(image: str, name: str, log_dir: Path) -> None:
    mount = str((ROOT / 'tools/benchmark').resolve())
    with (log_dir / 'ego_container_id.txt').open('x', encoding='utf-8') as handle:
        subprocess.check_call([
            'docker', 'run', '-d', '--rm', '-p', '46200:46200', '--name', name,
            '-v', f'{mount}:/benchmark:ro', image, 'bash', '-lc',
            'source /opt/ros/humble/setup.bash && source /ego_ws/install/setup.bash && '
            '(ros2 launch /benchmark/ego.launch.py &) && exec python3 /benchmark/ego_node.py --port 46200',
        ], stdout=handle)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        output = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
        logs = output.stdout + output.stderr
        if 'TCP adapter listening' in logs and 'Waiting for trigger' in logs:
            return
        time.sleep(.25)
    raise TimeoutError('EGO container did not become ready')


def stop_ego(name: str, log_dir: Path) -> None:
    logs = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
    (log_dir / 'ego_container.log').write_text(logs.stdout + logs.stderr, encoding='utf-8')
    subprocess.run(['docker', 'stop', '-t', '3', name], capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze-manifest', type=Path, default=ROOT / 'results/fly-ego-comparison/freeze/manifest.json')
    parser.add_argument('--formal-dir', type=Path, default=ROOT / 'results/fly-ego-comparison/formal')
    args = parser.parse_args()
    freeze = verify_freeze_manifest(args.freeze_manifest, ROOT)
    seed_manifest = json.loads((args.formal_dir / 'seed_manifest.json').read_text(encoding='utf-8'))
    verify_sealed_manifest(seed_manifest)
    if seed_manifest['generated_after_freeze_sha256'] != freeze['manifest_sha256']:
        raise ValueError('formal worlds belong to another freeze')
    worlds = {world['seed']: world for world in seed_manifest['worlds']}
    for world in worlds.values():
        if sha256_file(ROOT / world['world_json']) != world['world_json_sha256']:
            raise ValueError(f'changed formal world JSON: {world["seed"]}')
        if sha256_file(ROOT / world['world_sdf']) != world['world_sdf_sha256']:
            raise ValueError(f'changed formal world SDF: {world["seed"]}')
    jobs_path = args.formal_dir / 'jobs.json'
    if sha256_file(jobs_path) != seed_manifest['jobs_sha256']:
        raise ValueError('formal jobs changed')
    jobs = json.loads(jobs_path.read_text(encoding='utf-8'))
    records = []
    state_path = args.formal_dir / 'batch_state.json'
    for job in jobs:
        verify_freeze_manifest(args.freeze_manifest, ROOT)
        world = worlds[job['seed']]
        episode_dir = args.formal_dir / 'episodes' / str(job['seed']) / job['controller']
        log_dir = args.formal_dir / 'runner_logs' / str(job['seed']) / job['controller']
        result_path = episode_dir / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding='utf-8'))
            records.append({'job': job, 'status': result['status'],
                            'ulog_capture_accepted': result.get('px4_ulog_capture_accepted') is True,
                            'result': str(result_path.relative_to(ROOT)).replace('\\', '/')})
            continue
        prepare_job_directories(episode_dir, log_dir)
        container_name = f'fly-ego-{job["seed"]}' if job['controller'] == 'ego' else None
        try:
            if container_name:
                start_ego(freeze['dependencies']['ego_image_id'], container_name, log_dir)
            command = [
                sys.executable, str(ROOT / 'tools/benchmark/run_episode.py'),
                '--controller', job['controller'],
                '--world-json', str(ROOT / world['world_json']),
                '--world-sdf', str(ROOT / world['world_sdf']),
                '--output', str(episode_dir),
                '--config', str(ROOT / 'configs/fly_ego_benchmark.yaml'),
                '--freeze-manifest', str(args.freeze_manifest),
            ]
            with (log_dir / 'episode.log').open('x', encoding='utf-8') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        finally:
            if container_name:
                stop_ego(container_name, log_dir)
        if not result_path.exists():
            raise RuntimeError(f'episode produced no result: {job["job_id"]}')
        result = json.loads(result_path.read_text(encoding='utf-8'))
        records.append({
            'job': job,
            'returncode': completed.returncode,
            'status': result['status'],
            'ulog_capture_accepted': result.get('px4_ulog_capture_accepted') is True,
            'result': str(result_path.relative_to(ROOT)).replace('\\', '/'),
        })
        atomic_json(state_path, {
            'freeze_manifest_sha256': freeze['manifest_sha256'],
            'updated_utc': datetime.now(timezone.utc).isoformat(),
            'completed': len(records),
            'total': len(jobs),
            'records': records,
        })
        print(json.dumps({'completed': len(records), 'total': len(jobs), 'job': job['job_id'], 'status': result['status']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
