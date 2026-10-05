import hashlib
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from flydrones.benchmark.worlds import generate_development_world, write_sdf
from tools.benchmark import make_prearm_pattern_fixture as pattern_module
from tools.benchmark.make_prearm_board_fixture import make_prearm_board_fixture
from tools.benchmark.make_prearm_pattern_fixture import make_prearm_pattern_fixture
from tools.benchmark.run_episode import prepare_development_textures


def _source(tmp_path):
    original_json = tmp_path / "original.json"
    original_sdf = tmp_path / "original.sdf"
    world = generate_development_world(1701)
    original_json.write_text(json.dumps(world))
    write_sdf(world, original_sdf)
    source = tmp_path / "source"
    make_prearm_board_fixture(original_json, original_sdf, source)
    return source


def test_pattern_changes_only_board_albedo_uris_and_is_deterministic(tmp_path):
    source = _source(tmp_path)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    a, b = tmp_path / "a", tmp_path / "b"
    manifest = make_prearm_pattern_fixture(source, a)
    make_prearm_pattern_fixture(source, b)
    for name in ("world.json", "ground_albedo.png", "obstacle_albedo.png"):
        assert (a / name).read_bytes() == (source / name).read_bytes()
    for name in ("world.sdf", "board_albedo.png", "manifest.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    tree = ET.parse(a / "world.sdf")
    for i in (0, 1):
        node = tree.find(f"world/model[@name='wall_{i}']/link/visual/material/pbr/metal/albedo_map")
        assert node.text == "board_albedo.png"
        node.text = "obstacle_albedo.png"
    assert ET.canonicalize(ET.tostring(tree.getroot(), encoding="unicode"), strip_text=True) == ET.canonicalize(
        (source / "world.sdf").read_text(), strip_text=True)
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    with Image.open(a / "board_albedo.png") as image:
        assert image.size == (512, 512)
        assert image.getpixel((0, 0)) == (24, 24, 24)
        assert image.getpixel((128, 112)) == (232, 232, 232)
    assert manifest["non_board_albedo_sdf_sha256"]


def test_pattern_rejects_tampered_source_and_existing_output(tmp_path):
    source = _source(tmp_path)
    out = tmp_path / "out"
    make_prearm_pattern_fixture(source, out)
    with pytest.raises(FileExistsError):
        make_prearm_pattern_fixture(source, out)
    with (source / "world.sdf").open("a") as stream:
        stream.write("<!-- tampered -->")
    with pytest.raises(ValueError, match="hash"):
        make_prearm_pattern_fixture(source, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_pattern_marks_partial_output_after_failure(tmp_path, monkeypatch):
    source = _source(tmp_path)
    out = tmp_path / "partial"

    def fail(_path):
        raise OSError("injected pattern write failure")

    monkeypatch.setattr(pattern_module, "_board_pattern", fail)
    with pytest.raises(OSError, match="injected"):
        make_prearm_pattern_fixture(source, out)
    assert json.loads((out / "INCOMPLETE.json").read_text())["status"] == "incomplete"
    assert not (out / "manifest.json").exists()


def test_pattern_rejects_dangling_incomplete_marker(tmp_path, monkeypatch):
    from pathlib import Path
    source = _source(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path:
                        path == source / 'INCOMPLETE.json' or original(path))
    with pytest.raises(ValueError, match='incomplete'):
        make_prearm_pattern_fixture(source, tmp_path / 'output')


def test_episode_copies_required_board_asset_and_rejects_missing_pattern(tmp_path):
    source = _source(tmp_path)
    fixture = tmp_path / "fixture"
    make_prearm_pattern_fixture(source, fixture)
    episode = tmp_path / "episode"
    episode.mkdir()
    manifest = prepare_development_textures(fixture, episode)
    assert manifest["files"]["board_albedo.png"]["sha256"] == hashlib.sha256(
        (fixture / "board_albedo.png").read_bytes()).hexdigest()
    (fixture / "board_albedo.png").unlink()
    empty_episode = tmp_path / "empty_episode"
    empty_episode.mkdir()
    with pytest.raises(ValueError, match="texture"):
        prepare_development_textures(fixture, empty_episode)
    assert not list(empty_episode.iterdir())


@pytest.mark.parametrize("failure", ["incomplete", "undeclared", "tampered"])
def test_episode_rejects_untrusted_pattern_before_copy(tmp_path, failure):
    source = _source(tmp_path)
    fixture = tmp_path / "fixture"
    make_prearm_pattern_fixture(source, fixture)
    if failure == "incomplete":
        (fixture / "INCOMPLETE.json").write_text('{"status":"incomplete"}')
    elif failure == "undeclared":
        (fixture / "manifest.json").write_text('{"schema":"unknown"}')
    else:
        (fixture / "board_albedo.png").write_bytes(b"changed")
    episode = tmp_path / "episode"
    episode.mkdir()
    with pytest.raises(ValueError):
        prepare_development_textures(fixture, episode)
    assert not list(episode.iterdir())
