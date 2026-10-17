"""Owned loopback launch boundary. Does not authorize PX4, fusion or flight."""
from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ''):
    _root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_root), str(_root / 'src')]

from tools.benchmark.capture_contract import read_declaration  # noqa: E402
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, verify_unchanged, write_manifest  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import supervise_worker  # noqa: E402
from tools.benchmark.owned_group_evidence import parse_stat  # noqa: E402

ROLES = {'unshare', 'ip', 'python', 'wrapper', 'dependencies', 'command-inputs'}
IDENTITY_KEYS = {'net', 'user', 'uid', 'gid', 'euid', 'egid', 'pid', 'pgrp', 'session', 'start_ticks'}


def validate_identity(value):
    if type(value) is not dict or value.keys() != IDENTITY_KEYS:
        raise ValueError('identity schema')
    for key in ('net', 'user'):
        if type(value[key]) is not str or re.fullmatch(key + r':\[[1-9][0-9]*\]', value[key]) is None:
            raise ValueError('namespace identity')
    for key in IDENTITY_KEYS - {'net', 'user'}:
        if type(value[key]) is not int or not 0 <= value[key] < 2**63:
            raise ValueError('process/credential identity')
    if min(value['pid'], value['pgrp'], value['session']) <= 1:
        raise ValueError('process identity must be non-init')


def validate_observation(parent, observation, ready):
    validate_identity(parent)
    if type(ready) is not bool or type(observation) is not dict or observation.keys() != {
            'identity', 'uid_map', 'gid_map', 'fds', 'topology'}:
        raise ValueError('observation schema')
    who = observation['identity']
    validate_identity(who)
    if (min(parent['uid'], parent['gid']) <= 0 or parent['uid'] != parent['euid'] or parent['gid'] != parent['egid']
            or any(who[k] == parent[k] for k in ('net', 'user', 'pid'))
            or any(who[k] != 0 for k in ('uid', 'gid', 'euid', 'egid'))
            or not who['pid'] == who['pgrp'] == who['session']):
        raise ValueError('not a fresh mapped owned namespace leader')
    for key, number in [('uid_map', parent['uid']), ('gid_map', parent['gid'])]:
        if type(observation[key]) is not str or observation[key].split() != ['0', str(number), '1']:
            raise ValueError('unexpected credential mapping')
    fds = observation['fds']
    if type(fds) is not list or len(fds) != 3:
        raise ValueError('extra/missing inherited descriptor')
    for index, fd in enumerate(fds):
        if (type(fd) is not dict or fd.keys() != {'fd', 'kind'} or type(fd['fd']) is not int
                or fd['fd'] != index or fd['kind'] not in ('char', 'pipe', 'file')):
            raise ValueError('inherited socket/unknown descriptor')
    topology = observation['topology']
    if type(topology) is not dict or topology.keys() != {'links', 'addresses', 'routes'}:
        raise ValueError('topology schema')
    for name in topology:
        if type(topology[name]) is not list or len(topology[name]) > 16 or any(type(x) is not dict for x in topology[name]):
            raise ValueError('invalid topology list')
    links, addresses, routes = (topology[k] for k in ('links', 'addresses', 'routes'))
    if len(links) != 1 or links[0].get('ifname') != 'lo' or links[0].get('link_type') != 'loopback':
        raise ValueError('foreign interface')
    flags = links[0].get('flags')
    if type(flags) is not list or 'LOOPBACK' not in flags or (ready and 'UP' not in flags):
        raise ValueError('loopback is not ready')
    if len(addresses) != 1 or addresses[0].get('ifname') != 'lo' or type(addresses[0].get('addr_info')) is not list:
        raise ValueError('interface address schema')
    seen = []
    for addr in addresses[0]['addr_info']:
        if type(addr) is not dict or type(addr.get('prefixlen')) is not int or addr.get('scope') != 'host':
            raise ValueError('invalid address')
        key = (addr.get('family'), addr.get('local'), addr['prefixlen'])
        if key not in (('inet', '127.0.0.1', 8), ('inet6', '::1', 128)) or key in seen:
            raise ValueError('foreign/duplicate address')
        seen.append(key)
    if ready and ('inet', '127.0.0.1', 8) not in seen:
        raise ValueError('IPv4 loopback absent')
    allowed_routes = {('local', '127.0.0.0/8'), ('local', '127.0.0.1'),
                      ('broadcast', '127.255.255.255'), ('local', '::1')}
    for route in routes:
        if (route.get('dev') != 'lo' or route.get('table') != 'local' or 'gateway' in route
                or (route.get('type'), route.get('dst')) not in allowed_routes):
            raise ValueError('foreign route')


