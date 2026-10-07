import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def mod():
    return importlib.import_module('tools.benchmark.isolated_namespace')


def parent():
    return dict(net='net:[100]', user='user:[101]', uid=1000, gid=1000,
                euid=1000, egid=1000, pid=80, pgrp=80, session=80, start_ticks=10)


def observation():
    return dict(identity=dict(net='net:[200]', user='user:[201]', uid=0, gid=0,
                             euid=0, egid=0, pid=90, pgrp=90, session=90, start_ticks=20),
                uid_map='0 1000 1\n', gid_map='0 1000 1\n',
                fds=[dict(fd=0, kind='char'), dict(fd=1, kind='pipe'), dict(fd=2, kind='pipe')],
                topology=dict(links=[dict(ifname='lo', flags=['LOOPBACK', 'UP'], link_type='loopback')],
                              addresses=[dict(ifname='lo', addr_info=[dict(family='inet', local='127.0.0.1',
                                                                         prefixlen=8, scope='host')])],
                              routes=[dict(type='local', dst='127.0.0.0/8', dev='lo', table='local')]))


def test_accepts_isolated_loopback_but_never_qualifies_flight():
    assert mod().validate_observation(parent(), observation(), True) is None


@pytest.mark.parametrize('change', [
    lambda x: x['identity'].update(net='net:[100]'),
    lambda x: x['identity'].update(user='user:[101]'),
    lambda x: x['identity'].update(pid=True),
    lambda x: x['identity'].update(pgrp=80),
    lambda x: x['identity'].update(uid=1000),
    lambda x: x['identity'].update(net='unknown'),
    lambda x: x.update(uid_map='0 0 1'),
    lambda x: x.update(gid_map='0 1000 1\n1 1001 1'),
    lambda x: x['fds'].append(dict(fd=4, kind='socket')),
    lambda x: x['fds'][1].update(kind='socket'),
    lambda x: x['fds'].append(dict(fd=4, kind='file')),
    lambda x: x['fds'].append(dict(fd=1, kind='pipe')),
    lambda x: x['topology']['links'].append(dict(ifname='eth0', flags=['UP'])),
    lambda x: x['topology']['links'][0].update(flags=['LOOPBACK']),
    lambda x: x['topology']['addresses'][0]['addr_info'][0].update(local='10.0.0.1'),
    lambda x: x['topology']['addresses'][0]['addr_info'][0].update(prefixlen=True),
    lambda x: x['topology']['routes'][0].update(gateway='127.0.0.2'),
    lambda x: x['topology']['routes'][0].update(dst='default'),
    lambda x: x['topology']['routes'][0].update(dev='eth0'),
    lambda x: x['topology'].update(routes=None),
])
def test_refuses_observation_gaps(change):
    value = observation()
    change(value)
    with pytest.raises(ValueError):
        mod().validate_observation(parent(), value, True)


def envelope(tmp_path):
    module = mod()
    files = {}
    for role in ['unshare', 'ip', 'python', 'dependencies', 'command-inputs']:
        path = tmp_path / role
        path.write_text(role)
        files[role] = [str(path)]
    files['wrapper'] = [str(Path(module.__file__).resolve())]
    return dict(schema='isolated-loopback-launch-v1', command=[files['python'][0], 'case'],
                inventory=files, baseline=module.snapshot(files), parent=parent(),
                environment={'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'},
                timeout_s=10)


class Fake:
    def __init__(self, document):
        self.document = document
        self.calls = []
        self.change = None
        self.exit = 0

    def observe(self, ip):
        self.calls.append('observe')
        value = observation()
        if self.change:
            self.change(self, value)
        return value

    def environment(self):
        return dict(self.document['environment'])

    def enable(self, ip):
        self.calls.append('enable')

    def run(self, command, environment):
        self.calls.append('run')
        return self.exit

    def snapshot(self, inventory):
        self.calls.append('snapshot')
        return mod().snapshot(inventory)

    def write(self, path, value):
        self.calls.append(Path(path).name)
        mod().write_manifest(path, value)


def test_worker_closes_gate_evidence_before_command_and_records_post(tmp_path):
    document = envelope(tmp_path)
    backend = Fake(document)
    out = tmp_path / 'worker'
    result = mod().run_worker(document, out, backend=backend)
    assert result['status'] == 'isolated_command_completed'
    assert result['command_exit'] == 0 and result['gate_verified'] is True
    assert result['fusion_qualified'] is False and result['runtime_closure_qualified'] is False
    assert backend.calls.index('gate.json') < backend.calls.index('run') < backend.calls.index('post.json')
    assert json.loads((out / 'result.json').read_text()) == result


@pytest.mark.parametrize('step', ['enable', 'gate.json', 'environment', 'snapshot'])
def test_worker_precommand_error_never_runs_command(tmp_path, step):
    document = envelope(tmp_path)
    backend = Fake(document)
    if step == 'gate.json':
        old = backend.write
        def write(path, value):
            if Path(path).name == step:
                raise OSError('close/short-write failure')
            return old(path, value)
        backend.write = write
    elif step == 'environment':
        backend.environment = lambda: {'LD_PRELOAD': '/unexpected'}
    else:
        def fail(*args):
            raise OSError(step)
        setattr(backend, step, fail)
    result = mod().run_worker(document, tmp_path / 'worker', backend=backend)
    assert result['status'] == 'isolated_command_failed' and result['errors']
    assert 'run' not in backend.calls


def test_worker_late_identity_drift_refuses_before_command(tmp_path):
    document = envelope(tmp_path)
    backend = Fake(document)
    def change(b, value):
        if b.calls.count('observe') >= 3:
            value['identity']['net'] = 'net:[333]'
    backend.change = change
    result = mod().run_worker(document, tmp_path / 'worker', backend=backend)
    assert result['status'] == 'isolated_command_failed'
    assert 'run' not in backend.calls


