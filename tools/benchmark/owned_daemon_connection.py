"""Same-descriptor Linux peer check. No commands, socket unlink or process kill.

SO_PEERCRED reflects the listener's credentials; this is not proof against
inherited/transferred FDs, hostile same-UID races, or unverified launch provenance.
Filesystem/journal blocking needs external supervision. Deadline checks here are
synchronous, not asynchronous cancellation. Successful handover grants no fusion.
"""
from __future__ import annotations

import copy
import os
import re
import socket
import struct
import time
from pathlib import Path, PurePosixPath

from tools.benchmark.owned_group_evidence import DEAD, parse_stat

KEYS = {'pid', 'pgrp', 'session', 'start_ticks', 'uid', 'gid', 'exe', 'cwd',
        'exe_device', 'exe_inode', 'cwd_device', 'cwd_inode', 'net', 'user'}


def validate_owner(row):
    if type(row) is not dict or row.keys() != KEYS:
        raise ValueError('owner schema')
    for key in ('pid', 'pgrp', 'session', 'start_ticks', 'uid', 'gid',
                'exe_device', 'exe_inode', 'cwd_device', 'cwd_inode'):
        minimum = 2 if key == 'pid' else 1 if key in ('pgrp', 'session', 'exe_inode', 'cwd_inode') else 0
        maximum = 2**32 if key in ('uid', 'gid') else 2**64
        if type(row[key]) is not int or not minimum <= row[key] < maximum:
            raise ValueError('owner numeric field: '+key)
    for key in ('exe', 'cwd'):
        if (type(row[key]) is not str or not row[key].startswith('/') or '\0' in row[key]
                or len(row[key].encode()) > 4096 or row[key].endswith(' (deleted)')
                or '..' in PurePosixPath(row[key]).parts):
            raise ValueError('owner path: '+key)
    for key in ('net', 'user'):
        if type(row[key]) is not str or not re.fullmatch(key+r':\[[0-9]{1,20}\]', row[key]):
            raise ValueError('owner namespace: '+key)


def _bounded(path):
    with path.open('r', encoding='utf-8') as stream:
        value = stream.read(65537)
    if len(value) > 65536:
        raise ValueError('proc observation exceeds bound')
    return value


def _owner_once(pid):
    root = Path(f'/proc/{pid}')
    row = parse_stat(_bounded(root/'stat'))
    if row['pid'] != pid or row.pop('state') in DEAD:
        raise ValueError('owner dead or changed')
    status = _bounded(root/'status')
    for label, key in (('Uid', 'uid'), ('Gid', 'gid')):
        matches = re.findall(r'^'+label+r':\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$', status, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError('owner credential fields')
        row[key] = int(matches[0][1])  # effective credential, matched to SO_PEERCRED
    for key in ('exe', 'cwd'):
        row[key] = os.readlink(root/key)
        stat = (root/key).stat()
        row[key+'_device'], row[key+'_inode'] = stat.st_dev, stat.st_ino
    for key in ('net', 'user'):
        row[key] = os.readlink(root/'ns'/key)
    validate_owner(row)
    return row


def observe_owner(process):
    if os.name != 'posix' or type(process.pid) is not int or process.pid <= 1:
        raise ValueError('owned Linux process required')
    if process.poll() is not None:
        raise ValueError('owner exited')
    first = _owner_once(process.pid)
    second = _owner_once(process.pid)
    if first != second or process.poll() is not None:
        raise ValueError('owner changed during observation')
    return first


class _ConnectCleanupFailure(Exception):
    def __init__(self, primary, cleanup):
        self.primary, self.cleanup = primary, cleanup
        super().__init__('connect failed and socket cleanup also failed')


class LinuxBackend:
    clock = staticmethod(time.monotonic_ns)
    observe = staticmethod(observe_owner)

    @staticmethod
    def connect(path, timeout):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(timeout)
            connection.connect(path)
            return connection
        except BaseException as primary:
            try:
                connection.close()
            except BaseException as cleanup:
                raise _ConnectCleanupFailure(primary, cleanup) from primary
            raise

    @staticmethod
    def peer(connection):
        if connection.family != socket.AF_UNIX or connection.type != socket.SOCK_STREAM:
            raise ValueError('connected AF_UNIX stream required')
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('iII'))
        pid, uid, gid = struct.unpack('iII', raw)
        return dict(pid=pid, uid=uid, gid=gid)

    @staticmethod
    def close(connection):
        connection.close()


