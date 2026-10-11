import hashlib
import io
import json
import subprocess

import pytest

from tools.benchmark.agent_capture_runtime import OwnedCaptureAgent, agent_runtime_record


def test_agent_runtime_rejects_unpinned_executable(tmp_path):
    bundle = tmp_path / 'runtime-bundle.tar.gz'
    bundle.write_bytes(b'not the sealed bundle')
    binary = tmp_path / 'MicroXRCEAgent'
    binary.write_bytes(b'not the fixed executable')
    lib = tmp_path / 'lib'
    lib.mkdir()
    config = tmp_path / 'agent.json'
    config.write_text(json.dumps(dict(schema='capture-agent-runtime-v1', bundle=str(bundle),
                                      binary=str(binary), lib_dir=str(lib), port=18888)))
    with pytest.raises(ValueError, match='bundle'):
        agent_runtime_record(config)


def test_agent_runtime_rejects_modified_config_and_wrong_port(tmp_path, monkeypatch):
    from tools.benchmark import agent_capture_runtime as module

    monkeypatch.setattr(module, 'BUNDLE_SHA256', hashlib.sha256(b'bundle').hexdigest())
    monkeypatch.setattr(module, 'AGENT_SHA256', hashlib.sha256(b'binary').hexdigest())
    monkeypatch.setattr(module, 'LIBRARY_SHA256', {'libfixed.so': hashlib.sha256(b'lib').hexdigest()})
    bundle = tmp_path / 'runtime-bundle.tar.gz'
    bundle.write_bytes(b'bundle')
    binary = tmp_path / 'MicroXRCEAgent'
    binary.write_bytes(b'binary')
    lib = tmp_path / 'lib'
    lib.mkdir()
    (lib / 'libfixed.so').write_bytes(b'lib')
    config = tmp_path / 'agent.json'
    record = dict(schema='capture-agent-runtime-v1', bundle=str(bundle),
                  binary=str(binary), lib_dir=str(lib), port=18888)
    config.write_text(json.dumps(record))
    actual = agent_runtime_record(config)
    assert actual['configuration'] == record
    assert set(actual['selected_paths']) == {str(config), str(bundle), str(binary), str(lib / 'libfixed.so')}
    (lib / 'libfixed.so').write_bytes(b'changed')
    with pytest.raises(ValueError, match='libfixed'):
        agent_runtime_record(config)
    (lib / 'libfixed.so').write_bytes(b'lib')
    record['port'] = 18889
    config.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='port'):
        agent_runtime_record(config)


def test_agent_runtime_rejects_library_escape(tmp_path, monkeypatch):
    from tools.benchmark import agent_capture_runtime as module

    monkeypatch.setattr(module, 'BUNDLE_SHA256', hashlib.sha256(b'bundle').hexdigest())
    monkeypatch.setattr(module, 'AGENT_SHA256', hashlib.sha256(b'binary').hexdigest())
    monkeypatch.setattr(module, 'LIBRARY_SHA256', {'libfixed.so': hashlib.sha256(b'lib').hexdigest()})
    bundle = tmp_path / 'bundle'
    bundle.write_bytes(b'bundle')
    binary = tmp_path / 'binary'
    binary.write_bytes(b'binary')
    outside = tmp_path / 'outside'
    outside.write_bytes(b'lib')
    lib = tmp_path / 'lib'
    lib.mkdir()
    try:
        (lib / 'libfixed.so').symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation unavailable')
    config = tmp_path / 'agent.json'
    config.write_text(json.dumps(dict(schema='capture-agent-runtime-v1', bundle=str(bundle),
                                      binary=str(binary), lib_dir=str(lib), port=18888)))
    with pytest.raises(ValueError, match='escapes'):
        agent_runtime_record(config)


def test_cleanup_failure_still_reaps_exact_owned_leader(tmp_path):
    calls = []

    class Process:
        pid = 7654

        def poll(self):
            return None

        def terminate(self):
            calls.append('term')

        def kill(self):
            calls.append('kill')

        def wait(self, timeout):
            calls.append(('wait', timeout))
            if 'kill' not in calls:
                raise subprocess.TimeoutExpired('agent', timeout)
            return -9

    class Group:
        errors = [{'operation': 'scan'}]

        def __init__(self, process, stream):
            pass

        def terminate(self):
            calls.append('group-terminate')

        def snapshot(self, label):
            calls.append(label)

        def close(self):
            calls.append('group-close')

        def summary(self):
            return {'graceful_group_cleanup_verified': False, 'errors': self.errors}

    out, err, events = io.StringIO(), io.StringIO(), io.StringIO()
    agent = OwnedCaptureAgent(
        Process(), {'configuration': {'port': 18888}}, tmp_path, out, err, events,
        socket_query=lambda _: '', group_factory=Group,
    )
    result = agent.stop()
    assert calls == ['group-terminate', 'term', ('wait', 5), 'kill', ('wait', 5),
                     'after_leader_reap', 'group-close']
    assert result['exit_code'] == -9
    assert 'leader fallback SIGKILL required' in result['errors']
    assert not result['fusion_qualified']


def test_wrong_listener_pid_latches_failure(tmp_path):
    class Group:
        def __init__(self, process, stream):
            pass

        def identity(self):
            return None

    agent = OwnedCaptureAgent(
        SimpleProcess(), {'configuration': {'port': 18888}}, tmp_path,
        io.StringIO(), io.StringIO(), io.StringIO(), group_factory=Group,
        socket_query=lambda _: ('UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* '
                                'users:(("MicroXRCEAgent",pid=9999,fd=3))'),
    )
    with pytest.raises(ValueError, match='owner mismatch'):
        agent.check(force=True)
    with pytest.raises(ValueError, match='failed or closed'):
        agent.check(force=True)


def test_duplicate_listener_is_terminal_not_startup_pending(tmp_path):
    class Group:
        def __init__(self, process, stream):
            pass

        def identity(self):
            return None

    row = ('UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* '
           'users:(("MicroXRCEAgent",pid=7654,fd=3))\n')
    agent = OwnedCaptureAgent(
        SimpleProcess(), {'configuration': {'port': 18888}}, tmp_path,
        io.StringIO(), io.StringIO(), io.StringIO(), group_factory=Group,
        socket_query=lambda _: row + row,
    )
    with pytest.raises(ValueError, match='exactly one'):
        agent.await_listener()
    assert agent.failure is not None


class SimpleProcess:
    pid = 7654

    def poll(self):
        return None
