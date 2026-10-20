"""Bound the owned native child before feeds; no sensor or flight qualification."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            result.update(block)
    return result.hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def inspect_identity(pid, executable, executable_sha, library, library_sha, *,
                     proc_root=Path('/proc'), readlink=os.readlink,
                     device_numbers=None):
    """Controlled files only: maps inode and on-disk SHA, not mapped-memory hashing."""
    if device_numbers is None:
        def device_numbers(dev):
            return os.major(dev), os.minor(dev)
    proc = Path(proc_root)/str(pid)
    facts = {'native_pid': pid, 'admitted': False, 'qualification': False,
             'boundary': 'pre-feed observation; continuous/mapped-memory/all-dependency integrity unknown'}
    try:
        actual_exe = readlink(proc/'exe')
        facts['executable_path'] = actual_exe
        facts['executable_sha256'] = digest(proc/'exe')
        raw = (proc/'maps').read_bytes()
        if len(raw) > 1024**2:
            raise ValueError('maps observation too large')
        facts['maps_raw'] = raw.decode('utf8', errors='strict')
        expected_path = str(Path(library).resolve())
        stat = Path(library).stat()
        device = device_numbers(stat.st_dev)
        facts['library_path'] = expected_path
        facts['library_sha256'] = digest(library)
        rows = []
        for line in facts['maps_raw'].splitlines():
            fields = line.split(None, 5)
            if len(fields) == 6 and 'libov_msckf_lib.so' in fields[5]:
                major, minor = (int(x, 16) for x in fields[3].split(':'))
                rows.append({'path': fields[5], 'permissions': fields[1],
                             'device': [major, minor], 'inode': int(fields[4])})
        facts['library_mappings'] = rows
        facts['admitted'] = (
            actual_exe == str(Path(executable).resolve())
            and facts['executable_sha256'] == executable_sha
            and facts['library_sha256'] == library_sha and bool(rows)
            and any('x' in row['permissions'] for row in rows)
            and all(row['path'] == expected_path and row['inode'] == stat.st_ino
                    and tuple(row['device']) == device for row in rows))
    except (OSError, ValueError, UnicodeError) as error:
        facts['error_type'] = type(error).__name__
        facts['error'] = str(error)
    return facts


def finish_owned(child, output):
    facts = {'native_pid': child.pid, 'before': child.poll(), 'escaped_closure': 'unknown'}
    try:
        if child.poll() is None:
            child.terminate()
            facts['terminate_sent'] = True
        try:
            facts['exit_code'] = child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            facts['kill_sent'] = True
            facts['exit_code'] = child.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        facts['cleanup_error'] = type(error).__name__
        facts['exit_code'] = child.poll()
    finally:
        try:
            child.stdin.close()
        finally:
            write(output+'.identity-cleanup.json', facts)


def run(argv, executable_sha, library, library_sha):
    output = argv[3]
    environment = os.environ.copy()
    for name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT'):
        environment.pop(name, None)
    child = subprocess.Popen([*argv, '--identity-barrier'], stdin=subprocess.PIPE, env=environment)
    try:
        write(output+'.identity-child.json', {'native_pid': child.pid, 'argv': [*argv, '--identity-barrier'],
              'loader_environment_cleared': ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT'], 'qualification': False})
        marker = Path(output+'.identity-ready')
        deadline = time.monotonic()+10
        while True:
            if marker.exists():
                if marker.stat().st_size > 32:
                    raise RuntimeError('native readiness marker too large')
                if marker.read_text().strip() == str(child.pid):
                    break
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('native pre-feed identity readiness absent or PID mismatch')
            time.sleep(0.01)
        facts = inspect_identity(child.pid, argv[0], executable_sha, library, library_sha)
        write(output+'.identity.json', facts)
        if not facts['admitted']:
            raise RuntimeError('native pre-feed identity refused')
        child.stdin.write(b'1')
        child.stdin.flush()
        child.stdin.close()
        code = child.wait(timeout=105)
        write(output+'.identity-completion.json', {'native_pid': child.pid, 'exit_code': code,
              'barrier_released': True, 'qualification': False})
        if code:
            raise RuntimeError('owned native consumer failed')
        return code
    except BaseException:
        finish_owned(child, output)
        raise


if __name__ == '__main__':
    if sys.platform != 'linux':
        raise SystemExit('native identity supervisor requires Linux; no fallback')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable-sha', required=True)
    parser.add_argument('--library', required=True)
    parser.add_argument('--library-sha', required=True)
    parser.add_argument('command', nargs=4)
    args = parser.parse_args()
    raise SystemExit(run(args.command, args.executable_sha, args.library, args.library_sha))