def validate_envelope(doc):
    if type(doc) is not dict or doc.keys() != {'schema', 'command', 'inventory', 'baseline', 'parent', 'environment', 'timeout_s'}:
        raise ValueError('launch envelope schema')
    if doc['schema'] != 'isolated-loopback-launch-v1':
        raise ValueError('launch envelope version')
    validate_identity(doc['parent'])
    timeout = doc['timeout_s']
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError('bounded timeout required')
    inventory = doc['inventory']
    if type(inventory) is not dict or inventory.keys() != ROLES:
        raise ValueError('explicit runtime roles required')
    for role, paths in inventory.items():
        if (type(paths) is not list or not paths or (role not in ('dependencies', 'command-inputs') and len(paths) != 1)
                or any(type(p) is not str or not Path(p).is_absolute() or '..' in Path(p).parts for p in paths)):
            raise ValueError('absolute declared runtime paths required')
    if inventory['wrapper'] != [str(Path(__file__).resolve())]:
        raise ValueError('wrapper source mismatch')
    command = doc['command']
    if (type(command) is not list or not 1 <= len(command) <= 128
            or any(type(x) is not str or '\0' in x for x in command)
            or sum(len(x.encode()) for x in command) > 65536
            or command[0] not in [p for paths in inventory.values() for p in paths]):
        raise ValueError('explicit declared command required')
    env = doc['environment']
    if (type(env) is not dict or not {'HOME', 'PATH', 'LANG', 'LC_ALL'} <= env.keys()
            or any(type(k) is not str or not k or '=' in k or '\0' in k or type(v) is not str or '\0' in v
                   for k, v in env.items()) or sum(len(k.encode()) + len(v.encode()) for k, v in env.items()) > 65536
            or any(k in env for k in ('LD_PRELOAD', 'LD_AUDIT', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'))):
        raise ValueError('explicit clean environment required')
    if type(doc['baseline']) is not dict or doc['baseline'].get('schema') != 'declared-files-v1':
        raise ValueError('declared runtime baseline required')


def namespace_identity():
    proc = parse_stat(Path('/proc/self/stat').read_text())
    return dict(net=os.readlink('/proc/self/ns/net'), user=os.readlink('/proc/self/ns/user'),
                uid=os.getuid(), gid=os.getgid(), euid=os.geteuid(), egid=os.getegid(),
                **{key: proc[key] for key in ('pid', 'pgrp', 'session', 'start_ticks')})


def read_bound_envelope(path, expected_sha256):
    before = file_record(path)
    if before['sha256'] != expected_sha256:
        raise ValueError('declaration hash mismatch')
    doc = read_declaration(path)
    if file_record(path) != before:
        raise ValueError('declaration changed during read')
    validate_envelope(doc)
    return doc


def observe(ip):
    fds = []
    for number in sorted(map(int, os.listdir('/proc/self/fd'))):
        try:
            mode = os.fstat(number).st_mode
        except OSError:
            # The directory-enumeration FD has already been closed by listdir.
            if not Path(f'/proc/self/fd/{number}').exists():
                continue
            raise
        kind = ('socket' if stat.S_ISSOCK(mode) else 'pipe' if stat.S_ISFIFO(mode) else
                'file' if stat.S_ISREG(mode) else 'char' if stat.S_ISCHR(mode) else 'unknown')
        fds.append(dict(fd=number, kind=kind))
    topology = {}
    for name, args in [('links', ['link']), ('addresses', ['address']), ('routes', ['route', 'show', 'table', 'all'])]:
        run = subprocess.run([ip, '-j', *args], capture_output=True, text=True, check=True, timeout=2)
        if len(run.stdout) > 65536 or run.stderr:
            raise ValueError('unexpected ip diagnostic/size')
        topology[name] = json.loads(run.stdout)
    return dict(identity=namespace_identity(), fds=fds, topology=topology,
                uid_map=Path('/proc/self/uid_map').read_text(), gid_map=Path('/proc/self/gid_map').read_text())


class Backend:
    observe = staticmethod(observe)
    snapshot = staticmethod(snapshot)
    write = staticmethod(write_manifest)

    @staticmethod
    def environment():
        return dict(os.environ)

    @staticmethod
    def enable(ip):
        subprocess.run([ip, 'link', 'set', 'lo', 'up'], check=True, timeout=2, capture_output=True)

    @staticmethod
    def run(command, environment):
        # Parent supervisor owns this same original session/group on timeout.
        return subprocess.run(command, env=environment, close_fds=True, check=False).returncode


def run_worker(envelope, output, backend=None):
    backend = backend or Backend()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(status='isolated_command_failed', command_exit=None, gate_verified=False,
                  post_verified=False, errors=[], runtime_closure_qualified=False,
                  physical_network_qualified=False, fusion_qualified=False)
    initial, final = None, None
    try:
        validate_envelope(envelope)
        ip = envelope['inventory']['ip'][0]
        if backend.environment() != envelope['environment']:
            raise ValueError('worker environment mismatch')
        verify_unchanged(envelope['baseline'], backend.snapshot(envelope['inventory']))
        initial = backend.observe(ip)
        backend.write(output / 'initial.json', initial)
        validate_observation(envelope['parent'], initial, False)
        backend.enable(ip)
        ready = backend.observe(ip)
        validate_observation(envelope['parent'], ready, True)
        if ready['identity'] != initial['identity']:
            raise ValueError('identity drift during setup')
        backend.write(output / 'gate.json', ready)
        # Journal write, flush AND close must succeed before this final check/spawn.
        final = backend.observe(ip)
        validate_observation(envelope['parent'], final, True)
        if final != ready:
            raise ValueError('pre-command observation drift')
        verify_unchanged(envelope['baseline'], backend.snapshot(envelope['inventory']))
        if backend.environment() != envelope['environment']:
            raise ValueError('pre-command environment drift')
        result['gate_verified'] = True
        result['command_exit'] = backend.run(envelope['command'], envelope['environment'])
        if type(result['command_exit']) is not int or result['command_exit'] != 0:
            raise ValueError('command exited unsuccessfully')
    except Exception as exc:
        result['errors'].append(dict(phase='command', reason=repr(exc)))
    finally:
        try:
            validate_envelope(envelope)
            post = backend.observe(envelope['inventory']['ip'][0])
            backend.write(output / 'post.json', post)
            validate_observation(envelope['parent'], post, result['gate_verified'])
            if initial is None or post['identity'] != initial['identity']:
                raise ValueError('post-command identity drift')
            if result['gate_verified'] and post != final:
                raise ValueError('post-command observation drift')
            after = backend.snapshot(envelope['inventory'])
            backend.write(output / 'post-files.json', after)
            verify_unchanged(envelope['baseline'], after)
            result['post_verified'] = True
        except Exception as exc:
            result['errors'].append(dict(phase='post', reason=repr(exc)))
    if not result['errors'] and result['gate_verified'] and result['post_verified'] and result['command_exit'] == 0:
        result['status'] = 'isolated_command_completed'
    backend.write(output / 'result.json', result)
    return result


def launch_isolated(command, output, inventory, environment, timeout_s):
    if os.name != 'posix':
        raise RuntimeError('Linux namespace boundary required')
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    document = dict(schema='isolated-loopback-launch-v1', command=command, inventory=inventory,
                    environment=environment, timeout_s=timeout_s, parent=namespace_identity(), baseline=snapshot(inventory))
    validate_envelope(document)
    declaration = output / 'declaration.json'
    write_manifest(declaration, document)
    declaration_record = file_record(declaration)
    argv = [inventory['unshare'][0], '--user', '--map-root-user', '--net', inventory['python'][0],
            '-I', inventory['wrapper'][0], '--worker', str(declaration), declaration_record['sha256'], str(output / 'worker')]
    result = dict(isolated_launch_qualified=False, physical_network_qualified=False,
                  fusion_qualified=False, runtime_closure_qualified=False, errors=[])
    try:
        # Existing environment transport requires paired declaration fields.
        supervisor = supervise_worker(argv, output / 'worker', timeout_s=timeout_s,
                                      launch_environment=environment,
                                      execution_contract=declaration)
        result['supervisor'] = supervisor
        terminal = read_declaration(output / 'worker/result.json')
        result['worker'] = terminal
        if (supervisor['status'] != 'worker_exited' or supervisor['worker_exit'] != 0 or supervisor['errors']
                or not supervisor['cleanup']['graceful_group_cleanup_verified']
                or terminal.get('status') != 'isolated_command_completed'
                or terminal.get('gate_verified') is not True or terminal.get('post_verified') is not True
                or type(terminal.get('command_exit')) is not int or terminal['command_exit'] != 0
                or terminal.get('errors') != []
                or any(terminal.get(k) is not False for k in (
                    'runtime_closure_qualified', 'physical_network_qualified', 'fusion_qualified'))):
            raise ValueError('isolated worker/cleanup did not pass')
    except Exception as exc:
        result['errors'].append(dict(phase='supervisor', reason=repr(exc)))
    finally:
        try:
            after = snapshot(inventory)
            write_manifest(output / 'parent-post-files.json', after)
            verify_unchanged(document['baseline'], after)
            if file_record(declaration) != declaration_record:
                raise ValueError('parent declaration drift')
            if namespace_identity() != document['parent']:
                raise ValueError('parent identity drift')
        except Exception as exc:
            result['errors'].append(dict(phase='parent-post', reason=repr(exc)))
    result['isolated_launch_qualified'] = not result['errors']
    write_manifest(output / 'launch-result.json', result)
    return result


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker':
        raise SystemExit('only declared internal worker entry is supported')
    outcome = run_worker(read_bound_envelope(Path(sys.argv[2]), sys.argv[3]), Path(sys.argv[4]))
    raise SystemExit(0 if outcome['status'] == 'isolated_command_completed' else 2)
