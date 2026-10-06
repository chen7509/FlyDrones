import hashlib
import json
from pathlib import Path

import pytest

from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark import runtime_resource_binding as binding
from tools.benchmark.capture_contract import execution_contract
from tools.benchmark.declared_runtime_snapshot import snapshot
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal


def fixture(tmp_path):
    source = tmp_path / 'selected.so'
    source.write_bytes(b'x')
    generated = {}
    for name in binding.GENERATED_NAMES:
        p = tmp_path / name
        p.write_bytes(name.encode())
        generated[name] = p
    inventory = {'selected': [str(source)]}
    doc = dict(schema='capture-resource-binding-v1', inventory=inventory, baseline=snapshot(inventory),
               environment={key: None for key in binding.ENV_KEYS},
               generated={name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in generated.items()})
    output = tmp_path / 'capture'
    output.mkdir()
    return doc, generated, source, output


def v3(doc):
    doc['schema'] = 'capture-resource-binding-v3'
    doc['graph'] = dict(schema='generated-resource-graph-v1', cwd=str(Path.cwd()),
                        environment={key: None for key in binding.QUERY_ENV_KEYS},
                        expected_context={})
    doc['runtime_maps'] = dict(self_phases=['postimports', 'postfinalize', 'postfirststep'],
                               owned_roles={'px4': ['ready', 'prestop']},
                               max_maps_bytes=8 * 1024 * 1024, max_observations=8)
    return doc


def start(doc, generated, source, output, **kwargs):
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    obj.start(generated, {key: None for key in binding.ENV_KEYS}, [source], **kwargs)
    return obj


def test_binding_accepts_only_declared_mesa_cache_control(tmp_path):
    doc, _, _, _ = fixture(tmp_path)
    doc['environment']['MESA_SHADER_CACHE_DISABLE'] = 'true'
    assert binding.validate_binding(doc)['environment']['MESA_SHADER_CACHE_DISABLE'] == 'true'
    doc['environment']['MESA_SHADER_CACHE_DISABLE'] = 'false'
    with pytest.raises(ValueError, match='lookup keys'):
        binding.validate_binding(doc)
    doc['environment'].pop('MESA_SHADER_CACHE_DISABLE')
    doc['environment']['UNDECLARED_RENDERER_SETTING'] = 'true'
    with pytest.raises(ValueError, match='lookup keys'):
        binding.validate_binding(doc)


def test_pre_and_post_records_without_claiming_full_closure(tmp_path):
    doc, generated, source, output = fixture(tmp_path)
    obj = start(doc, generated, source, output)
    assert (output / 'runtime-binding-pre.json').is_file()
    result = obj.finish()
    assert result['pre_recorded'] is True and result['declared_files_stable'] is True
    assert result['runtime_closure_qualified'] is False
    assert result['errors'] == []


@pytest.mark.parametrize('change', ['baseline', 'baseline_type', 'copy', 'environment', 'missing_selected'])
def test_bad_setup_refuses_before_callback(tmp_path, change):
    doc, generated, source, output = fixture(tmp_path)
    env = {key: None for key in binding.ENV_KEYS}
    if change == 'baseline':
        source.write_bytes(b'drift')
    elif change == 'baseline_type':
        doc['baseline']['files'][0]['bytes'] = True
    elif change == 'copy':
        generated['world.sdf'].write_bytes(b'changed')
    elif change == 'environment':
        env['GZ_SIM_RESOURCE_PATH'] = '/different'
    else:
        source = tmp_path / 'other'
        source.write_bytes(b'x')
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    with pytest.raises(ValueError):
        obj.start(generated, env, [source])
    assert not obj.pre_recorded


@pytest.mark.parametrize('change', ['extra', 'missing_env', 'missing_generated', 'empty', 'bad_digest'])
def test_invalid_declarations_refused(tmp_path, change):
    doc, generated, source, output = fixture(tmp_path)
    if change == 'extra':
        doc['ignored'] = True
    elif change == 'missing_env':
        doc['environment'].pop('LD_LIBRARY_PATH')
    elif change == 'missing_generated':
        doc['generated'].pop('gz_env.sh')
    elif change == 'bad_digest':
        doc['generated']['gz_env.sh'] = 'unknown'
    else:
        doc['inventory'] = {}
    with pytest.raises(ValueError):
        binding.RuntimeBinding(doc, output, map_reader=lambda: '')


def test_capture_failure_keeps_original_and_post_drift(tmp_path):
    doc, generated, source, output = fixture(tmp_path)
    result = {'status': 'incomplete', 'errors': []}
    with CaptureJournal(output, result) as journal:
        obj = binding.attach_binding(journal, result, doc, output, map_reader=lambda: '')
        obj.start(generated, {key: None for key in binding.ENV_KEYS}, [source])
        source.write_bytes(b'changed')
        raise RuntimeError('original startup failure')
    assert result['status'] == 'capture_failed'
    assert any('original startup failure' in e for e in result['errors'])
    assert any('runtime binding' in e for e in result['errors'])
    assert result['runtime_binding']['declared_files_stable'] is False
    assert (output / 'runtime-binding-post.json').is_file()


