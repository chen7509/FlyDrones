#!/usr/bin/env python3
"""Generate the unseen formal worlds only after the benchmark is sealed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.provenance import seal_manifest, sha256_file
from flydrones.benchmark.runner import build_jobs, verify_freeze_manifest
from flydrones.benchmark.worlds import generate_world, write_sdf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze-manifest', type=Path, default=ROOT / 'results/fly-ego-comparison/freeze/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'results/fly-ego-comparison/formal')
    args = parser.parse_args()
    freeze = verify_freeze_manifest(args.freeze_manifest, ROOT)
    seed_manifest_path = args.output / 'seed_manifest.json'
    if seed_manifest_path.exists():
        raise SystemExit(f'refusing to regenerate formal worlds: {seed_manifest_path}')
    rng = secrets.SystemRandom()
    seeds = []
    while len(seeds) < 20:
        candidate = rng.randrange(10_000_000, 2**63)
        if candidate not in seeds and candidate not in {1701, 1702, 1703, 1704}:
            seeds.append(candidate)
    families = [family for family in ('forest', 'corridor', 'mixed', 'disturbed') for _ in range(5)]
    worlds = []
    for seed, family in zip(seeds, families):
        directory = args.output / 'worlds' / str(seed)
        world = generate_world(seed, family)
        directory.mkdir(parents=True, exist_ok=True)
        json_path, sdf_path = directory / 'world.json', directory / 'world.sdf'
        json_path.write_text(json.dumps(world, indent=2), encoding='utf-8')
        write_sdf(world, sdf_path)
        worlds.append({
            'seed': seed,
            'family': family,
            'candidate': world['candidate'],
            'world_json': str(json_path.relative_to(ROOT)).replace('\\', '/'),
            'world_json_sha256': sha256_file(json_path),
            'world_sdf': str(sdf_path.relative_to(ROOT)).replace('\\', '/'),
            'world_sdf_sha256': sha256_file(sdf_path),
        })
    jobs = build_jobs(seeds, ['fly_raw', 'fly_guided', 'ego'])
    (args.output / 'jobs.json').write_text(json.dumps(jobs, indent=2), encoding='utf-8')
    seed_manifest = seal_manifest({
        'phase': 'formal_worlds',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'generated_after_freeze_sha256': freeze['manifest_sha256'],
        'seed_source': 'Python secrets.SystemRandom backed by operating-system entropy',
        'worlds': worlds,
        'jobs_sha256': sha256_file(args.output / 'jobs.json'),
    })
    seed_manifest_path.write_text(json.dumps(seed_manifest, indent=2), encoding='utf-8')
    print(json.dumps({'worlds': len(worlds), 'episodes': len(jobs), 'seed_manifest_sha256': seed_manifest['manifest_sha256']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
