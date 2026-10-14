"""Produce a metric AprilGrid asset; no sensor capture or calibration qualification.

This product includes software developed by the Autonomous Systems Lab and
Skybotix AG. Codes/drawing convention: pinned Kalibr; see the retained notice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
PIN = '1f60227442d25e36365ef5f72cd80b9666d73467'
# IDs 0..8 from pinned Tag36h11.h (not Tag36h11_other.h).
CODES = (0xd5d628584, 0xd97f18b49, 0xdd280910e, 0xe479e9c98,
         0xebcbca822, 0xf31dab3ac, 0x056a5d085, 0x10652e1d4, 0x22b1dfead)

MESH = '''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
 <asset><created>2026-10-14T00:00:00Z</created><modified>2026-10-14T00:00:00Z</modified><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
 <library_geometries><geometry id="face"><mesh>
  <source id="positions"><float_array id="position-array" count="12">-0.15 -0.15 0 0.57 -0.15 0 0.57 0.57 0 -0.15 0.57 0</float_array>
   <technique_common><accessor source="#position-array" count="4" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
  <source id="uv"><float_array id="uv-array" count="8">0 0 1 0 1 1 0 1</float_array>
   <technique_common><accessor source="#uv-array" count="4" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
  <vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
  <triangles count="2"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>0 0 1 1 2 2 0 0 2 2 3 3</p></triangles>
 </mesh></geometry></library_geometries>
 <library_visual_scenes><visual_scene id="scene"><node id="board"><instance_geometry url="#face"/></node></visual_scene></library_visual_scenes>
 <scene><instance_visual_scene url="#scene"/></scene>
</COLLADA>
'''

SDF = '''<?xml version="1.0" encoding="utf-8"?>
<sdf version="1.9"><model name="kalibr_aprilgrid_3x3"><static>true</static><link name="board">
 <collision name="slab"><pose>0.21 0.21 -0.01 0 0 0</pose><geometry><box><size>0.72 0.72 0.02</size></box></geometry></collision>
 <visual name="target"><geometry><mesh><uri>aprilgrid.dae</uri></mesh></geometry>
  <material><ambient>1 1 1 1</ambient><diffuse>1 1 1 1</diffuse><specular>0 0 0 1</specular>
   <pbr><metal><metalness>0</metalness><roughness>1</roughness><albedo_map>aprilgrid.png</albedo_map></metal></pbr></material>
 </visual>
</link></model></sdf>
'''


def _write(output: Path, name: str, data: bytes) -> None:
    with (output / name).open('xb') as stream:
        stream.write(data)


def make_target(output: Path) -> dict:
    """Create fixed assets exclusively; retain incomplete output on failure.

    Paths must be controlled and static. Design dimensions and hashes never
    imply print metrology, rendered visibility, source identity or calibration.
    """
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('target output already exists; use a new directory')
    output.mkdir(parents=True, exist_ok=False)
    try:
        image = Image.new('L', (960, 960), 255)
        draw = ImageDraw.Draw(image)
        tags = []
        for tag_id, code in enumerate(CODES):
            col, row = tag_id % 3, tag_id // 3
            left, top = 200+col*200, 600-row*200
            draw.rectangle((left, top, left+159, top+159), fill=0)
            # Official PDF uses inverted black bits then np.rot90(..., 2).
            # Raster (i,j) therefore uses original bit (5-i,5-j).
            for i in range(6):
                for j in range(6):
                    if code & (1 << (6*(5-i)+(5-j))):
                        x, y = left+32+j*16, top+32+i*16
                        draw.rectangle((x, y, x+15, y+15), fill=255)
            # Official symmetric subpixel-refinement corner squares.
            for x in (left-40, left+160):
                for y in (top-40, top+160):
                    draw.rectangle((x, y, x+39, y+39), fill=0)
            x, y = col*.15, row*.15
            tags.append({'id': tag_id, 'code_hex': f'{code:09x}',
                         'raster_top_left_px': [left, top], 'tag_edge_px': 160,
                         'corners_target_m': [[x,y,0], [x+.12,y,0],
                                              [x+.12,y+.12,0], [x,y+.12,0]]})
        with (output / 'aprilgrid.png').open('xb') as stream:
            image.save(stream, format='PNG')
        _write(output, 'target.yaml', b'target_type: aprilgrid\ntagRows: 3\ntagCols: 3\ntagSize: 0.12\ntagSpacing: 0.25\n')
        layout = {'schema': 'kalibr-aprilgrid-layout-v1', 'tags': tags,
                  'target_axes': 'x right / y up / z out; origin tag0 bottom-left',
                  'black_border_modules': 2, 'module_px': 16, 'margin_px': 200,
                  'meters_per_pixel': .00075, 'physical_dimensions_measured': False,
                  'detector_compatibility': 'pinned Kalibr default border2; native detection untested'}
        _write(output, 'layout.json', (json.dumps(layout, indent=2)+'\n').encode())
        _write(output, 'aprilgrid.dae', MESH.encode())
        _write(output, 'model.sdf', SDF.encode())
        _write(output, 'model.config', b'<?xml version="1.0"?><model><name>kalibr_aprilgrid_3x3</name><version>1</version><sdf version="1.9">model.sdf</sdf><description>Unqualified calibration target design asset</description></model>\n')
        for name in ('NOTICE.txt', 'LICENSE'):
            _write(output, name, (ROOT / 'third_party/kalibr-aprilgrid' / name).read_bytes())
        files = {}
        for path in sorted(output.iterdir()):
            data = path.read_bytes()
            files[path.name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        manifest = {'schema': 'kalibr-aprilgrid-production-v1', 'upstream_pin': PIN,
                    'files': files, 'generated_target': True,
                    'qualification': dict.fromkeys(('source', 'clock', 'measured_calibration',
                                                    'training', 'flight'), False),
                    'pending': ['native detector', 'Gazebo UV/visibility', 'owned new capture study',
                                'multi-axis excitation', 'Kalibr solve and independent quality audit']}
        _write(output, 'manifest.json', (json.dumps(manifest, indent=2)+'\n').encode())
        return manifest
    except BaseException as exc:
        _write(output, 'INCOMPLETE.json', (json.dumps({'status': 'incomplete',
               'error_type': type(exc).__name__, 'retry': 'new directory only'})+'\n').encode())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(make_target(args.output), indent=2))


if __name__ == '__main__':
    main()
