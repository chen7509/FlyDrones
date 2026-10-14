import hashlib
import inspect
import json

import pytest


def call_executor(module, record):
    # Exercise the original resource behavior before the new record API exists.
    if 'admission_record' in inspect.signature(module.execute).parameters:
        return module.execute(record)
    return module.execute()


def test_original_first_gate_refusal_keeps_exact_facts(tmp_path, monkeypatch):
    from tools.benchmark import run_openvins_dataset_consumer as m
    monkeypatch.setattr(m, 'STUDY', tmp_path/'study')
    facts = {'admitted': False, 'windows_available': 101, 'wsl': {'available': 202}}
    monkeypatch.setattr(m, 'admission', lambda: facts)
    record = tmp_path/'first.json'
    with pytest.raises(RuntimeError, match='admission refused'):
        call_executor(m, record)
    assert json.loads(record.read_text()) == facts
    assert not m.STUDY.exists()
    with pytest.raises(FileExistsError):
        call_executor(m, record)


def test_existing_original_study_never_observes_or_writes(tmp_path, monkeypatch):
    from tools.benchmark import run_openvins_dataset_consumer as m
    monkeypatch.setattr(m, 'STUDY', tmp_path)
    monkeypatch.setattr(m, 'admission', lambda: pytest.fail('competing admission'))
    with pytest.raises(FileExistsError):
        call_executor(m, tmp_path/'record.json')
    assert not (tmp_path/'record.json').exists()


def test_changed_seal_refused_before_dataset_or_upstream_read(tmp_path, monkeypatch):
    from tools.benchmark import run_openvins_dataset_consumer as m
    dataset = tmp_path/'data'
    dataset.mkdir()
    changed = dataset/'changed.bin'
    changed.write_bytes(b'changed dataset and expected hash together')
    (dataset/'completion.json').write_text(json.dumps({
        'status': 'file-dataset-production-complete', 'candidate_imu_csv_emitted': True,
        'ulog_bytes_bound_by_reader': True}))
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'members': [{'path': 'data/changed.bin',
        'sha256': hashlib.sha256(changed.read_bytes()).hexdigest()}]}))
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    monkeypatch.setattr(m, 'DATASET', dataset)
    monkeypatch.setattr(m, 'MANIFEST', manifest)
    def upstream(*args, **kwargs):
        value = m.PIN if 'rev-parse' in args else m.LIB_SHA if args[0] == 'sha256sum' else ''
        return type('Output', (), {'stdout': value.encode()})()
    monkeypatch.setattr(m, 'wsl', upstream)
    with pytest.raises(ValueError, match='sealed manifest changed'):
        m.verify_input()


def test_modified_config_refused_before_study_and_build(tmp_path, monkeypatch):
    from tools.benchmark import run_openvins_dataset_consumer as m
    monkeypatch.setattr(m, 'STUDY', tmp_path/'study')
    monkeypatch.setattr(m, 'admission', lambda: {'admitted': True})
    monkeypatch.setattr(m, 'verify_input', lambda: {})
    configs = tmp_path/'config'
    configs.mkdir()
    for name in ('estimator_config.yaml', 'kalibr_imu_chain.yaml', 'kalibr_imucam_chain.yaml'):
        (configs/name).write_text('modified: true\n')
    monkeypatch.setattr(m, 'CONFIG_SOURCE', configs)
    monkeypatch.setattr(m, 'wsl', lambda *a, **k: type('Output', (), {'stdout': b''})())
    monkeypatch.setattr(m, 'scoped', lambda *a, **k: pytest.fail('build dispatched'))
    with pytest.raises(ValueError, match='frozen configuration changed'):
        call_executor(m, tmp_path/'first.json')
    assert not m.STUDY.exists()
