import io
import json
import os

import pytest

from tools.benchmark import declared_runtime_snapshot as snap


def test_snapshot_preserves_role_path_and_content(tmp_path):
    p = tmp_path / 'gz_env.sh'
    p.write_bytes(b'abc')
    result = snap.snapshot({'px4_startup': [p]})
    row = result['files'][0]
    assert row['role'] == 'px4_startup'
    assert row['sha256'] == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert row['bytes'] == 3
    assert row['resolved'] == str(p.resolve())
    assert result['runtime_closure_qualified'] is False


@pytest.mark.parametrize('kind', ['missing', 'directory', 'empty_role', 'empty_inventory', 'duplicate'])
def test_silent_omissions_are_refused(tmp_path, kind):
    p = tmp_path / 'binding.so'
    p.write_bytes(b'binding')
    cases = {'missing': {'binding': [tmp_path / 'absent']}, 'directory': {'binding': [tmp_path]},
             'empty_role': {'binding': []}, 'empty_inventory': {}, 'duplicate': {'a': [p], 'b': [p]}}
    with pytest.raises((ValueError, OSError)):
        snap.snapshot(cases[kind])


def test_in_read_mutation_refuses(tmp_path, monkeypatch):
    p = tmp_path / 'lib.so'
    p.write_bytes(b'abc')
    original = snap._digest
    def mutate(stream):
        result = original(stream)
        p.write_bytes(b'changed-length')
        return result
    monkeypatch.setattr(snap, '_digest', mutate)
    with pytest.raises(ValueError, match='changed'):
        snap.snapshot({'library': [p]})


def test_post_snapshot_content_drift_refuses(tmp_path):
    p = tmp_path / 'start'
    p.write_bytes(b'before')
    before = snap.snapshot({'startup': [p]})
    p.write_bytes(b'after')
    after = snap.snapshot({'startup': [p]})
    with pytest.raises(ValueError, match='drift'):
        snap.verify_unchanged(before, after)


def test_post_snapshot_same_content_replacement_refuses(tmp_path):
    p = tmp_path / 'start'
    p.write_bytes(b'before')
    before = snap.snapshot({'startup': [p]})
    q = tmp_path / 'new'
    q.write_bytes(b'before')
    os.replace(q, p)
    with pytest.raises(ValueError, match='drift'):
        snap.verify_unchanged(before, snap.snapshot({'startup': [p]}))


def test_exclusive_manifest_and_shortwrite(tmp_path):
    p = tmp_path / 'snapshot.json'
    snap.write_manifest(p, {'value': 1})
    assert json.loads(p.read_text()) == {'value': 1}
    with pytest.raises(FileExistsError):
        snap.write_manifest(p, {'value': 2})
    class Short(io.StringIO):
        def write(self, text):
            return len(text) - 1
    with pytest.raises(OSError, match='short'):
        snap.write_stream(Short(), {'value': 1})


def test_flush_failure_propagates():
    class Broken(io.StringIO):
        def flush(self):
            raise OSError('flush failed')
    with pytest.raises(OSError, match='flush'):
        snap.write_stream(Broken(), {'value': 1})


def test_close_failure_cannot_return_manifest_success(tmp_path, monkeypatch):
    class CloseFailure(io.StringIO):
        def close(self):
            super().close()
            raise OSError('close failed')
    stream = CloseFailure()
    monkeypatch.setattr(type(tmp_path), 'open', lambda *a, **k: stream)
    with pytest.raises(OSError, match='close failed'):
        snap.write_manifest(tmp_path / 'manifest.json', {'value': 1})
    assert stream.closed


def test_ldd_requires_success_and_resolved_files():
    output = 'linux-vdso.so.1 (0x0001)\n libx.so => /usr/lib/libx.so (0x0002)\n /lib/ld-linux.so (0x0003)\n'
    assert snap.parse_ldd(output, 0) == ['/usr/lib/libx.so', '/lib/ld-linux.so']
    for text, status in [('libx => not found', 0), (output, 1), ('', 0), ('not a dynamic executable', 0), ('garbage', 0)]:
        with pytest.raises(ValueError):
            snap.parse_ldd(text, status)


def test_symlink_alias_chain_and_target_drift(tmp_path):
    p = tmp_path / 'a'
    q = tmp_path / 'b'
    alias = tmp_path / 'link'
    p.write_bytes(b'same')
    q.write_bytes(b'same')
    try:
        alias.symlink_to(p.name)
    except OSError as exc:
        pytest.skip('platform symlink permission: ' + str(exc))
    before = snap.snapshot({'library': [alias]})
    assert before['files'][0]['links'][0]['target'] == 'a'
    alias.unlink()
    alias.symlink_to(q.name)
    with pytest.raises(ValueError, match='drift'):
        snap.verify_unchanged(before, snap.snapshot({'library': [alias]}))


def test_parent_symlink_is_recorded(tmp_path):
    directory = tmp_path / 'actual'
    directory.mkdir()
    (directory / 'file').write_bytes(b'x')
    alias = tmp_path / 'alias'
    try:
        alias.symlink_to(directory, target_is_directory=True)
    except OSError as exc:
        pytest.skip('platform symlink permission: ' + str(exc))
    result = snap.snapshot({'binding': [alias / 'file']})
    assert result['files'][0]['links'][0]['path'] == str(alias)
