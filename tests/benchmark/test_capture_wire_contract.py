import hashlib
import json

import pytest

from tools.benchmark import capture_contract as contract
from tools.benchmark import capture_disarmed_sensors as capture


def configuration():
    return dict(schema='capture-wire-v1', session_id='declared-study-wire',
                sim_origin_ns=0, remote_origin_ns=1_000_000)


def selected(tmp_path):
    path = tmp_path / 'wire.json'
    path.write_text(json.dumps(configuration()))
    return capture.parse_capture_args([
        '--output', str(tmp_path / 'capture'), '--wire-config', str(path),
        '--execution-contract', str(tmp_path / 'execution.json'),
        '--runtime-binding', str(tmp_path / 'binding.json'),
        '--shadow-binary', str(tmp_path / 'probe'), '--shadow-config', str(tmp_path / 'config'),
        '--reference-module', str(tmp_path / 'reference.so'), '--reference-sha256', 'a' * 64,
        '--source-fanout-profile', 'ready-shadow-heartbeat-estimator-v1',
        '--motion-profile', 'supported-ready-v1', '--physics-trace-profile', 'substep-ready-v1',
    ])


def test_wire_configuration_is_declared_and_forwarded_without_changing_limits(tmp_path):
    assert hasattr(contract, 'wire_configuration_record'), 'wire declaration missing'
    args = selected(tmp_path)
    declaration = contract.execution_contract(args)
    wire = declaration['wire']
    assert wire['configuration'] == configuration()
    assert wire['sha256'] == hashlib.sha256(args.wire_config.read_bytes()).hexdigest()
    assert declaration['wall_budget_s'] == declaration['supervisor_s'] == 300
    assert declaration['physics_step_ns'] == 1_000_000
    options = contract.worker_options(args)
    index = options.index('--wire-config')
    assert options[index + 1] == str(args.wire_config.resolve())
    args.execution_contract.write_text(json.dumps(declaration))
    assert contract.validate_declaration(args) == declaration
    changed = configuration()
    changed['remote_origin_ns'] += 1
    args.wire_config.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='declaration'):
        contract.validate_declaration(args)


@pytest.mark.parametrize('field,value', [
    ('schema', 'other'), ('session_id', ''), ('session_id', '../escape'),
    ('sim_origin_ns', 1), ('sim_origin_ns', False), ('remote_origin_ns', True),
    ('remote_origin_ns', -1), ('remote_origin_ns', 2**63), ('extra', 1),
])
def test_invalid_wire_configuration_refused(tmp_path, field, value):
    assert hasattr(contract, 'wire_configuration_record'), 'wire declaration missing'
    path = tmp_path / 'bad.json'
    data = configuration()
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        contract.wire_configuration_record(path)


def test_wire_cannot_select_an_undeclared_legacy_launch(tmp_path):
    assert hasattr(contract, 'wire_configuration_record'), 'wire declaration missing'
    with pytest.raises(SystemExit):
        capture.parse_capture_args(['--output', str(tmp_path), '--wire-config', str(tmp_path / 'wire.json')])
    old = capture.parse_capture_args(['--output', str(tmp_path)])
    assert 'wire' not in contract.execution_contract(old)
    assert '--wire-config' not in contract.worker_options(old)


def test_actual_capture_selector_calls_only_the_selected_factory(tmp_path):
    from types import SimpleNamespace
    assert hasattr(capture, 'prepare_capture_receiver'), 'actual receiver selector missing'
    calls, cleanups = [], []
    legacy = SimpleNamespace(close=lambda: calls.append('legacy close'))
    journal = SimpleNamespace(cleanup=lambda *a, **k: cleanups.append((a, k)))
    result = {'errors': []}
    common = dict(journal=journal, result=result, output=tmp_path, start_ns=10,
                  source_guard=lambda: None, heartbeat_sink=lambda _: None)
    first = capture.prepare_capture_receiver(
        {'wall_budget_s': 300}, **common,
        legacy_factory=lambda: calls.append('legacy') or legacy,
        wire_factory=lambda *a, **k: pytest.fail('unselected wire factory invoked'))
    assert first == (legacy, None)
    assert calls == ['legacy']
    token = object()
    def wire(*args, **kwargs):
        calls.append(('wire', args, kwargs))
        return token
    config_path = tmp_path / 'selected-wire.json'
    config_path.write_text(json.dumps(configuration()))
    second = capture.prepare_capture_receiver(
        {'wall_budget_s': 300, 'wire': contract.wire_configuration_record(config_path)}, **common,
        legacy_factory=lambda: pytest.fail('legacy receiver must not coexist'), wire_factory=wire)
    assert second == (None, token)
    assert calls[-1][0] == 'wire'
    assert calls[-1][2]['total_deadline_ns'] == 300_000_000_010


def test_config_drift_after_declaration_is_refused_before_receiver_creation(tmp_path):
    from types import SimpleNamespace
    args = selected(tmp_path)
    declared = contract.execution_contract(args)
    changed = configuration()
    changed['remote_origin_ns'] += 1
    args.wire_config.write_text(json.dumps(changed))
    created = []
    with pytest.raises(ValueError, match='wire.*changed'):
        capture.prepare_capture_receiver(
            declared, journal=SimpleNamespace(), result={'errors': []}, output=tmp_path,
            start_ns=10, source_guard=lambda: None, heartbeat_sink=lambda _: None,
            legacy_factory=lambda: created.append('legacy'), wire_factory=lambda *a, **k: created.append('wire'))
    assert created == []
