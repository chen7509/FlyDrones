"""Read-only declared-file evidence; not an atomic snapshot or runtime closure proof."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from collections import deque
from pathlib import Path


def _identity(info):
    return dict(device=info.st_dev, inode=info.st_ino, mode=info.st_mode,
                size=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def _same_path_fd(path_identity, fd_identity):
    # Windows Python 3.12 stat/fstat ctime can expose different timestamps.
    # Retain and compare each API's ctime over time, but not across APIs.
    keys = path_identity.keys() - ({'ctime_ns'} if os.name == 'nt' else set())
    return all(path_identity[key] == fd_identity[key] for key in keys)


def _resolve(path):
    pending = deque(path.parts[1:])
    current = Path(path.anchor)
    links = []
    while pending:
        part = pending.popleft()
        if part == '..':
            current = current.parent
            continue
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            if len(links) >= 40:
                raise ValueError('symlink chain exceeds 40')
            target = os.readlink(current)
            links.append(dict(path=str(current), target=target, identity=_identity(info)))
            parts = Path(target)
            if parts.is_absolute():
                current = Path(parts.anchor)
                pending.extendleft(reversed(parts.parts[1:]))
            else:
                current = current.parent
                pending.extendleft(reversed(parts.parts))
    return current, links


def _digest(stream):
    digest = hashlib.sha256()
    count = 0
    while data := stream.read(1024 * 1024):
        digest.update(data)
        count += len(data)
    return digest.hexdigest(), count


def file_record(path):
    requested = Path(path)
    if '..' in requested.parts:
        raise ValueError('parent traversal in declared path')
    requested = requested.absolute()
    resolved, links = _resolve(requested)
    initial = _identity(resolved.stat())
    if not stat.S_ISREG(initial['mode']):
        raise ValueError('declared artifact is not a regular file')
    with resolved.open('rb') as stream:
        before = _identity(os.fstat(stream.fileno()))
        if not _same_path_fd(initial, before):
            raise ValueError('file identity changed before read')
        digest, count = _digest(stream)
        after = _identity(os.fstat(stream.fileno()))
    final, final_links = _resolve(requested)
    if (before != after or initial != _identity(final.stat()) or resolved != final
            or links != final_links or count != before['size']):
        raise ValueError('declared artifact changed while hashing')
    return dict(requested=str(requested), resolved=str(resolved), links=links,
                identity=before, path_identity=initial, bytes=count, sha256=digest)


def snapshot(inventory):
    if type(inventory) is not dict or not inventory:
        raise ValueError('nonempty declared inventory required')
    started = time.monotonic_ns()
    rows, seen = [], set()
    for role, paths in inventory.items():
        if type(role) is not str or not role.strip() or type(paths) is not list or not paths:
            raise ValueError('nonempty role and explicit path list required')
        for path in paths:
            key = os.path.normcase(str(Path(path).absolute()))
            if key in seen:
                raise ValueError('duplicate declared path')
            seen.add(key)
            rows.append(dict(role=role, **file_record(path)))
    return dict(schema='declared-files-v1', files=rows, started_monotonic_ns=started,
                ended_monotonic_ns=time.monotonic_ns(), runtime_closure_qualified=False,
                scope='declared files only; runtime dlopen, environment and atomic snapshot unqualified')


def verify_unchanged(before, after):
    if (before.get('schema') != 'declared-files-v1' or after.get('schema') != 'declared-files-v1'
            or not before.get('files') or before['files'] != after.get('files')):
        raise ValueError('declared artifact drift or missing snapshot')
    return True


def write_stream(stream, manifest):
    payload = json.dumps(manifest, indent=2, allow_nan=False) + '\n'
    if stream.write(payload) != len(payload):
        raise OSError('short manifest write')
    stream.flush()


def write_manifest(path, manifest):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        write_stream(stream, manifest)


def parse_ldd(output, returncode):
    """Parse trusted installed ELF dependency listings, never execute arbitrary input."""
    if type(returncode) is not int or returncode != 0 or not output.strip():
        raise ValueError('dependency command failed or empty')
    paths = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r'linux-vdso\S* \(0x[0-9a-fA-F]+\)', line):
            continue
        match = re.fullmatch(r'(?:\S+ => )?(/.+) \(0x[0-9a-fA-F]+\)', line)
        if match is None:
            raise ValueError('unresolved or unsupported dependency line: ' + line)
        if match[1] not in paths:
            paths.append(match[1])
    if not paths:
        raise ValueError('no resolved ELF dependencies')
    return paths
