"""Materialize a new target-bearing source scene and time-only design load.

Uses libsdformat semantic poses, never a simulator or a measured calibration.
Input/output directories must be controlled and static throughout the operation.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

TARGET_MANIFEST_SHA = '6999d535dea7b6c156a618fa309aac6bb45b919026e5d5d468ea548e8d8e4fc2'
TEMPLATE_SHA = 'b42bd639080c967ceb84edc7bbf023b064dbd4fc610ccb81a1eaceb5fb373c1e'
MODEL_SDF_HASHES = {
    'models/x500_base/model.sdf': 'e807dca3406f7cd5cb3d545898601c3ec17e0e5242e25cf467a69df1812cf436',
    'models/x500/model.sdf': 'cfe92f98360967faa895b77aa8a6fff3fc9b290286e94e45297c4bdd7b62fbf9',
    'models/x500_benchmark/model.sdf': 'ff8eaa1dbb73b77d693e1d29908bc0ebee6ffa64311951e133db38fda82e7ee9',
    'models/OakD-Benchmark/model.sdf': '806c532bd2a22e9caa85d79bf5fd974d7ce02b1eb660df7802c1fc557f4ae5fe',
}
MODEL_CONFIG_HASHES = {
    'models/x500_base/model.config': '4856afbdeb52f19468f56ddaf4be57c04688f347b8cef2f609daacd2d014d437',
    'models/x500/model.config': '52fdda8e66faa5095434d54e4dcaad5a6a8833cd014e0a5b439349ed8b4a1b67',
    'models/x500_benchmark/model.config': '8ee3cb7538603f4ac4a20991f239c90c6f45ac493b6866b2935865d047e32949',
    'models/OakD-Benchmark/model.config': '8833a7d9785b2c17cc120d80af883513bae65eb7dfa6cec111ed524780884ee8',
}
LIMITS = dict(duration_s=25, step_s=.001, latest_anchor_s=8.2, program_end_s=14,
              force_n=40, torque_nm=.1, angular_speed_rad_s=.5, displacement_m=1,
              speed_m_s=3, tilt_rad=math.pi / 4, ground_clearance_m=.1, target_clearance_m=.1)
QUALIFICATION = {k: False for k in ('source', 'clock', 'measured_calibration', 'accuracy',
                                  'teacher', 'fusion', 'training', 'flight')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def rotation(rpy):
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
                     [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr], [-sp, cp*sr, cp*cr]])


def transform(pose):
    result = np.eye(4)
    result[:3, :3] = rotation(pose[3:])
    result[:3, 3] = pose[:3]
    return result


def aggregate(links):
    masses = np.array([p['mass'] for p in links], dtype=float)
    coms = np.array([p['com'] for p in links], dtype=float)
    if not len(links) or not np.isfinite(masses).all() or np.any(masses <= 0) or not np.isfinite(coms).all():
        raise ValueError('invalid composite mass/COM')
    mass = float(masses.sum())
    center = (masses[:, None] * coms).sum(axis=0) / mass
    inertia = np.zeros((3, 3))
    for row in links:
        tensor = np.array(row['inertia'], dtype=float)
        if tensor.shape != (3, 3) or not np.isfinite(tensor).all() or not np.allclose(tensor, tensor.T):
            raise ValueError('invalid inertial tensor')
        if np.linalg.eigvalsh(tensor).min() <= 0:
            raise ValueError('nonpositive inertial tensor')
        d = np.array(row['com']) - center
        inertia += tensor + row['mass'] * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return dict(mass_kg=mass, com_model_m=center.tolist(), inertia_com_model_kg_m2=inertia.tolist())


def pulse(u):
    if not 0 <= u <= 1:
        return 0., 0., 0.
    return (64 * u**3 * (1-u)**3,
            192*u**2 - 768*u**3 + 960*u**4 - 384*u**5,
            384*u - 2304*u**2 + 3840*u**3 - 1920*u**4)


def request(relative_s, mass, inertia):
    """Time-only requested kinematics/loads, including the original quintic lift."""
    if not math.isfinite(relative_s) or not 0 <= relative_s <= 25:
        raise ValueError('invalid relative program time')
    position, velocity, acceleration = np.zeros(3), np.zeros(3), np.zeros(3)
    rpy, omega, alpha = np.zeros(3), np.zeros(3), np.zeros(3)
    u = min(relative_s / 2, 1)
    position[2] = .4 * (10*u**3 - 15*u**4 + 6*u**5)
    velocity[2] = .2 * (30*u**2 - 60*u**3 + 30*u**4)
    acceleration[2] = .1 * (60*u - 180*u**2 + 120*u**3)
    for index in range(6):
        q, dq, ddq = pulse((relative_s - (2 + 2*index)) / 2)
        axis = index % 3
        amplitude = math.radians(8) if index < 3 else .01
        if index < 3:
            rpy[axis], omega[axis], alpha[axis] = amplitude*q, amplitude*dq/2, amplitude*ddq/4
        else:
            position[axis] += amplitude*q
            velocity[axis] += amplitude*dq/2
            acceleration[axis] += amplitude*ddq/4
    rotate = rotation(rpy)
    world_inertia = rotate @ np.asarray(inertia) @ rotate.T
    torque = world_inertia @ alpha + np.cross(omega, world_inertia @ omega)
    force = mass * (acceleration + [0, 0, 9.81])
    return dict(relative_s=relative_s, translation_m=position.tolist(), velocity_m_s=velocity.tolist(),
                rotation_rpy_rad=rpy.tolist(), omega_world_rad_s=omega.tolist(),
                force_world_n=force.tolist(), torque_world_nm=torque.tolist())


def _pose(p):
    return [p.x(), p.y(), p.z(), p.rot().roll(), p.rot().pitch(), p.rot().yaw()]


def resolve_geometry(world_path, model_directory):
    """Native SDFormat include/frame graph; failures are propagated, never guessed."""
    import sdformat14 as sdf

    config = sdf.ParserConfig()
    config.add_uri_path('model://', str(model_directory))
    # The retained x500_benchmark uses a bare `x500` URI. Gazebo installs a
    # resolver for that form; standalone libsdformat requires one explicitly.
    def find_model(uri):
        name = uri.removeprefix('model://')
        candidate = model_directory / name
        if name in ('x500', 'x500_base', 'x500_benchmark', 'OakD-Benchmark', 'kalibr_aprilgrid_3x3'):
            return str(candidate) if candidate.is_dir() else ''
        return ''

    config.set_find_callback(find_model)
    root = sdf.Root()
    root.load(str(world_path), config)
    model = root.world_by_index(0).model_by_name('x500_benchmark_8')
    model.validate_graphs()
    if model.model_count() != 0 or model.link_count() != 6:
        raise ValueError('unsupported merged rig graph')
    rows, boxes, link_records = [], [], {}
    for i in range(model.link_count()):
        link = model.link_by_index(i)
        pose = _pose(link.semantic_pose().resolve())
        link_matrix = transform(pose)
        inertial = link.inertial()
        local = link_matrix @ transform(_pose(inertial.pose()))
        matrix = inertial.mass_matrix()
        diag, off = matrix.diagonal_moments(), matrix.off_diagonal_moments()
        tensor = np.array([[diag.x(), off.x(), off.y()], [off.x(), diag.y(), off.z()],
                           [off.y(), off.z(), diag.z()]])
        tensor = local[:3, :3] @ tensor @ local[:3, :3].T
        row = dict(name=link.name(), mass=matrix.mass(), com=local[:3, 3].tolist(), inertia=tensor.tolist())
        rows.append(row)
        link_records[link.name()] = dict(row, pose_model=pose)
        for c in range(link.collision_count()):
            collision = link.collision_by_index(c)
            box = collision.geometry().box_shape()
            if box is None:
                raise ValueError('unsupported collision shape')
            size = np.array([box.size().x(), box.size().y(), box.size().z()])
            coll_pose = transform(_pose(collision.semantic_pose().resolve('__model__')))
            points = np.array(list(itertools.product(*[(-s/2, s/2) for s in size])))
            # Revolute rotor sweep: circumscribed sphere is conservative for every
            # joint angle and does not pretend that its box orientation stays fixed.
            if link.name().startswith('rotor_'):
                radius = float(np.linalg.norm(coll_pose[:3, 3] - link_matrix[:3, 3]) + np.linalg.norm(size/2))
                points = np.array(list(itertools.product((-radius, radius), repeat=3)))
                coll_pose = link_matrix
            boxes.extend((points @ coll_pose[:3, :3].T + coll_pose[:3, 3]).tolist())
    camera = model.link_by_name('camera_link').sensor_by_name('rgbd')
    camera_pose = _pose(camera.semantic_pose().resolve('__model__'))
    # Camera properties are also read from retained source XML; refuse workload changes.
    camera_xml = ET.parse(model_directory / 'OakD-Benchmark/model.sdf').find('model/link/sensor')
    camera_params = dict(width=int(camera_xml.findtext('camera/image/width')),
                         height=int(camera_xml.findtext('camera/image/height')),
                         hfov=float(camera_xml.findtext('camera/horizontal_fov')),
                         near=float(camera_xml.findtext('camera/clip/near')),
                         far=float(camera_xml.findtext('camera/clip/far')))
    if camera_params != dict(width=160, height=120, hfov=1.274, near=.2, far=19.1):
        raise ValueError('camera workload changed')
    return dict(aggregate(rows), links=link_records, collision_vertices_model=boxes,
                model_pose_world=_pose(model.semantic_pose().resolve()), camera_pose_model=camera_pose,
                camera=camera_params, resolution='installed libsdformat14 semantic_pose.resolve',
                inertia_scope='instantaneous frozen rotor assembly design coefficient, not a rigid joint claim')


def design(geometry):
    model = transform(geometry['model_pose_world'])
    camera = transform(geometry['camera_pose_model'])
    initial_camera = model @ camera
    # Keep the original +X camera convention and place target from initial design,
    # never from runtime truth. This fixed study requires aligned initial axes.
    if not np.allclose(initial_camera[:3, :3], np.eye(3), atol=1e-12):
        raise ValueError('unsupported initial camera orientation')
    initial_vertices = np.asarray(geometry['collision_vertices_model']) @ model[:3, :3].T + model[:3, 3]
    if abs(float(initial_vertices[:, 2].min())) > 1e-9:
        raise ValueError('initial ground contact required before unforced readiness')
    center = initial_camera[:3, 3] + [.6, 0, .4]
    target_rotation = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]])
    origin = center - target_rotation @ [.21, .21, 0]
    corners = np.array([[x + dx, y + dy, 0] for y in (0, .15, .30) for x in (0, .15, .30)
                        for dx, dy in ((0, 0), (.12, 0), (.12, .12), (0, .12))])
    world_corners = corners @ target_rotation.T + origin
    inertia = np.asarray(geometry['inertia_com_model_kg_m2'])
    com = np.asarray(geometry['com_model_m'])
    vertices = np.asarray(geometry['collision_vertices_model'])
    f = 80 / math.tan(geometry['camera']['hfov']/2)
    # Conservative analytic maxima for the fixed polynomial program. |q'|<3.5,
    # |q''|<=24; original lift speed<=.375 and |acceleration|<.578.
    angular_bound = math.radians(8)*3.5/2
    acceleration_bound = math.radians(8)*24/4
    inertia_norm = float(np.linalg.norm(inertia, 2))
    torque_bound = inertia_norm*(acceleration_bound + angular_bound**2)
    force_bound = geometry['mass_kg'] * (9.81 + .578 + .01*24/4)
    if (torque_bound > LIMITS['torque_nm'] or force_bound > LIMITS['force_n']
            or angular_bound > LIMITS['angular_speed_rad_s']):
        raise ValueError('analytic force/torque/angular design bound exceeded')
    radius = float(np.linalg.norm(vertices-com, axis=1).max())
    collision_speed_bound = .4 + angular_bound * radius
    camera_lever = float(np.linalg.norm(camera[:3, 3]-com))
    target_com_distance = float(np.linalg.norm(world_corners - (model @ np.r_[com, 1])[:3], axis=1).max())
    point_speed_bound = .4 + angular_bound*(camera_lever + target_com_distance + .41)
    rows = []
    for step in range(25001):
        # Complete relative table; anchor waiting is stationary and appended at runtime.
        row = request(step/1000, geometry['mass_kg'], inertia)
        rotate = rotation(row['rotation_rpy_rad'])
        motion = np.eye(4)
        motion[:3, :3] = rotate
        motion[:3, 3] = com - rotate @ com + row['translation_m']
        rig_world = model @ motion
        camera_world = rig_world @ camera
        local = (world_corners - camera_world[:3, 3]) @ camera_world[:3, :3]
        depth = local[:, 0]
        uv = np.column_stack((80 - f*local[:, 1]/depth, 60 - f*local[:, 2]/depth))
        visible = ((depth >= .2) & (depth <= 19.1) & (uv[:, 0] >= 0) & (uv[:, 0] <= 160)
                   & (uv[:, 1] >= 0) & (uv[:, 1] <= 120))
        collision = vertices @ rig_world[:3, :3].T + rig_world[:3, 3]
        gap = float(center[0] - collision[:, 0].max())  # slab extends away from camera (+worldX).
        clearance = float(collision[:, 2].min())
        force, torque = float(np.linalg.norm(row['force_world_n'])), float(np.linalg.norm(row['torque_world_nm']))
        if force > LIMITS['force_n'] or torque > LIMITS['torque_nm']:
            raise ValueError('force/torque design bound exceeded')
        if np.linalg.norm(row['omega_world_rad_s']) > LIMITS['angular_speed_rad_s']:
            raise ValueError('angular speed design bound exceeded')
        if gap < LIMITS['target_clearance_m'] or clearance < 0:
            raise ValueError('collision design bound exceeded')
        if 2 <= row['relative_s'] <= 14 and (not visible.all() or clearance < .1):
            raise ValueError('excitation visibility/ground collision design incomplete')
        row.update(visible_corner_count=int(visible.sum()), corner_pixels=uv.tolist(),
                   corner_depth_m=depth.tolist(), ground_clearance_m=clearance, target_plane_gap_m=gap)
        row['per_link_force_world_n'] = {
            name: (np.asarray(row['force_world_n'])*link['mass']/geometry['mass_kg']).tolist()
            for name, link in geometry.get('links', {}).items()
        }
        rows.append(row)
    active = rows[2000:14001]
    minimum_depth = min(min(r['corner_depth_m']) for r in active)
    # Bound variation from each 1ms table point to any intervening time, using
    # point speed and the quotient derivative of pinhole projection.
    depth_error = point_speed_bound*.001
    depth_lower = minimum_depth-depth_error
    lateral_bound = target_com_distance + .41 + camera_lever
    pixel_error = f*point_speed_bound*(1/depth_lower + lateral_bound/depth_lower**2)*.001
    pixel_margin = min(min(min(u, 160-u, v, 120-v) for u, v in r['corner_pixels']) for r in active)
    ground_lower = min(r['ground_clearance_m'] for r in active)-collision_speed_bound*.001
    gap_lower = min(r['target_plane_gap_m'] for r in rows)-collision_speed_bound*.001
    if (depth_lower < .2 or max(max(r['corner_depth_m']) for r in active)+depth_error > 19.1
            or pixel_margin <= pixel_error or ground_lower < .1 or gap_lower < .1):
        raise ValueError('continuous requested geometry design bound incomplete')
    return dict(target_pose_world=[*origin.tolist(), 0, -math.pi/2, 0], limits=LIMITS,
                corner_identity=[dict(tag_id=i, layout_corner_index=j) for i in range(9) for j in range(4)],
                coefficient_model=geometry['inertia_scope'] if 'inertia_scope' in geometry else 'analytic fixture',
                schedule='anchor lift0..2; RX2..4 RY4..6 RZ6..8 TX8..10 TY10..12 TZ12..14; rest..25',
                audit=dict(rows=len(rows), step_ns=1000000, actual_continuous_dynamics_qualified=False,
                           requested_between_steps_bounds=dict(pixel_margin=pixel_margin, pixel_variation_upper=pixel_error,
                                                              depth_lower_m=depth_lower, ground_lower_m=ground_lower,
                                                              target_gap_lower_m=gap_lower, torque_upper_nm=torque_bound,
                                                              force_upper_n=force_bound, angular_speed_upper_rad_s=angular_bound,
                                                              speed_upper_m_s=.4, displacement_upper_m=.41,
                                                              tilt_upper_rad=math.radians(8)),
                           excitation_all_corners_in_image=True,
                           startup_cropped_rows=sum(r['visible_corner_count'] < 36 for r in rows[:2000]),
                           minimum_excitation_ground_clearance_m=min(r['ground_clearance_m'] for r in active),
                           minimum_target_plane_gap_m=min(r['target_plane_gap_m'] for r in rows),
                           max_force_n=max(np.linalg.norm(r['force_world_n']) for r in rows),
                           max_torque_nm=max(np.linalg.norm(r['torque_world_nm']) for r in rows)), rows=rows)


def _target_bytes(target):
    raw = (target / 'manifest.json').read_bytes()
    if sha(raw) != TARGET_MANIFEST_SHA:
        raise ValueError('sealed target manifest changed')
    files = json.loads(raw)['files']
    data = {'manifest.json': raw}
    for name, record in files.items():
        blob = (target / name).read_bytes()
        if len(blob) != record['bytes'] or sha(blob) != record['sha256']:
            raise ValueError('sealed target member changed')
        data[name] = blob
    return data


def materialize(output, *, target, model_roots, template):
    if output.exists():
        raise FileExistsError(output)
    target_data = _target_bytes(target)
    template_data = template.read_bytes()
    if sha(template_data) != TEMPLATE_SHA:
        raise ValueError('original world template changed')
    sources = {}
    for name in ('x500_base', 'x500', 'x500_benchmark', 'OakD-Benchmark'):
        matches = [root / name for root in model_roots if (root / name).is_dir()]
        if len(matches) != 1:
            raise ValueError('model root ambiguous/missing: ' + name)
        for path in sorted(matches[0].rglob('*')):
            if path.is_symlink():
                raise ValueError('unsupported source symlink')
            if path.is_file():
                sources['models/' + str(path.relative_to(matches[0].parent)).replace('\\', '/')] = path
    if len(sources) > 256 or sum(p.stat().st_size for p in sources.values()) > 64*1024**2:
        raise ValueError('static source bill exceeds declared per-bundle cap')
    pinned_models = MODEL_SDF_HASHES | MODEL_CONFIG_HASHES
    for name, expected in pinned_models.items():
        if name not in sources or sha(sources[name].read_bytes()) != expected:
            raise ValueError('pinned model source/selector changed: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    bill = {}
    try:
        for name, source in sources.items():
            data = source.read_bytes()
            if name in pinned_models and sha(data) != pinned_models[name]:
                raise ValueError('pinned model source/selector changed during snapshot: ' + name)
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if source.read_bytes() != data:
                raise ValueError('model resource changed during snapshot')
            bill[name] = dict(source=str(source), bytes=len(data), sha256=sha(data))
        for name, data in target_data.items():
            dest = output / 'models/kalibr_aprilgrid_3x3' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        world = ET.fromstring(template_data)
        node = world.find('world')
        for element in list(node):
            if element.tag == 'model' and element.get('name') != 'ground':
                node.remove(element)
        for element in node.findall('include'):
            if element.findtext('name') != 'x500_benchmark_8':
                raise ValueError('unexpected original model include')
        shutil.copyfile(template.parent / 'ground_albedo.png', output / 'ground_albedo.png')
        ET.ElementTree(world).write(output / 'geometry-input.sdf', encoding='utf8', xml_declaration=True)
        geometry = resolve_geometry(output / 'geometry-input.sdf', output / 'models')
        # Initial scene placement at nominal level contact, before any runtime:
        # the old include's .24 plus merged x500_base .24 otherwise leaves feet
        # .253m above ground. Unsupported startup settling would shift the rig
        # away from a target positioned from that airborne nominal camera pose.
        old_pose = geometry['model_pose_world']
        if any(abs(v) > 1e-12 for v in old_pose[3:]):
            raise ValueError('unsupported initial rig rotation')
        min_z = min(v[2] for v in geometry['collision_vertices_model'])
        include = node.find('include')
        include.find('pose').text = ' '.join(format(v, '.17g') for v in [old_pose[0], old_pose[1], -min_z, 0, 0, 0])
        ET.ElementTree(world).write(output / 'nominal-contact-input.sdf', encoding='utf8', xml_declaration=True)
        geometry = resolve_geometry(output / 'nominal-contact-input.sdf', output / 'models')
        geometry['initial_placement'] = dict(original_include_pose=old_pose,
                                             new_include_pose=geometry['model_pose_world'],
                                             reason='nominal level ground contact before unforced startup',
                                             actual_contact_equilibrium_qualified=False)
        frozen = design(geometry)
        included = ET.SubElement(node, 'include')
        ET.SubElement(included, 'uri').text = 'model://kalibr_aprilgrid_3x3'
        ET.SubElement(included, 'name').text = 'kalibr_aprilgrid_3x3'
        ET.SubElement(included, 'pose').text = ' '.join(format(v, '.17g') for v in frozen['target_pose_world'])
        ET.ElementTree(world).write(output / 'world.sdf', encoding='utf8', xml_declaration=True)
        with (output / 'requested-load-and-projection.jsonl').open('x', encoding='utf8', newline='\n') as stream:
            for row in frozen.pop('rows'):
                stream.write(json.dumps(row, allow_nan=False) + '\n')
        record = dict(schema='target-bearing-source-scene-v1', geometry=geometry, design=frozen,
                      source_bill=bill, template_sha256=sha(template_data), qualification=QUALIFICATION,
                      runtime_graph_frozen=False, physical_dispatch_ready=False,
                      prediction_scope='ideal requested poses, no render/actual dynamics/native corners',
                      pending=['raw graph/callback integration', 'runtime/toolchain identity/load freeze',
                               'owned physical source', 'native extraction', 'measurement solve/quality'])
        save(output / 'scene-load.json', record)
        files = {p.relative_to(output).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
                 for p in sorted(output.rglob('*')) if p.is_file()}
        save(output / 'manifest.json', dict(schema='target-bearing-source-scene-bill-v1', files=files))
        return record
    except Exception as exc:
        save(output / 'failure.json', dict(reason=repr(exc), qualification=QUALIFICATION))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, action='append', required=True)
    parser.add_argument('--template', type=Path, required=True)
    args = parser.parse_args()
    result = materialize(args.output, target=args.target, model_roots=args.model_root, template=args.template)
    print(json.dumps(dict(schema=result['schema'], audit=result['design']['audit'], qualification=QUALIFICATION)))


if __name__ == '__main__':
    main()
