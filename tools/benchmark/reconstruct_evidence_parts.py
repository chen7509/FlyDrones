#!/usr/bin/env python3
"""Reassemble upload-sized evidence parts and verify the original sealed ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or Path(name).name != name or '\\' in name:
        raise ValueError('invalid part or index name')
    return name


def reconstruct(manifest_path: Path, output: Path) -> None:
    """Reject overwrite and publish only after part, ZIP, and member verification."""
    manifest_path, output = Path(manifest_path), Path(output)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'flydrones-evidence-parts-v1':
        raise ValueError('invalid evidence parts manifest')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    index_path = manifest_path.parent / _safe_name(manifest['index'])
    index_bytes = index_path.read_bytes()
    if _sha(index_bytes) != manifest['index_sha256']:
        raise ValueError('sealed index hash mismatch')
    index = json.loads(index_bytes)
    if (index['archive_sha256'] != manifest['archive_sha256'] or
            index['archive_bytes'] != manifest['archive_bytes']):
        raise ValueError('sealed index and parts manifest disagree')
    parts = manifest['parts']
    if not parts or len({part['name'] for part in parts}) != len(parts):
        raise ValueError('missing or duplicate evidence part')
    chunks = []
    for part in parts:
        path = manifest_path.parent / _safe_name(part['name'])
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'missing or unsafe evidence part: {path}')
        payload = path.read_bytes()
        if len(payload) != part['bytes'] or _sha(payload) != part['sha256']:
            raise ValueError(f'evidence part hash mismatch: {path}')
        chunks.append(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.partial')
    with temporary.open('xb') as stream:
        for chunk in chunks:
            stream.write(chunk)
    if temporary.stat().st_size != manifest['archive_bytes'] or _sha(temporary.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('reassembled archive hash mismatch')
    with zipfile.ZipFile(temporary) as source:
        if len(source.namelist()) != len(index['members']) or set(source.namelist()) != set(index['members']):
            raise ValueError('archive member list mismatch')
        for name, expected in index['members'].items():
            payload = source.read(name)
            if len(payload) != expected['bytes'] or _sha(payload) != expected['sha256']:
                raise ValueError(f'archive member mismatch: {name}')
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reconstruct(args.manifest, args.output)
    print(f'verified: {args.output}')


if __name__ == '__main__':
    main()
