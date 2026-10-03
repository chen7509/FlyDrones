#!/usr/bin/env python3
"""Split two already sealed prearm ZIPs for a constrained Git upload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

NAMES = ('openvins-prearm-static-dev-1701',
         'openvins-prearm-static-dev-1701-reviewed')
HEAD_CHUNK_BYTES = 2_000_000
TAIL_CHUNK_BYTES = 1_000_000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split(source_dir: Path, target_dir: Path) -> None:
    for name in NAMES:
        archive_path = source_dir / f'{name}.zip'
        index_path = target_dir / f'{name}.sha256.json'
        manifest_path = target_dir / f'{name}.parts.json'
        if manifest_path.exists():
            raise FileExistsError(manifest_path)
        archive = archive_path.read_bytes()
        index_bytes = index_path.read_bytes()
        index = json.loads(index_bytes)
        if len(archive) != index['archive_bytes'] or sha(archive) != index['archive_sha256']:
            raise ValueError(f'original sealed archive changed: {archive_path}')
        parts = []
        offset = 0
        while offset < len(archive):
            number = len(parts) + 1
            part_name = f'{name}.zip.part{number:03d}'
            size = HEAD_CHUNK_BYTES if number <= 2 else TAIL_CHUNK_BYTES
            payload = archive[offset:offset + size]
            destination = target_dir / part_name
            if destination.exists():
                if destination.read_bytes() != payload:
                    raise ValueError(f'existing uploaded part differs: {destination}')
            else:
                with destination.open('xb') as stream:
                    stream.write(payload)
            parts.append({'name': part_name, 'bytes': len(payload), 'sha256': sha(payload)})
            offset += len(payload)
        manifest = {
            'schema': 'flydrones-evidence-parts-v1',
            'archive': f'{name}.zip', 'archive_bytes': len(archive),
            'archive_sha256': sha(archive),
            'index': index_path.name, 'index_sha256': sha(index_bytes),
            'head_chunk_bytes': HEAD_CHUNK_BYTES,
            'tail_chunk_bytes': TAIL_CHUNK_BYTES, 'parts': parts,
        }
        with manifest_path.open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2)
            stream.write('\n')
        print(f'{name}: {len(parts)} parts, SHA-256 {manifest["archive_sha256"]}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--target-dir', type=Path, required=True)
    args = parser.parse_args()
    split(args.source_dir, args.target_dir)


if __name__ == '__main__':
    main()
