import json
from types import SimpleNamespace

import pytest

from tools.benchmark import capture_contract as contract
from tools.benchmark import capture_disarmed_sensors as capture


def args(tmp_path, *extra):
    return capture.parse_capture_args(['--output', str(tmp_path / 'capture'), *extra])


def test_declared_ordinary_limits_and_workload(tmp_path):
    selected = contract.execution_contract(args(tmp_path))
    assert selected['wall_budget_s'] == 300
    assert selected['supervisor_s'] == 300
    assert selected['simulation_duration_ns'] == 25_000_000_000
    assert selected['physics_step_ns'] == 1_000_000
    assert selected['imu_hz'] == 250
    assert selected['rgbd_hz'] == 10
    assert selected['rgbd_size'] == [160, 120]


@pytest.mark.parametrize('field,value', [
    ('wall_budget_s', 60), ('supervisor_s', 90), ('imu_hz', 249),
    ('physics_step_ns', 1000000.0), ('estimator_run', 0), ('extra', 'ignored'),
])
def test_tampered_declaration_refuses_before_supervisor(tmp_path, monkeypatch, field, value):
    declaration = contract.execution_contract(args(tmp_path))
    declaration[field] = value
    path = tmp_path / 'declaration.json'
    path.write_text(json.dumps(declaration))
    monkeypatch.setattr('sys.argv', ['capture', '--output', str(tmp_path / 'capture'), '--execution-contract', str(path)])
    calls = []
    monkeypatch.setattr(capture, 'supervise_worker', lambda *a, **k: calls.append((a, k)))
    with pytest.raises((ValueError, SystemExit)):
        capture.main()
    assert calls == []


def test_duplicate_json_keys_refused(tmp_path):
    path = tmp_path / 'duplicate.json'
    path.write_text('{"wall_budget_s":60,"wall_budget_s":300}')
    with pytest.raises(ValueError, match='duplicate'):
        contract.read_declaration(path)


@pytest.mark.parametrize('fault,expected', [(False, 300), (True, 90)])
def test_supervisor_consumes_contract_and_forwards_declaration(tmp_path, monkeypatch, fault, expected):
    extra = []
    if fault:
        extra = ['--reference-fault-profile', 'native-pre-epoch-v1', '--reference-module', 'probe.so',
                 '--reference-sha256', 'a' * 64, '--motion-profile', 'supported-ready-v1',
                 '--physics-trace-profile', 'substep-ready-v1']
    selected = args(tmp_path, *extra)
    path = tmp_path / 'selected.json'
    path.write_text(json.dumps(contract.execution_contract(selected)))
    monkeypatch.setattr('sys.argv', ['capture', '--output', str(tmp_path / 'capture'), *extra,
                                   '--execution-contract', str(path)])
    calls = []
    def supervise(command, output, **kwargs):
        calls.append((command, kwargs))
        return dict(status='worker_exited', worker_exit=0, capture_status='capture_completed',
                    cleanup={'graceful_group_cleanup_verified': True}, errors=[])
    monkeypatch.setattr(capture, 'supervise_worker', supervise)
    assert capture.main() == 0
    assert calls[0][1]['timeout_s'] == expected
    assert calls[0][0][-2:] == ['--execution-contract', str(path.resolve())]
    assert contract.execution_contract(selected)['wall_budget_s'] == (60 if fault else 300)


def test_declared_launcher_refuses_legacy_missing_contract(tmp_path):
    with pytest.raises(ValueError, match='declaration'):
        contract.declared_command(args(tmp_path), 'python', 'capture.py')


def test_unknown_fault_profile_is_not_normal_timeout():
    with pytest.raises(ValueError):
        contract.execution_contract(SimpleNamespace(reference_fault_profile='typo'))


def test_direct_worker_refuses_before_resource_inspection(tmp_path, monkeypatch):
    path = tmp_path / 'wrong.json'
    path.write_text('{}')
    monkeypatch.setattr('sys.argv', ['capture', '--worker', '--output', str(tmp_path / 'capture'),
                                   '--execution-contract', str(path)])
    calls = []
    monkeypatch.setattr(capture, 'active_resources', lambda: calls.append('inspected'))
    with pytest.raises(ValueError, match='declaration'):
        capture.main()
    assert calls == []


def test_launch_environment_union_preserves_absent_and_present_empty():
    binding = {
        'schema': 'capture-resource-binding-v3',
        'environment': {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''},
        'graph': {'environment': {'HOME': '/home/test', 'PATH': '/usr/bin', 'LANG': 'C.UTF-8',
                                  'GZ_FILE_PATH': ''}},
    }
    selected = contract.derive_launch_environment(binding)
    assert selected == {
        'GZ_FILE_PATH': '', 'HOME': '/home/test', 'LANG': 'C.UTF-8', 'PATH': '/usr/bin',
        'PYTHONPATH': None, 'SDF_PATH': '',
    }
    assert contract.materialize_launch_environment(selected) == {
        'GZ_FILE_PATH': '', 'HOME': '/home/test', 'LANG': 'C.UTF-8', 'PATH': '/usr/bin',
        'SDF_PATH': '',
    }


def test_launch_environment_refuses_overlap_conflict():
    binding = {
        'schema': 'capture-resource-binding-v3',
        'environment': {'HOME': '/declared'},
        'graph': {'environment': {'HOME': '/different'}},
    }
    with pytest.raises(ValueError, match='conflict'):
        contract.derive_launch_environment(binding)


@pytest.mark.parametrize('environment', [
    {'': 'value'}, {'BAD=NAME': 'value'}, {'BAD\0NAME': 'value'}, {'NAME': 'bad\0value'},
    {'NAME': 1}, {1: 'value'}, {1: 'value', 'A': 'other'}, {'A': 'x' * 65537},
])
def test_launch_environment_refuses_malformed_or_oversized(environment):
    with pytest.raises(ValueError, match='environment'):
        contract.validate_launch_environment(environment)


def test_execution_v2_binds_exact_launch_environment(tmp_path):
    selected = args(tmp_path)
    environment = {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''}
    declaration = contract.execution_contract(selected, environment)
    assert declaration['schema'] == 'capture-execution-v2'
    assert declaration['launch_environment'] == environment
    path = tmp_path / 'execution-v2.json'
    path.write_text(json.dumps(declaration))
    selected.execution_contract = path
    assert contract.validate_declaration(selected, environment) == declaration
    with pytest.raises(ValueError, match='declaration'):
        contract.validate_declaration(selected, dict(environment, PYTHONPATH='hostile'))
