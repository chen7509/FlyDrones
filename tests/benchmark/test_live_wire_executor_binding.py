"""Offline binding to the existing one-shot runner; no subprocess is run."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmark.live_wire_study_fixture import fixture, write
from tools.benchmark import execute_openvins_health_physical_run as executor
from tools.benchmark.audit_live_wire_study import _dispatch_records
from tools.benchmark.declared_runtime_snapshot import file_record


def prepared(tmp_path):
    manifest, _, path = fixture(tmp_path)
    return manifest, path, executor.prepare_live_wire_execution(path)


def test_prepare_is_read_only_and_binds_actual_existing_executor(tmp_path, monkeypatch):
    manifest, _, path = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('offline preparation attempted process/network I/O')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    monkeypatch.setattr('socket.socket', forbidden)
    plan = executor.prepare_live_wire_execution(path)
    assert plan['executor'] == file_record(executor.__file__)
    assert plan['study_manifest'] == file_record(path)
    assert plan['command'] == manifest['command']
    assert plan['live_activation_available'] is False
    assert plan['fusion_eligible'] is False
    assert all(not Path(p).exists() for p in plan['outputs'].values())
    assert not (tmp_path / 'executor-binding.json').exists()


def test_shared_runner_emits_future_wire_envelopes_with_fake_runner_only(tmp_path):
    manifest, path, plan = prepared(tmp_path)
    calls = []
    def fake(command, **kwargs):
        calls.append(command)
        Path(plan['destination']).mkdir()
        return SimpleNamespace(returncode=0)
    assert executor._execute_once(plan, resources_fn=lambda: [], runner=fake) == 0
    assert calls == [manifest['command']]
    dispatch = json.loads(Path(plan['outputs']['dispatch']).read_text())
    completion = json.loads(Path(plan['outputs']['completion']).read_text())
    checked = _dispatch_records(manifest, file_record(path), dispatch, completion)
    assert checked['records_consistent']
    assert checked['executor_identity_attested'] is False
    assert dispatch['executor'] == plan['executor']
    with pytest.raises(ValueError, match='output already exists'):
        executor._execute_once(plan, resources_fn=lambda: [], runner=fake)
    assert len(calls) == 1


@pytest.mark.parametrize('failure', ['returncode', 'exception'])
def test_shared_runner_keeps_failure_and_refuses_second_attempt(tmp_path, failure):
    _, _, plan = prepared(tmp_path)
    calls = []
    def fake(*args, **kwargs):
        calls.append(True)
        if failure == 'exception':
            raise RuntimeError('synthetic child failure')
        return SimpleNamespace(returncode=2)
    code = executor._execute_once(plan, resources_fn=lambda: [], runner=fake)
    assert code == (125 if failure == 'exception' else 2)
    completion = json.loads(Path(plan['outputs']['completion']).read_text())
    assert completion['launcher_returncode'] == code
    assert completion['destination_exists'] is False
    assert bool(completion['launcher_error']) == (failure == 'exception')
    with pytest.raises(ValueError, match='output already exists'):
        executor._execute_once(plan, resources_fn=lambda: [], runner=fake)
    assert len(calls) == 1


@pytest.mark.parametrize('name', ['output', 'dispatch', 'completion'])
def test_existing_evidence_refuses_before_dispatch(tmp_path, name):
    _, _, plan = prepared(tmp_path)
    target = Path(plan['outputs'][name])
    target.write_bytes(b'older evidence')
    with pytest.raises(ValueError, match='output already exists'):
        executor._execute_once(plan, resources_fn=lambda: [], runner=lambda *a, **k: pytest.fail('run'))
    assert target.read_bytes() == b'older evidence'


def test_changed_manifest_refuses_before_runner(tmp_path):
    _, path, plan = prepared(tmp_path)
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='identity'):
        executor._execute_once(plan, resources_fn=lambda: [], runner=lambda *a, **k: pytest.fail('run'))
    assert not Path(plan['outputs']['dispatch']).exists()


def test_competing_resources_refuse_without_dispatch(tmp_path):
    _, _, plan = prepared(tmp_path)
    with pytest.raises(ValueError, match='competing resources'):
        executor._execute_once(plan, resources_fn=lambda: ['existing simulation'], runner=lambda *a, **k: None)
    assert not Path(plan['outputs']['dispatch']).exists()


def test_public_executor_cannot_activate_prepared_live_study(tmp_path):
    manifest, _, path = fixture(tmp_path)
    # The existing public entry remains health-only. Binding is not activation.
    write(tmp_path / 'study-manifest.json', manifest)
    with pytest.raises(ValueError, match='invalid physical run preflight'):
        executor.execute(tmp_path, resources_fn=lambda: [], runner=lambda *a, **k: pytest.fail('run'))
    assert not Path(manifest['outputs']['dispatch']).exists()
    assert path.exists()


def test_existing_supplemental_stdout_path_refuses(tmp_path):
    manifest, _, path = fixture(tmp_path)
    original = Path(manifest['files']['capture']['requested'])
    # The supplemental stdout path is outside the four original manifest outputs.
    (tmp_path / 'physical-output.txt').mkdir()
    with pytest.raises(ValueError, match='output already exists'):
        executor.prepare_live_wire_execution(path)
    assert original.exists()


def test_health_runner_also_refuses_old_stdout_before_dispatch(tmp_path):
    from tests.benchmark.test_execute_openvins_health_physical_run import study
    root = study(tmp_path)
    (root / 'physical-output.txt').write_bytes(b'old evidence')
    with pytest.raises(ValueError, match='output already exists'):
        executor.execute(root, resources_fn=lambda: [], runner=lambda *a, **k: pytest.fail('run'))
    assert not (root / 'physical-dispatch.json').exists()


@pytest.mark.parametrize('field', ['command', 'executor', 'dispatch_schema'])
def test_changed_bound_plan_refuses(tmp_path, field):
    _, _, plan = prepared(tmp_path)
    if field == 'executor':
        plan[field]['sha256'] = '0' * 64
    elif field == 'command':
        plan[field] = ['unauthorized-program']
    else:
        plan[field] = 'wrong-schema'
    with pytest.raises(ValueError, match='identity|differs'):
        executor._execute_once(plan, resources_fn=lambda: [], runner=lambda *a, **k: pytest.fail('run'))
    assert not Path(plan['outputs']['dispatch']).exists()


def test_success_with_remaining_resources_is_failure(tmp_path):
    _, _, plan = prepared(tmp_path)
    scans = iter([[], ['synthetic remaining child']])
    assert executor._execute_once(plan, resources_fn=lambda: next(scans),
                                  runner=lambda *a, **k: SimpleNamespace(returncode=0)) == 2
    completion = json.loads(Path(plan['outputs']['completion']).read_text())
    assert completion['command_returncode'] == 0
    assert completion['launcher_returncode'] == 2
    assert completion['resources_after'] == ['synthetic remaining child']


def test_collision_between_extra_stdout_and_capture_refuses(tmp_path):
    manifest, docs, path = fixture(tmp_path)
    from tools.benchmark.live_wire_study import _expected_command
    manifest['outputs']['capture'] = str(tmp_path / 'physical-output.txt' / 'capture')
    manifest['command'] = _expected_command(manifest, docs['execution'])
    write(path, manifest)
    with pytest.raises(ValueError, match='output paths overlap'):
        executor.prepare_live_wire_execution(path)