def test_failed_pre_still_gets_terminal_binding_result(tmp_path, monkeypatch):
    doc, generated, source, output = fixture(tmp_path)
    result = {'status': 'incomplete', 'errors': []}
    original = binding.write_manifest
    def fail_pre(path, data):
        if path.name == 'runtime-binding-pre.json':
            raise OSError('close failed')
        return original(path, data)
    monkeypatch.setattr(binding, 'write_manifest', fail_pre)
    with CaptureJournal(output, result) as journal:
        obj = binding.attach_binding(journal, result, doc, output, map_reader=lambda: '')
        obj.start(generated, {key: None for key in binding.ENV_KEYS}, [source])
        pytest.fail('startup advanced after failed pre record')
    assert result['status'] == 'capture_failed'
    assert result['runtime_binding']['pre_recorded'] is False


def test_mapping_parser_preserves_file_identity_and_rejects_deleted():
    text = '1000-2000 r-xp 0000 08:01 12 /usr/lib/libexample.so\n2000-3000 rw-p 0000 00:00 0 [heap]\n'
    rows = binding.parse_maps(text)
    assert rows == [dict(path='/usr/lib/libexample.so', device='08:01', inode=12)]
    for bad in ['garbage', text.replace('libexample.so', 'libexample.so (deleted)'),
                text.replace('/usr/lib/libexample.so', 'relative.so')]:
        with pytest.raises(ValueError):
            binding.parse_maps(bad)


def test_unknown_mapping_is_recorded_before_refusal(tmp_path):
    doc, generated, source, output = fixture(tmp_path)
    obj = start(doc, generated, source, output)
    obj.map_reader = lambda: '1000-2000 r-xp 0000 08:01 12 /not/declared.so\n'
    with pytest.raises(ValueError, match='mapping'):
        obj.observe('postimports')
    recorded = json.loads((output / 'runtime-maps-postimports.json').read_text())
    assert recorded['unknown'][0]['path'] == '/not/declared.so'
    assert obj.finish()['runtime_closure_qualified'] is False


@pytest.mark.parametrize('role', ['bootstrap:selfmaps', 'generated:world.sdf'])
def test_reserved_inventory_role_cannot_replace_required_baseline(tmp_path, role):
    doc, generated, source, output = fixture(tmp_path)
    doc['inventory'] = {role: [str(source)]}
    doc['baseline'] = snapshot(doc['inventory'])
    with pytest.raises(ValueError, match='reserved'):
        binding.RuntimeBinding(doc, output, map_reader=lambda: '')


def test_cli_binding_requires_execution_declaration(tmp_path):
    with pytest.raises(SystemExit):
        capture.parse_capture_args(['--output', str(tmp_path / 'out'), '--runtime-binding', 'binding.json'])


def test_parent_validates_binding_and_forwards_it(tmp_path, monkeypatch):
    doc, generated, source, output = fixture(tmp_path)
    path = tmp_path / 'binding.json'
    path.write_text(json.dumps(doc))
    declaration = tmp_path / 'contract.json'
    argv = ['--output', str(output), '--runtime-binding', str(path), '--execution-contract', str(declaration)]
    parsed = capture.parse_capture_args(argv)
    declaration.write_text(json.dumps(execution_contract(parsed)))
    monkeypatch.setattr('sys.argv', ['capture', *argv])
    calls = []
    def supervise(command, output, **kwargs):
        calls.append(command)
        return dict(status='worker_exited', worker_exit=0, capture_status='capture_completed',
                    cleanup={'graceful_group_cleanup_verified': True}, errors=[])
    monkeypatch.setattr(capture, 'supervise_worker', supervise)
    assert capture.main() == 0
    assert calls[0][-2:] == ['--runtime-binding', str(path.resolve())]
    doc['environment'].pop('HOME')
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        capture.main()
    assert len(calls) == 1


@pytest.mark.parametrize('which', ['baseline', 'generated'])
def test_change_between_validation_and_combined_snapshot_is_not_adopted(tmp_path, which):
    doc, generated, source, output = fixture(tmp_path)
    def maps():
        target = source if which == 'baseline' else generated['world.sdf']
        target.write_bytes(b'changed between reads')
        return ''
    obj = binding.RuntimeBinding(doc, output, map_reader=maps)
    with pytest.raises(ValueError, match='between'):
        obj.start(generated, {key: None for key in binding.ENV_KEYS}, [source])
    assert not obj.pre_recorded
    assert obj.finish()['declared_files_stable'] is False


@pytest.mark.parametrize('omitted', ['kalibr_imu_chain.yaml', 'kalibr_imucam_chain.yaml', 'freeze.json'])
def test_actual_estimator_calibration_omission_is_refused(tmp_path, omitted):
    doc, generated, source, output = fixture(tmp_path)
    directory = tmp_path / 'config'
    directory.mkdir()
    contents = {'estimator_config.yaml': 'relative_config_imu: kalibr_imu_chain.yaml\nrelative_config_imucam: kalibr_imucam_chain.yaml\n',
                'kalibr_imu_chain.yaml': 'imu config', 'kalibr_imucam_chain.yaml': 'camera config'}
    for name, text in contents.items():
        (directory / name).write_text(text)
    (directory / 'freeze.json').write_text(json.dumps({'sha256': {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in contents}}))
    paths = [source] + [directory / name for name in [*contents, 'freeze.json'] if name != omitted]
    doc['inventory'] = {'selected': [str(p) for p in paths]}
    doc['baseline'] = snapshot(doc['inventory'])
    selected = binding.estimator_inputs(source, directory / 'estimator_config.yaml', None)
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    with pytest.raises(ValueError, match='absent'):
        obj.start(generated, {key: None for key in binding.ENV_KEYS}, selected)
