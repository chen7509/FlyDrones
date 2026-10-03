from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from tools.benchmark.make_vio_texture_fixture import make_fixture

SOURCE = """<sdf version="1.9"><world name="development">
<physics name="fixed"><max_step_size>0.001</max_step_size></physics>
<model name="ground"><static>true</static><pose>0 0 -0.1 0 0 0</pose><link name="body">
<collision name="collision"><geometry><box><size>100 100 .2</size></box></geometry></collision>
<visual name="visual"><geometry><box><size>100 100 .2</size></box></geometry>
<material><ambient>.45 .5 .35 1</ambient><diffuse>.45 .5 .35 1</diffuse></material></visual>
</link></model>
<model name="tree_0"><static>true</static><pose>0 0 2.25 0 0 0</pose><link name="body">
<collision name="collision"><geometry><cylinder><radius>.8</radius><length>4.5</length></cylinder></geometry></collision>
<visual name="visual"><geometry><cylinder><radius>.8</radius><length>4.5</length></cylinder></geometry>
<material><diffuse>.25 .15 .07 1</diffuse></material></visual>
</link></model></world></sdf>"""


def _source(tmp_path):
    world_json = tmp_path / "original.json"
    world_sdf = tmp_path / "original.sdf"
    world_json.write_text('{"seed":1701,"family":"development_single"}\n')
    world_sdf.write_text(SOURCE)
    return world_json, world_sdf


def test_fixture_is_deterministic_and_preserves_physics_and_collision(tmp_path) -> None:
    source_json, source_sdf = _source(tmp_path)
    one, two = tmp_path / "one", tmp_path / "two"
    first = make_fixture(source_json, source_sdf, one, seed=17)
    second = make_fixture(source_json, source_sdf, two, seed=17)
    for name in ("world.json", "world.sdf", "ground_albedo.png", "obstacle_albedo.png"):
        assert (one / name).read_bytes() == (two / name).read_bytes()
    assert (one / "world.json").read_bytes() == source_json.read_bytes()
    original = ET.parse(source_sdf).getroot()
    modified = ET.parse(one / "world.sdf").getroot()
    for path in ("world/physics", "world/model[@name='ground']/pose",
                 "world/model[@name='ground']/link/collision",
                 "world/model[@name='tree_0']/pose",
                 "world/model[@name='tree_0']/link/collision"):
        source = ET.canonicalize(ET.tostring(original.find(path), encoding="unicode"), strip_text=True)
        target = ET.canonicalize(ET.tostring(modified.find(path), encoding="unicode"), strip_text=True)
        assert source == target
    assert modified.findtext("world/model[@name='ground']/link/visual/material/pbr/metal/albedo_map") == "ground_albedo.png"
    assert modified.findtext("world/model[@name='tree_0']/link/visual/material/pbr/metal/albedo_map") == "obstacle_albedo.png"
    assert first["source_world_sha256"] == second["source_world_sha256"]
    assert json.loads((one / "manifest.json").read_text()) == first


def test_fixture_rejects_overwrite_and_missing_ground(tmp_path) -> None:
    source_json, source_sdf = _source(tmp_path)
    out = tmp_path / "fixture"
    make_fixture(source_json, source_sdf, out, seed=1)
    with pytest.raises(FileExistsError):
        make_fixture(source_json, source_sdf, out, seed=1)
    source_sdf.write_text(SOURCE.replace('name="ground"', 'name="other"'))
    with pytest.raises(ValueError, match="ground"):
        make_fixture(source_json, source_sdf, tmp_path / "bad", seed=1)
