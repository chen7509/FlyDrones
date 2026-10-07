import hashlib
import json
from types import SimpleNamespace

import pytest

from tools.benchmark import capture_contract as contract
from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy


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


def test_worker_options_propagates_startup_preflight(tmp_path):
    selected = args(tmp_path)
    selected.startup_preflight = True
    options = contract.worker_options(selected)
    assert options.count('--startup-preflight') == 1


def test_startup_preflight_requires_complete_declared_inputs(tmp_path):
    with pytest.raises(SystemExit):
        args(tmp_path, '--startup-preflight')


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


def test_execution_v3_binds_exact_prospective_gauge_policy(tmp_path):
    policy_path = tmp_path / 'trajectory-gauge-policy.json'
    policy_path.write_text(json.dumps(trajectory_gauge_policy(), sort_keys=True) + '\n')
    selected = args(tmp_path, '--trajectory-gauge-policy', str(policy_path),
                    '--runtime-binding', str(tmp_path / 'binding.json'),
                    '--execution-contract', str(tmp_path / 'execution.json'))
    environment = {'HOME': '/home/test', 'SDF_PATH': ''}
    declaration = contract.execution_contract(selected, environment)
    assert declaration['schema'] == 'capture-execution-v3'
    assert declaration['trajectory_gauge_policy'] == {
        'path': str(policy_path.absolute()),
        'resolved': str(policy_path.resolve()),
        'bytes': len(policy_path.read_bytes()),
        'sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        'schema': 'trajectory-gauge-policy-v1',
    }
    contract_path = tmp_path / 'execution-v3.json'
    contract_path.write_text(json.dumps(declaration))
    selected.execution_contract = contract_path
    assert contract.validate_declaration(selected, environment) == declaration
    assert contract.worker_options(selected)[-2:] == [
        '--trajectory-gauge-policy', str(policy_path.resolve())]


@pytest.mark.parametrize('mutation', ['semantic', 'duplicate', 'changed_during_read'])
def test_execution_v3_refuses_invalid_or_changed_policy(tmp_path, monkeypatch, mutation):
    policy = trajectory_gauge_policy()
    policy_path = tmp_path / 'trajectory-gauge-policy.json'
    if mutation == 'semantic':
        policy['screens']['max_position_error_m'] = 0.5
        policy_path.write_text(json.dumps(policy))
    elif mutation == 'duplicate':
        policy_path.write_text('{"schema":"trajectory-gauge-policy-v1","schema":"changed"}')
    else:
        policy_path.write_text(json.dumps(policy))
        original = contract._file_identity
        calls = {'count': 0}

        def changed(path):
            row = original(path)
            calls['count'] += 1
            if calls['count'] == 2:
                row = dict(row, sha256='0' * 64)
            return row

        monkeypatch.setattr(contract, '_file_identity', changed)
    selected = args(tmp_path, '--trajectory-gauge-policy', str(policy_path),
                    '--runtime-binding', str(tmp_path / 'binding.json'),
                    '--execution-contract', str(tmp_path / 'execution.json'))
    with pytest.raises(ValueError):
        contract.execution_contract(selected, {'HOME': '/home/test'})


def test_worker_records_v3_policy_identity(tmp_path):
    environment = {'HOME': '/home/test'}
    policy_path = tmp_path / 'trajectory-gauge-policy.json'
    policy_path.write_text(json.dumps(trajectory_gauge_policy()))
    output = tmp_path / 'capture'
    binding_path = tmp_path / 'binding.json'
    contract_path = tmp_path / 'execution-v3.json'
    argv = ['--worker', '--output', str(output), '--trajectory-gauge-policy', str(policy_path),
            '--runtime-binding', str(binding_path), '--execution-contract', str(contract_path)]
    parsed = capture.parse_capture_args(argv)
    declaration = contract.execution_contract(parsed, environment)
    contract_path.write_text(json.dumps(declaration))
    output.mkdir()
    capture.record_worker_trajectory_policy(output, declaration, policy_path)
    record = json.loads((output / 'trajectory-gauge-policy-worker.json').read_text())
    assert record['matches_declaration'] is True
    assert record['sha256'] == hashlib.sha256(policy_path.read_bytes()).hexdigest()


def test_initial_environment_parser_preserves_empty_and_absent():
    assert capture.parse_initial_environment(b'HOME=/home/test\0SDF_PATH=\0') == {
        'HOME': '/home/test', 'SDF_PATH': '',
    }


@pytest.mark.parametrize('raw', [
    b'', b'HOME=/home/test', b'=value\0', b'NO_EQUALS\0', b'A=1\0A=2\0', b'BAD=\xff\0',
])
def test_initial_environment_parser_refuses_malformed_or_duplicate(raw):
    with pytest.raises(ValueError, match='environment'):
        capture.parse_initial_environment(raw)


def test_worker_records_exact_environment_before_other_work(tmp_path):
    environment = {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''}
    declaration = {'schema': 'capture-execution-v2', 'launch_environment': environment}
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text(json.dumps(declaration))
    output = tmp_path / 'capture'
    record = capture.record_worker_environment(
        output, declaration, contract_path,
        reader=lambda: b'HOME=/home/test\0SDF_PATH=\0',
    )
    assert record['matches'] is True
    assert record['observed'] == {'HOME': '/home/test', 'SDF_PATH': ''}
    assert (output / 'execution-environment-worker.json').is_file()


