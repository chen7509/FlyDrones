"""Deterministic paired-job manifests and resumable batch bookkeeping."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil

from .provenance import verify_files, verify_sealed_manifest


def build_jobs(seeds: list[int], controllers: list[str]) -> list[dict]:
    if not seeds or not controllers or len(set(controllers)) != len(controllers):
        raise ValueError('seeds and unique controllers are required')
    jobs = []
    for world_index, seed in enumerate(seeds):
        if type(seed) is not int:
            raise ValueError('seeds must be integers')
        order = controllers[world_index % len(controllers):] + controllers[:world_index % len(controllers)]
        for run_index, controller in enumerate(order):
            jobs.append({
                'seed': seed,
                'controller': controller,
                'world_index': world_index,
                'run_index': run_index,
                'job_id': f'{seed}:{controller}',
            })
    return jobs


def pending_jobs(jobs: list[dict], records: list[dict]) -> list[dict]:
    completed = set()
    for record in records:
        key = (record.get('seed'), record.get('controller'))
        if key in completed:
            raise ValueError(f'duplicate terminal record: {key}')
        if not record.get('status'):
            raise ValueError(f'record lacks terminal status: {key}')
        completed.add(key)
    return [job for job in jobs if (job['seed'], job['controller']) not in completed]


def require_frozen_manifest(path: Path, expected_sha256: str) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValueError('evaluation requires a freeze manifest')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('phase') != 'freeze':
        raise ValueError('invalid freeze manifest phase')
    if manifest.get('manifest_sha256') != expected_sha256:
        raise ValueError('freeze manifest mismatch')
    return manifest


def snapshot_episode_inputs(world_json: Path, world_sdf: Path, output: Path) -> tuple[Path, Path]:
    """Copy the shared world into an episode before any backend modification."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    copies = []
    hashes = {}
    for name, source in (('world.json', Path(world_json)), ('world.sdf', Path(world_sdf))):
        if not source.is_file():
            raise FileNotFoundError(source)
        payload = source.read_bytes()
        hashes[f'{name.replace(".", "_")}_sha256'] = hashlib.sha256(payload).hexdigest()
        destination = output / name
        shutil.copy2(source, destination)
        copies.append(destination)
    (output / 'input_manifest.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    return tuple(copies)


def verify_freeze_manifest(path: Path, root: Path) -> dict:
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest.get('phase') != 'freeze':
        raise ValueError('invalid freeze manifest phase')
    verify_sealed_manifest(manifest)
    verify_files(manifest.get('files', {}), Path(root))
    return manifest