def test_changed_dependency_between_gate_and_spawn_refuses(tmp_path):
    document = envelope(tmp_path)
    backend = Fake(document)
    old = backend.write
    def write(path, value):
        old(path, value)
        if Path(path).name == 'gate.json':
            Path(document['inventory']['dependencies'][0]).write_text('drift')
    backend.write = write
    result = mod().run_worker(document, tmp_path / 'worker', backend=backend)
    assert result['status'] == 'isolated_command_failed'
    assert 'run' not in backend.calls


def test_nonzero_child_and_post_failure_both_survive(tmp_path):
    document = envelope(tmp_path)
    backend = Fake(document)
    backend.exit = 7
    def change(b, value):
        if 'run' in b.calls:
            raise OSError('post missing')
    backend.change = change
    result = mod().run_worker(document, tmp_path / 'worker', backend=backend)
    assert result['command_exit'] == 7
    assert len(result['errors']) == 2
    assert 'post missing' in str(result['errors'])


def test_post_topology_change_cannot_qualify_success(tmp_path):
    document = envelope(tmp_path)
    backend = Fake(document)
    def change(b, value):
        if 'run' in b.calls:
            value['topology']['routes'] = []
    backend.change = change
    result = mod().run_worker(document, tmp_path / 'worker', backend=backend)
    assert result['status'] == 'isolated_command_failed'
    assert result['post_verified'] is False


def test_parent_passes_real_declaration_path_to_existing_supervisor(tmp_path, monkeypatch):
    module = mod()
    doc = envelope(tmp_path)
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(module, 'namespace_identity', parent)
    calls = []
    def supervisor(command, output, **kwargs):
        assert Path(kwargs['execution_contract']).is_file()
        passed = json.loads(Path(kwargs['execution_contract']).read_text())
        assert passed['command'] == doc['command']
        calls.append(command)
        terminal = module.run_worker(passed, output, backend=Fake(passed))
        assert terminal['gate_verified']
        return dict(status='worker_exited', worker_exit=0, errors=[],
                    cleanup=dict(graceful_group_cleanup_verified=True))
    monkeypatch.setattr(module, 'supervise_worker', supervisor)
    result = module.launch_isolated(doc['command'], tmp_path / 'launch', doc['inventory'], doc['environment'], 10)
    assert result['isolated_launch_qualified'] is True, result
    assert len(calls) == 1


def test_bound_envelope_rejects_changed_command(tmp_path):
    module = mod()
    doc = envelope(tmp_path)
    path = tmp_path / 'declaration.json'
    module.write_manifest(path, doc)
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert module.read_bound_envelope(path, digest) == doc
    doc['command'].append('changed')
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='declaration'):
        module.read_bound_envelope(path, digest)


def test_parent_rejects_success_label_without_gate_evidence(tmp_path, monkeypatch):
    module = mod()
    doc = envelope(tmp_path)
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(module, 'namespace_identity', parent)
    def supervisor(command, output, **kwargs):
        output.mkdir()
        module.write_manifest(output / 'result.json', {'status': 'isolated_command_completed'})
        return dict(status='worker_exited', worker_exit=0, errors=[],
                    cleanup=dict(graceful_group_cleanup_verified=True))
    monkeypatch.setattr(module, 'supervise_worker', supervisor)
    result = module.launch_isolated(doc['command'], tmp_path / 'launch', doc['inventory'], doc['environment'], 10)
    assert result['isolated_launch_qualified'] is False


def test_worker_records_child_spawn_error_and_post_evidence(tmp_path):
    doc = envelope(tmp_path)
    backend = Fake(doc)
    def fail(*args):
        raise OSError('command spawn failed')
    backend.run = fail
    result = mod().run_worker(doc, tmp_path / 'worker', backend=backend)
    assert result['command_exit'] is None and result['post_verified'] is True
    assert 'command spawn failed' in str(result['errors'])


@pytest.mark.parametrize('stage', ['short', 'close'])
def test_actual_manifest_writer_failure_prevents_spawn(tmp_path, monkeypatch, stage):
    module = mod()
    doc = envelope(tmp_path)
    backend = Fake(doc)
    real_open = Path.open
    class Broken:
        def __enter__(self):
            return self
        def write(self, value):
            return len(value) - 1 if stage == 'short' else len(value)
        def flush(self):
            pass
        def __exit__(self, *args):
            if stage == 'close':
                raise OSError('close failed')
    def patched(path, *args, **kwargs):
        return Broken() if path.name == 'gate.json' else real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', patched)
    result = module.run_worker(doc, tmp_path / 'worker', backend=backend)
    assert result['status'] == 'isolated_command_failed' and 'run' not in backend.calls


@pytest.mark.parametrize('change', [
    lambda x: x['inventory'].pop('dependencies'),
    lambda x: x['inventory'].update(wrapper=['/other']),
    lambda x: x.update(command=['/not-declared']),
    lambda x: x.update(timeout_s=True),
    lambda x: x.update(timeout_s=0),
    lambda x: x.update(timeout_s=float('inf')),
    lambda x: x['environment'].update(LD_PRELOAD='/other'),
    lambda x: x.update(schema='unknown'),
    lambda x: x.update(extra='unknown'),
])
def test_strict_envelope_rejects_ambiguous_execution(tmp_path, change):
    document = copy.deepcopy(envelope(tmp_path))
    change(document)
    with pytest.raises(ValueError):
        mod().validate_envelope(document)