def test_worker_environment_mismatch_is_recorded_then_refused(tmp_path):
    environment = {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''}
    declaration = {'schema': 'capture-execution-v2', 'launch_environment': environment}
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text(json.dumps(declaration))
    output = tmp_path / 'capture'
    with pytest.raises(ValueError, match='environment mismatch'):
        capture.record_worker_environment(
            output, declaration, contract_path,
            reader=lambda: b'HOME=/home/test\0PYTHONPATH=hostile\0SDF_PATH=\0',
        )
    record = json.loads((output / 'execution-environment-worker.json').read_text())
    assert record['matches'] is False
    assert record['runtime_environment_qualified'] is False


def test_worker_environment_evidence_write_failure_refuses(tmp_path, monkeypatch):
    environment = {'HOME': '/home/test'}
    declaration = {'schema': 'capture-execution-v2', 'launch_environment': environment}
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text(json.dumps(declaration))
    monkeypatch.setattr(capture, 'write_manifest',
                        lambda *_args: (_ for _ in ()).throw(OSError('injected close failure')))
    with pytest.raises(OSError, match='close failure'):
        capture.record_worker_environment(
            tmp_path / 'capture', declaration, contract_path, reader=lambda: b'HOME=/home/test\0',
        )


def test_parent_derives_v2_environment_and_passes_it_to_supervisor(tmp_path, monkeypatch):
    environment = {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''}
    graph_environment = {'HOME': '/home/test', 'PATH': '/usr/bin', 'LANG': 'C.UTF-8'}
    binding = {
        'schema': 'capture-resource-binding-v3', 'environment': environment,
        'graph': {'environment': graph_environment},
    }
    binding_path = tmp_path / 'binding.json'
    binding_path.write_text(json.dumps(binding))
    output = tmp_path / 'capture'
    declaration_path = tmp_path / 'execution.json'
    argv = ['--output', str(output), '--runtime-binding', str(binding_path),
            '--execution-contract', str(declaration_path)]
    parsed = capture.parse_capture_args(argv)
    launch_environment = contract.derive_launch_environment(binding)
    declaration_path.write_text(json.dumps(contract.execution_contract(parsed, launch_environment)))
    monkeypatch.setattr('tools.benchmark.runtime_resource_binding.validate_binding', lambda doc: doc)
    monkeypatch.setattr('sys.argv', ['capture', *argv])
    calls = []

    def supervise(command, selected_output, **kwargs):
        calls.append((command, selected_output, kwargs))
        return dict(status='worker_exited', worker_exit=0, capture_status='capture_completed',
                    cleanup={'graceful_group_cleanup_verified': True}, errors=[])

    monkeypatch.setattr(capture, 'supervise_worker', supervise)
    assert capture.main() == 0
    assert calls[0][2]['launch_environment'] == launch_environment
    assert calls[0][2]['execution_contract'] == declaration_path
    assert calls[0][2]['timeout_s'] == 300


def test_motion_intent_profile_is_declared_and_forwarded_only_when_enabled(tmp_path):
    legacy = args(tmp_path)
    enabled = args(
        tmp_path,
        '--motion-intent-profile', 'native-beginning-zupt-v1',
        '--source-fanout-profile', 'ready-shadow-heartbeat-estimator-v1',
        '--shadow-binary', str(tmp_path / 'native'),
        '--shadow-config', str(tmp_path / 'config'),
        '--reference-module', str(tmp_path / 'reference'),
        '--reference-sha256', 'a' * 64,
        '--motion-profile', 'supported-ready-v1',
        '--physics-trace-profile', 'substep-ready-v1',
    )

    assert 'motion_intent_profile' not in contract.execution_contract(legacy)['profiles']
    assert contract.execution_contract(enabled)['profiles']['motion_intent_profile'] == 'native-beginning-zupt-v1'
    options = contract.worker_options(enabled)
    index = options.index('--motion-intent-profile')
    assert options[index + 1] == 'native-beginning-zupt-v1'


def test_native_motion_intent_bridge_requires_unarmed_proof_and_applies_before_anchor():
    from tools.benchmark.capture_disarmed_sensors import apply_native_motion_intent

    now = iter(range(1_000, 1_020))

    class Readiness:
        def motion_intent_state(self):
            return {"state": "internal"}

    class Gate:
        session_id = "session"
        clock_id = "clock"
        failure = None

        def __init__(self):
            self.calls = []

        def observe_estimator(self, value):
            self.calls.append(("state", value))

        def request(self, command):
            self.calls.append(("request", command))
            return {"action": command["effective_sim_ns"]}

        def acknowledge(self, ack):
            self.calls.append(("ack", ack))

        def authorize_step(self, ns):
            self.calls.append(("authorize", ns))
            return True

    class Client:
        def send_motion_intent(self, action):
            return {"native": action}

    gate = Gate()
    proof = {"records": {"heartbeat": {"base_mode": 0}}}
    apply_native_motion_intent(gate, Readiness(), Client(), 2_600_000_000, proof, clock=lambda: next(now))

    assert [call[0] for call in gate.calls] == ["state", "request", "ack", "authorize"]
    assert gate.calls[1][1]["effective_sim_ns"] == 2_600_000_000
    assert gate.calls[1][1]["velocity_setpoint_frd_m_s"] == [0.0, 0.0, -0.2]
    with pytest.raises(ValueError, match="unarmed"):
        apply_native_motion_intent(gate, Readiness(), Client(), 3_000_000_000,
                                   {"records": {"heartbeat": {"base_mode": 128}}},
                                   clock=lambda: next(now))