def _error(exc):
    try:
        return type(exc).__name__+': '+str(exc)
    except BaseException:
        return type(exc).__name__+': <unprintable>'


class ConnectionRefusal(ValueError):
    def __init__(self, evidence):
        self.evidence = copy.deepcopy(evidence)
        super().__init__(evidence['error'])


def connect_owned_daemon(process, expected, path, *, deadline_ns, journal, backend=None):
    backend = backend or LinuxBackend()
    expected = copy.deepcopy(expected)
    connection = None
    result = dict(connection_peer_matched=False, network_authorized=False, fusion_qualified=False,
                  runtime_closure_qualified=False, events=[], error=None, close_error=None,
                  refusal_journal_error=None, peer_observations=[])
    last_clock = None

    def clock():
        nonlocal last_clock
        now = backend.clock()
        if type(now) is not int or not 0 <= now < 2**64 or last_clock is not None and now < last_clock:
            raise ValueError('invalid or regressed connection clock')
        last_clock = now
        if now >= deadline_ns:
            raise TimeoutError('connection deadline expired')
        return now

    def owner():
        current = backend.observe(process)
        validate_owner(current)
        if current != expected:
            raise ValueError('registered owner changed')
        return current

    def peer():
        value = backend.peer(connection)
        result['peer_observations'].append(copy.deepcopy(value))
        if (type(value) is not dict or value.keys() != {'pid', 'uid', 'gid'}
                or any(type(value[k]) is not int or value[k] != expected[k] for k in ('pid', 'uid', 'gid'))):
            raise ValueError('connected peer does not match owned process')
        return value

    def record(kind, **fields):
        event = dict(kind=kind, **fields)
        result['events'].append(copy.deepcopy(event))
        if journal(copy.deepcopy(event)) is not None:
            raise ValueError('journal must return None')

    try:
        validate_owner(expected)
        if type(process.pid) is not int or process.pid != expected['pid']:
            raise ValueError('Popen owner PID mismatch')
        if (type(path) is not str or not path.startswith('/') or '\0' in path
                or '..' in PurePosixPath(path).parts or not 1 <= len(os.fsencode(path)) <= 107):
            raise ValueError('explicit bounded pathname required')
        if type(deadline_ns) is not int or not 0 <= deadline_ns < 2**64 or not callable(journal):
            raise ValueError('bounded deadline and journal required')
        start = clock()
        if deadline_ns-start > 2000000000:
            raise ValueError('connection budget exceeds2s')
        owner()
        record('connect_attempt', path=path, owner=expected, deadline_ns=deadline_ns, at_ns=clock())
        owner()
        connection = backend.connect(path, (deadline_ns-clock())/1e9)
        clock()
        credentials = peer()
        current = owner()
        record('peer_observed', peer=credentials, owner=current, at_ns=clock())
        owner()
        peer()
        result['handover_ns'] = clock()
        result['connection_peer_matched'] = True
        return connection, result
    except BaseException as exc:
        if isinstance(exc, _ConnectCleanupFailure):
            result['close_error'] = _error(exc.cleanup)
            exc = exc.primary
        result['error'] = _error(exc)
        if connection is not None:
            try:
                backend.close(connection)
            except BaseException as close_exc:
                result['close_error'] = _error(close_exc)
        try:
            record('connection_refused', error=result['error'], close_error=result['close_error'])
        except BaseException as journal_exc:
            result['refusal_journal_error'] = _error(journal_exc)
        if not isinstance(exc, Exception):
            raise exc
        raise ConnectionRefusal(result) from exc
