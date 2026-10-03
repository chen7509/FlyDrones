#!/usr/bin/env python3
"""Create a physical near-start texture-board world for one VIO development test."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from flydrones.benchmark.worlds import (
    generate_development_world,
    has_route,
    write_sdf,
)
from tools.benchmark.make_vio_texture_fixture import make_fixture

BOARDS = (
    {'lo': [-5.52, -1.55, .1], 'hi': [-5.48, -.75, 1.4]},
    {'lo': [-5.52, .75, .1], 'hi': [-5.48, 1.55, 1.4]},
)


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def make_prearm_board_fixture(
    source_json: Path, source_sdf: Path, output_dir: Path, *, texture_seed: int = 1701,
) -> dict:
    """Derive two collidable textured boards from the exact public 1701 world."""
    source_json, source_sdf, output_dir = map(Path, (source_json, source_sdf, output_dir))
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError('prearm board fixture output already exists')
    if any(path.is_symlink() or not path.is_file() for path in (source_json, source_sdf)):
        raise ValueError('unsafe or missing source world')
    if type(texture_seed) is not int or texture_seed != 1701:
        raise ValueError('fixed texture seed 1701 required for paired development comparison')
    original = json.loads(source_json.read_text(encoding='utf-8'))
    if original.get('seed') != 1701 or original != generate_development_world(1701):
        raise ValueError('source must be unmodified development seed 1701')

    # Verify that the supplied SDF describes this exact world before deriving
    # from JSON. The temporary file is a single regular file, never a directory.
    with tempfile.NamedTemporaryFile(
        prefix='prearm-world-check-', suffix='.sdf', dir=output_dir.parent, delete=False,
    ) as handle:
        canonical_path = Path(handle.name)
    try:
        write_sdf(original, canonical_path)
        if source_sdf.read_bytes() != canonical_path.read_bytes():
            raise ValueError('source SDF differs from public seed 1701 geometry')
    finally:
        canonical_path.unlink()

    world = copy.deepcopy(original)
    world['boxes'] = [copy.deepcopy(board) for board in BOARDS]
    radius = world['vehicle_envelope_radius_m']
    if not has_route(world, radius):
        raise ValueError('physical boards block the route')
    staging = Path(tempfile.mkdtemp(prefix=output_dir.name + '-source-',
                                    dir=output_dir.parent))
    intended_parent = output_dir.parent.resolve()
    try:
        if staging.resolve().parent != intended_parent:
            raise RuntimeError('temporary source escaped output parent')
        derived_json = staging / 'world.json'
        derived_sdf = staging / 'world.sdf'
        derived_json.write_text(json.dumps(world, indent=2) + '\n', encoding='utf-8')
        write_sdf(world, derived_sdf)
        texture_manifest = make_fixture(
            derived_json, derived_sdf, output_dir, seed=texture_seed,
        )
        with (output_dir / 'derived-source-world.sdf').open('xb') as stream:
            stream.write(derived_sdf.read_bytes())
        texture_manifest_path = output_dir / 'manifest.json'
        texture_manifest_path.rename(output_dir / 'texture-manifest.json')
        manifest = {
            'schema': 'flydrones-openvins-prearm-board-dev-v2',
            'scope': 'single-aircraft development physical boards with collision changes; not a formal benchmark world',
            'source_world_json_sha256': _sha(source_json),
            'source_world_sdf_sha256': _sha(source_sdf),
            'derived_source_world_sdf_sha256': _sha(output_dir / 'derived-source-world.sdf'),
            'generated_world_json_sha256': _sha(output_dir / 'world.json'),
            'generated_world_sdf_sha256': _sha(output_dir / 'world.sdf'),
            'texture_manifest_sha256': _sha(output_dir / 'texture-manifest.json'),
            'ground_albedo_sha256': texture_manifest['ground_albedo_sha256'],
            'obstacle_albedo_sha256': texture_manifest['obstacle_albedo_sha256'],
            'texture_seed': texture_seed,
            'boards': list(BOARDS),
            'route_preserved': True,
            'vehicle_envelope_radius_m': radius,
            'sdf_visual_and_collision': 'generated together by write_sdf',
        }
        with (output_dir / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2)
            stream.write('\n')
        return manifest
    except BaseException as exc:
        # Keep failed output as evidence, but make it impossible to mistake it
        # for a complete fixture or to silently reuse its directory.
        if output_dir.is_dir() and not output_dir.is_symlink():
            with (output_dir / 'INCOMPLETE.json').open('x', encoding='utf-8') as stream:
                json.dump({
                    'status': 'incomplete',
                    'error_type': type(exc).__name__,
                    'retry': 'use a new output directory; do not run this fixture',
                }, stream, indent=2)
                stream.write('\n')
        raise
    finally:
        if staging.resolve().parent != intended_parent:
            raise RuntimeError('refusing unsafe temporary source cleanup')
        shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-json', type=Path, required=True)
    parser.add_argument('--source-sdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--texture-seed', type=int, default=1701)
    args = parser.parse_args()
    print(json.dumps(make_prearm_board_fixture(
        args.source_json, args.source_sdf, args.output_dir,
        texture_seed=args.texture_seed,
    ), indent=2))


if __name__ == '__main__':
    main()
