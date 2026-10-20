import hashlib
import json
import os
import sys
from pathlib import Path

import pytest


def test_pre_feed_identity_rejects_another_mapping_and_keeps_raw(tmp_path):
    from tools.benchmark.openvins_native_identity import inspect_identity
    elf = tmp_path/'consumer'
    library = tmp_path/'libov_msckf_lib.so'
    elf.write_bytes(b'ELF fixture')
    library.write_bytes(b'library fixture')
    proc = tmp_path/'proc'/'123'
    proc.mkdir(parents=True)
    (proc/'exe').write_bytes(elf.read_bytes())
    # Platform-independent procfs protocol fixture, not an actual kernel map.
    (proc/'maps').write_bytes(b'1000-2000 r-xp 00000000 00:01 9 /another/libov_msckf_lib.so\n')
    result = inspect_identity(123, elf, hashlib.sha256(elf.read_bytes()).hexdigest(),
                              library, hashlib.sha256(library.read_bytes()).hexdigest(),
                              proc_root=proc.parent, readlink=lambda p: str(elf),
                              device_numbers=lambda d: (0, 0))
    assert result['admitted'] is False
    assert result['maps_raw'].endswith('/another/libov_msckf_lib.so\n')
    assert result['native_pid'] == 123


def test_same_path_wrong_inode_refused_and_bound_mapping_accepted(tmp_path):
    from tools.benchmark.openvins_native_identity import inspect_identity
    elf = tmp_path/'consumer'
    library = tmp_path/'libov_msckf_lib.so'
    elf.write_bytes(b'ELF fixture')
    library.write_bytes(b'library fixture')
    proc = tmp_path/'proc'/'123'
    proc.mkdir(parents=True)
    (proc/'exe').write_bytes(elf.read_bytes())
    stat = library.stat()
    dev = f'{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}' if os.name != 'nt' else '00:00'
    kwargs = {'proc_root': proc.parent, 'readlink': lambda p: str(elf),
              'device_numbers': lambda d: (0, 0)} if os.name == 'nt' else {'proc_root': proc.parent, 'readlink': lambda p: str(elf)}
    def check(inode):
        (proc/'maps').write_text(f'1000-2000 r-xp 00000000 {dev} {inode} {library}\n')
        return inspect_identity(123, elf, hashlib.sha256(elf.read_bytes()).hexdigest(),
                                library, hashlib.sha256(library.read_bytes()).hexdigest(), **kwargs)
    assert check(stat.st_ino + 1)['admitted'] is False
    assert check(stat.st_ino)['admitted'] is True
    library.write_bytes(b'changed')
    result = inspect_identity(123, elf, hashlib.sha256(elf.read_bytes()).hexdigest(),
                              library, hashlib.sha256(b'library fixture').hexdigest(), **kwargs)
    assert result['admitted'] is False


def test_owned_process_barrier_rejection_never_receives_release(tmp_path, monkeypatch):
    from tools.benchmark import openvins_native_identity as m
    class Child:
        pid = 123
        stdin = type('Pipe', (), {'write': lambda self, data: pytest.fail('barrier released'),
                                'close': lambda self: None})()
        stopped = False
        def poll(self):
            return 1 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def wait(self, timeout):
            assert timeout <= 120
            return 1
    child = Child()
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: child)
    marker = tmp_path/'states.csv.identity-ready'
    marker.write_text('123\n')
    monkeypatch.setattr(m, 'inspect_identity', lambda *a: {'native_pid': 123, 'admitted': False})
    with pytest.raises(RuntimeError, match='identity refused'):
        m.run(['elf', 'config', 'data', str(tmp_path/'states.csv')], 'elfsha', 'lib', 'libsha')
    assert child.stopped
    assert json.loads((tmp_path/'states.csv.identity.json').read_text())['admitted'] is False
    assert json.loads((tmp_path/'states.csv.identity-cleanup.json').read_text())['exit_code'] == 1


def test_actual_owned_protocol_child_waits_for_audit_before_release(tmp_path, monkeypatch):
    from tools.benchmark import openvins_native_identity as m
    script = tmp_path/'protocol_child.py'
    script.write_text("import pathlib,os,sys\n"
        "out=pathlib.Path(sys.argv[2])\n"
        "out.with_name(out.name+'.identity-ready').write_text(str(os.getpid()))\n"
        "assert sys.stdin.buffer.read(1)==b'1'\n"
        "assert out.with_name(out.name+'.identity.json').exists()\n"
        "out.write_text('software protocol released, not native estimator')\n")
    output = tmp_path/'states'
    def inspect(pid, *args):
        assert not output.exists()
        return {'native_pid': pid, 'admitted': True, 'fixture': True}
    monkeypatch.setattr(m, 'inspect_identity', inspect)
    assert m.run([sys.executable, str(script), str(output), str(output)], 'fixture', 'fixture', 'fixture') == 0
    completion = json.loads(Path(str(output)+'.identity-completion.json').read_text())
    assert completion['barrier_released'] and completion['exit_code'] == 0
    assert output.read_text().startswith('software protocol')


def test_ready_file_exists_before_pid_write_waits_for_complete_marker(tmp_path, monkeypatch):
    from tools.benchmark import openvins_native_identity as m
    class Pipe:
        def write(self, data):
            assert data == b'1'
        def flush(self):
            pass
        def close(self):
            pass
    class Child:
        pid = 123
        stdin = Pipe()
        def poll(self):
            return None
        def wait(self, timeout):
            return 0
        def terminate(self):
            pytest.fail('valid child rejected')
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: Child())
    output = tmp_path/'states'
    marker = Path(str(output)+'.identity-ready')
    marker.write_text('123\n')
    original = Path.read_text
    reads = []
    def delayed(self, *args, **kwargs):
        if self == marker:
            reads.append(True)
            if len(reads) == 1:
                return ''  # Actual open-before-write interleaving.
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', delayed)
    monkeypatch.setattr(m, 'inspect_identity', lambda *a: {'admitted': True})
    assert m.run(['elf', 'config', 'data', str(output)], 'fixture', 'fixture', 'fixture') == 0
    assert len(reads) >= 2
