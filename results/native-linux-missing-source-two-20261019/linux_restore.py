"""Exact two-file conditional restore; all other filesystem access is metadata or read-only."""

import base64
import hashlib
import json
import os
import signal
import stat
import struct
import sys
import time

selection = SELECTION  # injected literal, not a Linux file/import
sources = COPY_SOURCES  # verified Windows bytes, injected as base64 literals
caps = selection['caps']
started = time.monotonic()
deadline = started + caps['read_seconds']
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.alarm(caps['read_seconds'])
wire = sys.stdout.buffer
metadata_bytes = payload_bytes = write_bytes = completed = 0
created = []
excluded_ids = {tuple(x) for x in selection['excluded_native_identities']}


class Stop(Exception):
    pass


def check():
    if time.monotonic() >= deadline:
        raise Stop('27s shared restoration/read deadline; no retry')


def info(s):
    return dict(dev=s.st_dev, ino=s.st_ino, mode=s.st_mode, uid=s.st_uid, gid=s.st_gid,
                nlink=s.st_nlink, bytes=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns)


def key(s):
    return s['dev'], s['ino']


def directory_key(s):
    return s['dev'], s['ino'], s['mode'], s['uid'], s['gid']


def emit(row, final=False):
    global metadata_bytes
    raw = json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode()
    if metadata_bytes + len(raw) > caps['metadata_bytes'] - (0 if final else 8192):
        raise Stop('metadata cap; no retry')
    wire.write(b'J' + struct.pack('>I', len(raw)) + raw)
    wire.flush()
    metadata_bytes += len(raw)


def parent_chain(path):
    """Hold no-follow directory FDs; never enumerate or create a directory."""
    parts = path.split('/')
    if not path.startswith('/') or any(p in ('.', '..') for p in parts):
        raise Stop('nonliteral target')
    chain = []
    try:
        root_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        root = info(os.fstat(root_fd))
        chain.append(dict(path='/', name=None, fd=root_fd, before=root))
        current = ''
        for name in parts[1:-1]:
            check()
            if not name:
                raise Stop('empty target component')
            current += '/' + name
            before = info(os.stat(name, dir_fd=chain[-1]['fd'], follow_symlinks=False))
            if not stat.S_ISDIR(before['mode']):
                raise Stop('non-directory or redirected ancestor: ' + current)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=chain[-1]['fd'])
            opened = info(os.fstat(fd))
            if directory_key(opened) != directory_key(before):
                os.close(fd)
                raise Stop('ancestor changed while opening: ' + current)
            chain.append(dict(path=current, name=name, fd=fd, before=opened))
        verify_chain(chain)
        return chain, parts[-1]
    except BaseException:
        for row in reversed(chain):
            os.close(row['fd'])
        raise


def verify_chain(chain):
    check()
    if directory_key(info(os.lstat('/'))) != directory_key(chain[0]['before']):
        raise Stop('root directory changed')
    for index, row in enumerate(chain):
        if directory_key(info(os.fstat(row['fd']))) != directory_key(row['before']):
            raise Stop('held ancestor changed: ' + row['path'])
        if index and directory_key(info(os.stat(row['name'], dir_fd=chain[index-1]['fd'],
                                                follow_symlinks=False))) != directory_key(row['before']):
            raise Stop('ancestor path changed: ' + row['path'])


def file_at(parent, name):
    try:
        return info(os.stat(name, dir_fd=parent, follow_symlinks=False))
    except FileNotFoundError:
        return None


reason = None
complete = False
emit(dict(type='start', pid=os.getpid(), interpreter=sys.executable, selected=2,
          allowed_target_write_bytes=48249, no_other_linux_writes=True,
          no_compiler_or_target=True, no_resource_query=True))
