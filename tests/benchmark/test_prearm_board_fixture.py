from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

from flydrones.benchmark.worlds import generate_development_world, write_sdf
from tools.benchmark import make_prearm_board_fixture as fixture_module
from tools.benchmark.make_prearm_board_fixture import make_prearm_board_fixture


def _source(tmp_path):
    world = generate_development_world(1701)
    source_json = tmp_path / 'original.json'
    source_sdf = tmp_path / 'original.sdf'
    source_json.write_text(json.dumps(world) + '\n', encoding='utf-8')
    write_sdf(world, source_sdf)
    return source_json, source_sdf


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prearm_board_fixture_is_deterministic_collidable_and_routeable(tmp_path):
    source_json, source_sdf = _source(tmp_path)
    original_hashes = _sha(source_json), _sha(source_sdf)
    a = tmp_path / 'a'
    b = tmp_path / 'b'
    first = make_prearm_board_fixture(source_json, source_sdf, a)
    second = make_prearm_board_fixture(source_json, source_sdf, b)
    for name in ('world.json', 'world.sdf', 'ground_albedo.png',
                 'obstacle_albedo.png'):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    world = json.loads((a / 'world.json').read_text())
    assert len(world['boxes']) == 2
    assert world['boxes'][0] == {
        'lo': [-5.52, -1.55, .1], 'hi': [-5.48, -.75, 1.4]}
    assert world['boxes'][1] == {
        'lo': [-5.52, .75, .1], 'hi': [-5.48, 1.55, 1.4]}
    root = ET.parse(a / 'world.sdf').getroot()
    for i in (0, 1):
        wall = root.find(f"world/model[@name='wall_{i}']")
        assert wall is not None and wall.findtext('static') == 'true'
        collision = wall.findtext('link/collision/geometry/box/size')
        visual = wall.findtext('link/visual/geometry/box/size')
        assert collision == visual
        assert wall.findtext('link/visual/material/pbr/metal/albedo_map') == 'obstacle_albedo.png'
    assert first['route_preserved'] is True
    assert first['source_world_json_sha256'] == original_hashes[0]
    assert first['source_world_sdf_sha256'] == original_hashes[1]
    assert (_sha(source_json), _sha(source_sdf)) == original_hashes
    assert first['generated_world_sdf_sha256'] == second['generated_world_sdf_sha256']
    assert json.loads((a / 'manifest.json').read_text()) == first
    assert 'physical boards' in first['scope']
    assert 'visual-only' in json.loads((a / 'texture-manifest.json').read_text())['scope']
    assert (a / 'derived-source-world.sdf').is_file()
    assert not list(tmp_path.glob('a-source-*'))


def test_prearm_board_fixture_rejects_wrong_world_and_overwrite(tmp_path):
    source_json, source_sdf = _source(tmp_path)
    out = tmp_path / 'fixture'
    make_prearm_board_fixture(source_json, source_sdf, out)
    with pytest.raises(FileExistsError):
        make_prearm_board_fixture(source_json, source_sdf, out)
    with pytest.raises(ValueError, match='fixed texture seed'):
        make_prearm_board_fixture(source_json, source_sdf, tmp_path / 'wrong-texture',
                                  texture_seed=1702)
    source_sdf.write_text(source_sdf.read_text().replace('0.001', '0.002'))
    with pytest.raises(ValueError, match='source SDF'):
        make_prearm_board_fixture(source_json, source_sdf, tmp_path / 'bad-sdf')
    source_json.write_text(source_json.read_text().replace('1701', '1702', 1))
    with pytest.raises(ValueError, match='seed 1701'):
        make_prearm_board_fixture(source_json, source_sdf, tmp_path / 'bad-seed')


def test_prearm_board_fixture_marks_partial_output_after_write_failure(tmp_path, monkeypatch):
    source_json, source_sdf = _source(tmp_path)
    out = tmp_path / 'partial'

    def interrupted_fixture(_json, _sdf, output_dir, *, seed):
        assert seed == 1701
        output_dir.mkdir()
        (output_dir / 'ground_albedo.png').write_bytes(b'partial')
        raise OSError('injected write failure')

    monkeypatch.setattr(fixture_module, 'make_fixture', interrupted_fixture)
    with pytest.raises(OSError, match='injected write failure'):
        make_prearm_board_fixture(source_json, source_sdf, out)
    incomplete = json.loads((out / 'INCOMPLETE.json').read_text())
    assert incomplete['status'] == 'incomplete'
    assert incomplete['error_type'] == 'OSError'
    assert not (out / 'manifest.json').exists()
    assert not list(tmp_path.glob('partial-source-*'))
    with pytest.raises(FileExistsError):
        make_prearm_board_fixture(source_json, source_sdf, out)
