"""Worker main orchestration, real file contracts, injected OS/SDK boundaries.

No socket or native process is created. Tiny test binaries/scene use an explicit
pin adapter; these tests do not qualify the installed PX4/Gazebo resource graph.
"""
import builtins
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmark.test_bound_resource_graph import graph_fixture
from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark import runtime_resource_binding as binding
from tools.benchmark.capture_contract import execution_contract, materialize_launch_environment
from tools.benchmark.declared_runtime_snapshot import snapshot
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy


def setup_entry(tmp_path, monkeypatch, *, preflight=True, wire=True):
    doc, generated, _, _, _ = graph_fixture(tmp_path)
    root, home = tmp_path / 'repo', tmp_path / 'home'
    px4 = home / 'PX4-Autopilot'
    build = px4 / 'build/px4_sitl_default'
    required = [
        build / 'bin/px4', build / 'rootfs/gz_env.sh', build / 'etc/init.d-posix/rcS',
        px4 / 'src/modules/simulation/gz_bridge/server.config',
        root / 'assets/gazebo/models/x500_benchmark/model.sdf',
        root / 'assets/gazebo/models/OakD-Benchmark/model.sdf',
        px4 / 'Tools/simulation/gz/models/x500/model.sdf',
        px4 / 'Tools/simulation/gz/models/x500_base/model.sdf',
        tmp_path / 'online_probe', tmp_path / 'reference.so',
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('fixture:' + path.name).encode())
    config = tmp_path / 'estimator_config.yaml'
    config.write_text('relative_config_imu: kalibr_imu_chain.yaml\n'
                      'relative_config_imucam: kalibr_imucam_chain.yaml\n')
    calibrations = [tmp_path / 'kalibr_imu_chain.yaml', tmp_path / 'kalibr_imucam_chain.yaml']
    for path in calibrations:
        path.write_text('fixture: not loaded by an estimator\n')
    freeze = tmp_path / 'freeze.json'
    freeze.write_text(json.dumps({'sha256': {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [config, *calibrations]}}))
    required += [config, *calibrations, freeze]
    archive = root / 'evidence/openvins-board-pattern-dev-1701-reviewed.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as stream:
        for name, path in generated.items():
            if name != 'gz_env.sh':
                stream.writestr('results/openvins-board-pattern-dev-1701/episode-v2/' + name, path.read_bytes())
    doc['generated']['gz_env.sh'] = hashlib.sha256(required[1].read_bytes()).hexdigest()
    doc['schema'] = 'capture-resource-binding-v3'
    doc['runtime_maps'] = dict(self_phases=['postimports', 'postfinalize', 'postfirststep'],
                               owned_roles={'px4': ['ready', 'prestop'], 'openvins': ['ready', 'prestop']},
                               max_maps_bytes=1024, max_observations=8)
    doc['inventory']['actual-inputs'] = [str(p) for p in required]
    wire_path = tmp_path / 'wire.json'
    wire_path.write_text(json.dumps(dict(schema='capture-wire-v1', session_id='entry-test',
                                         sim_origin_ns=0, remote_origin_ns=0)))
    if wire:
        doc['inventory']['wire'] = [str(wire_path)]
    doc['baseline'] = snapshot(doc['inventory'])
    binding_path = tmp_path / 'binding.json'
    binding_path.write_text(json.dumps(doc))
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps(trajectory_gauge_policy()))
    declaration = tmp_path / 'execution.json'
    output = tmp_path / 'worker-output'
    argv = ['--worker', '--output', str(output), '--runtime-binding', str(binding_path),
            '--execution-contract', str(declaration), '--trajectory-gauge-policy', str(policy),
            '--shadow-binary', str(tmp_path / 'online_probe'), '--shadow-config', str(config),
            '--reference-module', str(tmp_path / 'reference.so'),
            '--reference-sha256', hashlib.sha256((tmp_path / 'reference.so').read_bytes()).hexdigest(),
            '--source-fanout-profile', 'ready-shadow-heartbeat-estimator-v1',
            '--motion-profile', 'supported-ready-v1', '--physics-trace-profile', 'substep-ready-v1']
    if preflight:
        argv += ['--startup-preflight']
    if wire:
        argv += ['--wire-config', str(wire_path)]
    environment = capture.derive_launch_environment(doc)
    declaration.write_text(json.dumps(execution_contract(capture.parse_capture_args(argv), environment)))
    monkeypatch.setattr(sys, 'argv', ['capture', *argv])
    monkeypatch.setattr(capture, 'ROOT', root)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(capture, 'active_resources', lambda: [])
    for key, value in materialize_launch_environment(environment).items():
        monkeypatch.setenv(key, value)
    for key, value in environment.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
    raw_environment = b''.join(k.encode() + b'=' + v.encode() + b'\0'
                               for k, v in materialize_launch_environment(environment).items())
    # A nonempty, exact synthetic process environment for the real recorder.
    if not raw_environment:
        environment['PATH'] = 'test-only'
        doc['graph']['environment']['PATH'] = 'test-only'
        monkeypatch.setenv('PATH', 'test-only')
        binding_path.write_text(json.dumps(doc))
        declaration.write_text(json.dumps(execution_contract(capture.parse_capture_args(argv), environment)))
        raw_environment = b'PATH=test-only\0'
    real_record = capture.record_worker_environment
    monkeypatch.setattr(capture, 'record_worker_environment',
                        lambda *a: real_record(*a, reader=lambda: raw_environment))
    runtime_parent = home / 'fly-ego-benchmark/runtime'
    runtime_parent.mkdir(parents=True)
    # Only capture's two installed pin checks are adapted, not binding/file hashes.
    pins = {required[0].read_bytes(): 'e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb',
            archive.read_bytes(): '669f3646e74c4e95826f12e79b456aba861a5b4003087541ce7dc1dc8cd1f4f3'}
    monkeypatch.setattr(capture, 'hashlib', SimpleNamespace(sha256=lambda data:
                        SimpleNamespace(hexdigest=lambda: pins[data]) if data in pins else hashlib.sha256(data)))
    original_binding = binding.RuntimeBinding
    monkeypatch.setattr(binding, 'RuntimeBinding',
                        lambda *a, **kw: original_binding(*a, map_reader=lambda: '', **kw))

    class SDK:
        def __init__(self, *_args):
            pass

        def query(self, *args):
            assert args == ('context',)
            return dict(doc['graph']['expected_context'])

        def check_budget(self):
            return 0.0

    monkeypatch.setattr(binding, 'QueryClient', SDK)
    original_import = builtins.__import__
    forbidden_calls = []

    def guarded_import(name, *args, **kwargs):
        if name == 'gz' or name.startswith('gz.') or name.startswith('pymavlink'):
            forbidden_calls.append('import:' + name)
            raise AssertionError('runtime native import escaped preflight: ' + name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)

    def forbidden(*_args, **_kwargs):
        forbidden_calls.append('factory')
        raise AssertionError('network/process factory escaped offline entry')

    monkeypatch.setattr(capture.socket, 'socket', forbidden)
    monkeypatch.setattr(capture.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(capture, 'run_capture_runtime', forbidden)
    return SimpleNamespace(output=output, wire=wire_path, declaration=declaration,
                           generated=generated, required=required, argv=argv, forbidden_calls=forbidden_calls)


@pytest.mark.parametrize('wire', [False, True])
def test_preflight_main_has_no_network_or_runtime_side_effects(tmp_path, monkeypatch, wire):
    case = setup_entry(tmp_path, monkeypatch, wire=wire)
    assert capture.main() == 0
    result = json.loads((case.output / 'result.json').read_text())
    assert result['status'] == 'capture_completed'
    assert result['runtime_binding']['phases'] == ['postgraph', 'bootstrap']
    assert result['runtime_binding']['owned_phases'] == {'px4': [], 'openvins': []}
    assert result['runtime_binding']['runtime_mapping_coverage_verified'] is False
    assert result['eligible_for_px4_fusion'] is False
    assert case.forbidden_calls == []


def test_preflight_main_does_not_report_planned_estimator_as_executed(tmp_path, monkeypatch):
    case = setup_entry(tmp_path, monkeypatch)

    class PortProbe:
        def __enter__(self):
            return self

        def bind(self, endpoint):
            assert endpoint == ('127.0.0.1', 14548)

        def __exit__(self, *_args):
            pass

    # Isolate the reporting bug from the independent socket construction bug.
    monkeypatch.setattr(capture.socket, 'socket', lambda *_args: PortProbe())
    assert capture.main() == 0
    result = json.loads((case.output / 'result.json').read_text())
    launch = json.loads((case.output / 'launch.json').read_text())
    assert launch['execution_contract']['estimator_run'] is True  # planned
    assert result['estimator_run'] is False  # never started


def test_preflight_wire_drift_refuses_before_output_or_factories(tmp_path, monkeypatch):
    case = setup_entry(tmp_path, monkeypatch)
    doc = json.loads(case.wire.read_text())
    doc['remote_origin_ns'] = 1
    case.wire.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='prospective execution declaration'):
        capture.main()
    assert not case.output.exists()


