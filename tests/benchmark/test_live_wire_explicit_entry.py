"""Public wire entry contracts, with synthetic files and fake runners only."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmark.live_wire_study_fixture import fixture, write
from tools.benchmark import execute_openvins_health_physical_run as executor
from tools.benchmark.declared_runtime_snapshot import file_record


def entry():
    assert hasattr(executor, 'execute_live_wire'), 'explicit wire entry is missing'
    return executor.execute_live_wire


def forbidden(*args, **kwargs):
    pytest.fail('real or unexpected runner invocation')


@pytest.fixture(autouse=True)
def no_process_or_network(monkeypatch):
    monkeypatch.setattr('subprocess.Popen', forbidden)
    monkeypatch.setattr('socket.socket', forbidden)


def invoke(path, **kwargs):
    options = dict(approved_manifest_sha256=file_record(path)['sha256'],
                   resources_fn=lambda: [], runner=forbidden)
    options.update(kwargs)
    return entry()(path, **options)


def test_selected_manifest_dispatches_original_command_once(tmp_path):
    manifest, _, path = fixture(tmp_path)
    calls = []
    before = path.read_bytes()

    def fake(command, **kwargs):
        receipt = json.loads((tmp_path / 'activation-request.json').read_text())
        assert receipt['request_is_not_dispatch'] is True
        assert receipt['fusion_eligible'] is False
        assert receipt['approved_manifest_sha256'] == file_record(path)['sha256']
        assert receipt['study_manifest'] == file_record(path)
        assert receipt['executor'] == file_record(executor.__file__)
        assert type(receipt['requested_wall_ns']) is int
        assert 'user_authorized' not in receipt
        calls.append(command)
        Path(manifest['outputs']['capture']).mkdir()
        return SimpleNamespace(returncode=0)

    assert invoke(path, runner=fake) == 0
    assert calls == [manifest['command']]
    assert path.read_bytes() == before
    completion = json.loads(Path(manifest['outputs']['completion']).read_text())
    assert completion['launcher_returncode'] == 0
    with pytest.raises(ValueError, match='already exists'):
        invoke(path, runner=fake)
    assert len(calls) == 1


@pytest.mark.parametrize('digest', [None, True, 7, '', 'A' * 64, 'a' * 63, 'z' * 64, '0' * 64])
def test_invalid_digest_cannot_write_intent_or_dispatch(tmp_path, digest):
    manifest, _, path = fixture(tmp_path)
    with pytest.raises(ValueError, match='digest'):
        invoke(path, approved_manifest_sha256=digest)
    assert not (tmp_path / 'activation-request.json').exists()
    assert not Path(manifest['outputs']['dispatch']).exists()


def test_missing_digest_is_required(tmp_path):
    _, _, path = fixture(tmp_path)
    with pytest.raises(TypeError, match='approved_manifest_sha256'):
        entry()(path, resources_fn=lambda: [], runner=forbidden)
    assert not (tmp_path / 'activation-request.json').exists()


@pytest.mark.parametrize('mutation', ['manifest', 'input'])
def test_preexisting_mutation_refuses_before_intent(tmp_path, mutation):
    manifest, _, path = fixture(tmp_path)
    digest = file_record(path)['sha256']
    if mutation == 'manifest':
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        Path(manifest['files']['capture']['requested']).write_text('changed')
    with pytest.raises(ValueError):
        invoke(path, approved_manifest_sha256=digest)
    assert not (tmp_path / 'activation-request.json').exists()
    assert not Path(manifest['outputs']['dispatch']).exists()


def test_resources_before_intent_refuse(tmp_path):
    manifest, _, path = fixture(tmp_path)
    with pytest.raises(ValueError, match='competing resources'):
        invoke(path, resources_fn=lambda: ['other simulator'])
    assert not (tmp_path / 'activation-request.json').exists()
    assert not Path(manifest['outputs']['dispatch']).exists()


def test_second_resource_gate_retains_intent_without_dispatch(tmp_path):
    manifest, _, path = fixture(tmp_path)
    scans = iter([[], ['new competing simulator']])
    with pytest.raises(ValueError, match='competing resources'):
        invoke(path, resources_fn=lambda: next(scans))
    receipt = tmp_path / 'activation-request.json'
    original = receipt.read_bytes()
    assert not Path(manifest['outputs']['dispatch']).exists()
    assert not Path(manifest['outputs']['completion']).exists()
    with pytest.raises(ValueError, match='already exists'):
        invoke(path)
    assert receipt.read_bytes() == original


def test_changed_source_at_resource_gate_is_revalidated(tmp_path):
    manifest, _, path = fixture(tmp_path)

    def mutate():
        Path(manifest['files']['capture']['requested']).write_text('changed after validation')
        return []

    with pytest.raises(ValueError):
        invoke(path, resources_fn=mutate)
    assert (tmp_path / 'activation-request.json').exists()
    assert not Path(manifest['outputs']['dispatch']).exists()


@pytest.mark.parametrize('output', ['activation-request.json', 'activation-request.json/capture'])
def test_request_output_overlap_refuses(tmp_path, output):
    from tools.benchmark.live_wire_study import _expected_command

    manifest, docs, path = fixture(tmp_path)
    manifest['outputs']['capture'] = str(tmp_path / output)
    manifest['command'] = _expected_command(manifest, docs['execution'])
    write(path, manifest)
    with pytest.raises(ValueError, match='overlap'):
        invoke(path)
    assert not (tmp_path / 'activation-request.json').exists()


def test_existing_request_input_alias_is_preserved(tmp_path):
    manifest, _, path = fixture(tmp_path)
    receipt = tmp_path / 'activation-request.json'
    receipt.hardlink_to(path)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        invoke(path)
    assert path.read_bytes() == receipt.read_bytes() == original
    assert not Path(manifest['outputs']['dispatch']).exists()


@pytest.mark.parametrize('failure', ['returncode', 'exception'])
def test_failed_runner_retains_existing_completion_semantics(tmp_path, failure):
    manifest, _, path = fixture(tmp_path)
    calls = []

    def fake(*args, **kwargs):
        calls.append(True)
        if failure == 'exception':
            raise RuntimeError('synthetic launch failure')
        return SimpleNamespace(returncode=2)

    expected = 125 if failure == 'exception' else 2
    assert invoke(path, runner=fake) == expected
    completion = json.loads(Path(manifest['outputs']['completion']).read_text())
    assert completion['launcher_returncode'] == expected
    assert bool(completion['launcher_error']) == (failure == 'exception')
    assert (tmp_path / 'activation-request.json').exists()
    with pytest.raises(ValueError, match='already exists'):
        invoke(path, runner=fake)
    assert calls == [True]


def test_request_write_failure_cannot_dispatch(tmp_path, monkeypatch):
    manifest, _, path = fixture(tmp_path)
    original = executor._write_x

    def fail_request(target, value):
        if Path(target).name == 'activation-request.json':
            Path(target).write_text('{partial')
            raise OSError('synthetic close failure')
        return original(target, value)

    monkeypatch.setattr(executor, '_write_x', fail_request)
    with pytest.raises(OSError, match='close failure'):
        invoke(path)
    assert (tmp_path / 'activation-request.json').read_text() == '{partial'
    assert not Path(manifest['outputs']['dispatch']).exists()


@pytest.mark.parametrize('args', [
    [], ['--live-wire-study', 'x'],
    ['--study', 'x', '--live-wire-study', 'y'],
    ['--study', 'x', '--approved-manifest-sha256', '0' * 64],
    ['--live-wire-study', 'x', '--approved-manifest-sha256', '0' * 64, '--development-gate', 'y'],
])
def test_cli_rejects_missing_or_crossed_routes(monkeypatch, args):
    entry()
    monkeypatch.setattr(executor, 'execute', forbidden)
    monkeypatch.setattr(executor, 'execute_live_wire', forbidden)
    with pytest.raises(SystemExit) as caught:
        executor.main(args)
    assert caught.value.code == 2


def test_cli_wire_and_health_route_explicitly(monkeypatch):
    entry()
    calls = []
    monkeypatch.setattr(executor, 'execute_live_wire', lambda *a, **k: calls.append(('wire', a, k)) or 17)
    monkeypatch.setattr(executor, 'execute', lambda *a, **k: calls.append(('health', a, k)) or 19)
    assert executor.main(['--live-wire-study', 'x', '--approved-manifest-sha256', 'a' * 64]) == 17
    assert calls[-1][0:2] == ('wire', (Path('x'),))
    assert calls[-1][2]['approved_manifest_sha256'] == 'a' * 64
    assert executor.main(['--study', 'y', '--development-gate', 'gate']) == 19
    assert calls[-1][0:2] == ('health', (Path('y'),))
    assert calls[-1][2]['development_gate'] == Path('gate')