try:
    expected_paths = ['/home/yuchen7509/flydrones-upstream/open_vins/LICENSE',
                      '/home/yuchen7509/flydrones-upstream/open_vins/ReadMe.md']
    if [x['path'] for x in selection['selected']] != expected_paths:
        raise Stop('exact two paths differ')
    if set(sources) != set(expected_paths) or caps['target_write_bytes'] != 48249:
        raise Stop('copy source scope/write cap differs')
    decoded = {}
    for item in selection['selected']:
        check()
        data = base64.b64decode(sources[item['path']], validate=True)
        git = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if (len(data) != item['expected_bytes']
                or hashlib.sha256(data).hexdigest() != item['expected_sha256']
                or git != item['expected_git_blob_sha1']):
            raise Stop('copy bytes differ from fixed manifest; no target writes')
        decoded[item['path']] = data
    if sum(map(len, decoded.values())) != 48249:
        raise Stop('copy aggregate differs')
    for index, item in enumerate(selection['selected']):
        check()
        path = item['path']
        if (path not in selection['allowed_content_endpoints'] or path in selection['excluded']
                or any(path == p or path.startswith(p + '/') for p in selection['forbidden_prefixes'])):
            raise Stop('excluded or unfrozen exact path')
        chain, name = parent_chain(path)
        fd = None
        action = 'unknown'
        try:
            if index == 0 and time.monotonic() - started >= 10:
                raise Stop('first metadata window exhausted within27s')
            parent = chain[-1]['fd']
            before = file_at(parent, name)
            ancestors = [dict(path=r['path'], stat=r['before']) for r in chain]
            emit(dict(type='identity', path=path, resolved=path, links=[], before=before,
                      ancestors=ancestors, status='absent' if before is None else 'observed'))
            verify_chain(chain)
            if before is None:
                # Durable intent is emitted before any side effect; no failed create is retried.
                emit(dict(type='create_intent', path=path, expected_bytes=len(decoded[path]),
                          expected_sha256=item['expected_sha256'], flags='O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC',
                          requested_mode=0o644))
                check()
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o644, dir_fd=parent)
                created.append(path)
                initial = info(os.fstat(fd))
                if (not stat.S_ISREG(initial['mode']) or initial['nlink'] != 1
                        or initial['bytes'] != 0 or key(initial) in excluded_ids):
                    raise Stop('created target identity invalid; preserve file UNKNOWN')
                emit(dict(type='created', path=path, initial=initial))
                action = 'created_from_verified_retained_bytes'
                check()
                if write_bytes + len(decoded[path]) > caps['target_write_bytes']:
                    raise Stop('target write aggregate bound')
                count = os.write(fd, decoded[path])
                write_bytes += max(0, count)
                if count != len(decoded[path]):
                    raise Stop('incomplete write; no delete or retry')
                os.fsync(fd)
                check()
                emit(dict(type='write_complete', path=path, bytes=count, after=info(os.fstat(fd))))
                os.lseek(fd, 0, os.SEEK_SET)
            else:
                if not stat.S_ISREG(before['mode']) or key(before) in excluded_ids:
                    raise Stop('nonregular or excluded old inode; no open/read/write')
                if before['bytes'] > caps['file_bytes']:
                    raise Stop('file cap; no read/write')
                if before['bytes'] != item['expected_bytes']:
                    raise Stop('existing target size differs; no read/write/retry')
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=parent)
                if info(os.fstat(fd)) != before:
                    raise Stop('existing target changed before read')
                action = 'existing_readonly'
            read_before = info(os.fstat(fd))
            verify_chain(chain)
            if (read_before != file_at(parent, name) or key(read_before) in excluded_ids
                    or read_before['bytes'] != item['expected_bytes']
                    or not stat.S_ISREG(read_before['mode'])):
                raise Stop('target identity/size differs before readback')
            if payload_bytes + read_before['bytes'] > caps['total_payload_bytes']:
                raise Stop('payload aggregate cap')
            emit(dict(type='begin', id=index, path=path, resolved=path, before=read_before, action=action))
            digest, git_digest = hashlib.sha256(), hashlib.sha1(b'blob ' + str(read_before['bytes']).encode() + b'\0')
            size = 0
            while size < read_before['bytes']:
                check()
                block = os.read(fd, min(65536, read_before['bytes'] - size))
                if not block:
                    raise Stop('unexpected readback EOF; partial retained')
                size += len(block)
                payload_bytes += len(block)
                digest.update(block)
                git_digest.update(block)
                wire.write(b'D' + struct.pack('>I', len(block)) + block)
                wire.flush()
            read_after = info(os.fstat(fd))
            verify_chain(chain)
            if read_before != read_after or read_after != file_at(parent, name):
                raise Stop('target changed during readback; partial UNKNOWN')
            matches = digest.hexdigest() == item['expected_sha256'] and git_digest.hexdigest() == item['expected_git_blob_sha1']
            emit(dict(type='end', id=index, path=path, resolved=path, before=read_before, after=read_after,
                      prior_target=before, bytes=size, sha256=digest.hexdigest(), git_blob_sha1=git_digest.hexdigest(),
                      stable=True, matches_fixed_manifest=matches, action=action))
            if not matches:
                raise Stop('actual existing/readback contents differ; no overwrite/retry')
            excluded_ids.add(key(read_after))
            completed += 1
        finally:
            if fd is not None:
                os.close(fd)
            for row in reversed(chain):
                os.close(row['fd'])
    complete = completed == 2
except BaseException as exc:
    reason = repr(exc)
try:
    emit(dict(type='completion', complete=complete, reason=reason, elapsed_s=time.monotonic()-started,
              payload_bytes=payload_bytes, target_bytes_written=write_bytes, created_paths=created,
              completed_files=completed, metadata_bytes_before_completion=metadata_bytes,
              all_qualifications=False, dispatchable=False,
              partial_files_not_deleted=True), final=True)
finally:
    signal.alarm(0)
