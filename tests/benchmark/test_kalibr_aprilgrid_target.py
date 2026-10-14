import hashlib
import json
import math
import runpy
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
CODES = [0xd5d628584, 0xd97f18b49, 0xdd280910e, 0xe479e9c98,
         0xebcbca822, 0xf31dab3ac, 0x056a5d085, 0x10652e1d4, 0x22b1dfead]


def upstream_pixels():
    """Run the pinned upstream drawing function against a raster canvas."""
    image = Image.new('L', (960, 960), 255)
    draw = ImageDraw.Draw(image)

    class Canvas:
        def fill(self, rectangle, ignored_color):
            x, y, w, h = rectangle
            # Upstream canvas uses y-up and continuous edge coordinates.
            x, y, w, h = (round(v) for v in (x, y, w, h))
            draw.rectangle((x, 960-y-h, x+w-1, 960-y-1), fill=0)

    globals_ = {'np': np, 'math': math,
                'c': Canvas(), 'path': types.SimpleNamespace(rect=lambda *x: x),
                'color': types.SimpleNamespace(rgb=types.SimpleNamespace(black=0))}
    ref = runpy.run_path(str(ROOT / 'tests/benchmark/fixtures/kalibr_aprilgrid_reference.py'),
                        init_globals=globals_)
    for tag in range(9):
        ref['generateAprilTag'](globals_['c'], (200+(tag % 3)*200, 200+(tag // 3)*200),
                                160, .25, tag, types.SimpleNamespace(tagCodes=CODES, totalBits=36))
    return image


def test_all_pixels_match_official_pinned_generator(tmp_path):
    from tools.benchmark.make_kalibr_aprilgrid_target import make_target
    make_target(tmp_path / 'target')
    with Image.open(tmp_path / 'target/aprilgrid.png') as image:
        assert image.mode == 'L' and image.size == (960, 960)
        assert image.tobytes() == upstream_pixels().tobytes()


def test_metric_layout_model_and_hashes(tmp_path):
    from tools.benchmark.make_kalibr_aprilgrid_target import make_target
    target = tmp_path / 'target'
    manifest = make_target(target)
    assert yaml.safe_load((target / 'target.yaml').read_text()) == {
        'target_type': 'aprilgrid', 'tagRows': 3, 'tagCols': 3,
        'tagSize': .12, 'tagSpacing': .25}
    layout = json.loads((target / 'layout.json').read_text())
    assert len(layout['tags']) == 9
    for tag in layout['tags']:
        i = tag['id']
        x, y = (i % 3)*.15, (i // 3)*.15
        assert np.allclose(tag['corners_target_m'], [[x,y,0],[x+.12,y,0],
                                                   [x+.12,y+.12,0],[x,y+.12,0]])
        assert tag['raster_top_left_px'] == [200+(i % 3)*200, 600-(i // 3)*200]
    sdf = ET.parse(target / 'model.sdf')
    assert sdf.findtext('.//static') == 'true'
    assert sdf.findtext('.//collision/geometry/box/size') == '0.72 0.72 0.02'
    assert sdf.findtext('.//visual/geometry/mesh/uri') == 'aprilgrid.dae'
    assert sdf.findtext('.//albedo_map') == 'aprilgrid.png'
    mesh = ET.parse(target / 'aprilgrid.dae')
    ns = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}
    assert mesh.find('.//c:unit', ns).attrib['meter'] == '1'
    assert mesh.findtext('.//c:float_array[@id="uv-array"]', namespaces=ns) == '0 0 1 0 1 1 0 1'
    for name, entry in manifest['files'].items():
        data = (target / name).read_bytes()
        assert len(data) == entry['bytes']
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
    assert all(value is False for value in manifest['qualification'].values())
    assert sum(p.stat().st_size for p in target.iterdir()) < 131072


def test_output_refusal_and_preserved_failure(tmp_path, monkeypatch):
    from tools.benchmark.make_kalibr_aprilgrid_target import make_target
    target = tmp_path / 'target'
    make_target(target)
    before = (target / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        make_target(target)
    assert (target / 'manifest.json').read_bytes() == before
    monkeypatch.setattr(Image.Image, 'save', lambda *a, **k: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        make_target(tmp_path / 'failed')
    assert json.loads((tmp_path / 'failed/INCOMPLETE.json').read_text())['status'] == 'incomplete'
    assert not (tmp_path / 'failed/manifest.json').exists()


def test_actual_cli_generates_and_refuses_overwrite(tmp_path):
    target = tmp_path / 'cli'
    command = [sys.executable, '-m', 'tools.benchmark.make_kalibr_aprilgrid_target',
               '--output', str(target)]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)['schema'] == 'kalibr-aprilgrid-production-v1'
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert second.returncode != 0 and 'FileExistsError' in second.stderr


def test_collada_required_asset_metadata(tmp_path):
    from tools.benchmark.make_kalibr_aprilgrid_target import make_target
    target = tmp_path / 'schema'
    make_target(target)
    ns = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}
    asset = ET.parse(target / 'aprilgrid.dae').find('c:asset', ns)
    # Khronos COLLADA1.4.1 XSD requires these children, in this order.
    assert [child.tag.rsplit('}', 1)[-1] for child in asset] == [
        'created', 'modified', 'unit', 'up_axis']
    assert asset.findtext('c:created', namespaces=ns) == '2026-10-14T00:00:00Z'
    assert asset.findtext('c:modified', namespaces=ns) == '2026-10-14T00:00:00Z'