def test_ordinary_capture_still_checks_port_before_runtime(tmp_path, monkeypatch):
    case = setup_entry(tmp_path, monkeypatch, preflight=False)

    class BusyPort:
        def __enter__(self):
            return self

        def bind(self, endpoint):
            assert endpoint == ('127.0.0.1', 14548)
            raise OSError('test occupied UDP port')

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(capture.socket, 'socket', lambda *_args: BusyPort())
    with pytest.raises(OSError, match='occupied UDP port'):
        capture.main()
    assert not (case.output / 'launch.json').exists()


@pytest.mark.parametrize('failure', ['calibration', 'generated-copy', 'sdk-query'])
def test_preflight_preparation_failure_stays_failed_without_estimator(tmp_path, monkeypatch, failure):
    case = setup_entry(tmp_path, monkeypatch)
    if failure == 'calibration':
        (tmp_path / 'kalibr_imu_chain.yaml').write_text('changed')
    elif failure == 'generated-copy':
        # The copy is checked against the prospective digest by the real binding.
        declaration = tmp_path / 'binding.json'
        data = json.loads(declaration.read_text())
        data['generated']['world.sdf'] = '0' * 64
        declaration.write_text(json.dumps(data))
    else:
        def refuse(*_args, **_kwargs):
            raise RuntimeError('test SDK query refused')
        monkeypatch.setattr(binding, 'QueryClient', refuse)
    assert capture.main() == 2
    result = json.loads((case.output / 'result.json').read_text())
    assert result['status'] == 'capture_failed'
    expected = {'calibration': 'frozen configuration/calibration changed',
                'generated-copy': 'actual generated copy hash mismatch',
                'sdk-query': 'test SDK query refused'}[failure]
    assert len(result['errors']) == 1 and expected in result['errors'][0]
    assert case.forbidden_calls == []
    assert result['estimator_run'] is False
    assert result['eligible_for_vio_input'] is False
    assert result['eligible_for_px4_fusion'] is False
    assert not (case.output / 'runtime-binding-pre.json').exists()


def test_parent_forwards_preflight_and_wire_to_real_worker_main(tmp_path, monkeypatch):
    case = setup_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['capture', *[arg for arg in case.argv if arg != '--worker']])

    def in_process_supervisor(command, output, **options):
        # Process creation/group cleanup is deliberately not under test here.
        assert options['timeout_s'] == 300
        with monkeypatch.context() as child:
            child.setattr(sys, 'argv', command[1:])
            code = capture.main()
        result = json.loads((output / 'result.json').read_text())
        return dict(status='worker_exited', worker_exit=code, capture_status=result['status'],
                    errors=[], cleanup=dict(graceful_group_cleanup_verified=True))

    monkeypatch.setattr(capture, 'supervise_worker', in_process_supervisor)
    assert capture.main() == 0
    result = json.loads((case.output / 'result.json').read_text())
    launch = json.loads((case.output / 'launch.json').read_text())
    assert result['startup_preflight_completed'] is True
    assert result['estimator_run'] is False
    assert launch['execution_contract']['wire']['configuration']['session_id'] == 'entry-test'
    assert launch['execution_contract']['wire']['sha256'] == hashlib.sha256(case.wire.read_bytes()).hexdigest()
