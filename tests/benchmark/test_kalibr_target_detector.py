import json

import pytest


def facts(memory):
    return {'windows_available': memory, 'wsl': {'available': memory},
            'blocked_processes': [], 'docker_exit': 0, 'docker_running': ''}


def test_independent_admission_keeps_original_reserve():
    from tools.benchmark import run_kalibr_target_detector as m
    from tools.benchmark.run_openvins_dataset_consumer import MIN_MEMORY
    assert MIN_MEMORY == 2*1024**3
    assert m.admitted(facts(1024**3))
    assert not m.admitted(facts(1024**3-1))
    d = facts(1024**3)
    d['blocked_processes'] = [{'pid': 9}]
    assert not m.admitted(d)


def test_refusal_persists_and_never_creates_study(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as m
    monkeypatch.setattr(m, 'STUDY', tmp_path/'study')
    monkeypatch.setattr(m, 'admission', lambda: facts(0))
    with pytest.raises(RuntimeError):
        m.execute_once(tmp_path/'first.json')
    assert json.loads((tmp_path/'first.json').read_text())['facts']['windows_available'] == 0
    assert not m.STUDY.exists()
    with pytest.raises(FileExistsError):
        m.execute_once(tmp_path/'first.json')


def test_existing_study_cannot_retry_even_with_new_record(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as m
    monkeypatch.setattr(m, 'STUDY', tmp_path/'study')
    m.STUDY.mkdir()
    with pytest.raises(FileExistsError):
        m.execute_once(tmp_path/'different.json')
    assert not (tmp_path/'different.json').exists()


def test_manifest_identity_mutation_refuses(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as m
    source = tmp_path/'source'
    source.mkdir()
    p = source/'one.cc'
    p.write_bytes(b'bad')
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'pin':m.PIN, 'members':[{'path':str(p),'sha256':'0'*64}]}))
    monkeypatch.setattr(m, 'SOURCE_MANIFEST', manifest)
    with pytest.raises(ValueError):
        m.verify_sources()


def test_actual_member_mutation_under_valid_manifest_refuses(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as m
    row = json.loads(m.SOURCE_MANIFEST.read_text())['members'][0]
    data = (m.ROOT/row['path']).read_bytes()
    target = tmp_path/row['path']
    target.parent.mkdir(parents=True)
    target.write_bytes(data+b'changed')
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='pinned source bytes changed'):
        m.verify_sources()


def test_actual_link_recipe_includes_pinned_pose_symbols(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as m

    class ObservedRecipe(Exception):
        pass

    monkeypatch.setattr(m, 'STUDY', tmp_path/'study')
    monkeypatch.setattr(m, 'admission', lambda: facts(1024**3))

    def observe(*args, **kwargs):
        commands = json.loads((m.STUDY/'build-commands.json').read_text())['commands']
        assert '-lopencv_calib3d' in commands[-1]
        raise ObservedRecipe

    monkeypatch.setattr(m, 'scoped', observe)
    with pytest.raises(ObservedRecipe):
        m.execute_once(tmp_path/'first.json')
