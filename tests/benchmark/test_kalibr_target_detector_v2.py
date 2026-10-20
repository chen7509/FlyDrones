import json

import pytest


def test_original_guard_not_overridden(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector as original
    from tools.benchmark import run_kalibr_target_detector_v2 as m
    old = original.STUDY
    monkeypatch.setattr(m, 'STUDY', tmp_path/'consumed')
    m.STUDY.mkdir()
    with pytest.raises(FileExistsError):
        m.execute_once(tmp_path/'record.json')
    assert original.STUDY == old
    assert not (tmp_path/'record.json').exists()


def test_cache_manifest_cannot_be_substituted(tmp_path, monkeypatch):
    from tools.benchmark import run_kalibr_target_detector_v2 as m
    p = tmp_path/'manifest.json'
    p.write_text(json.dumps({'wrong.o':{'sha256':'0'*64}}))
    monkeypatch.setattr(m, 'CACHE_MANIFEST', p)
    with pytest.raises(ValueError, match='cache manifest'):
        m.verify_cache()
