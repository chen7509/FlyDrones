"""Private procedural world generation; no routes are returned to controllers."""

import xml.etree.ElementTree as ET
from collections import deque
from itertools import product
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from .geometry import point_clearances


# Every collision box in pinned PX4 x500_base plus the benchmark RGB-D body.
# Poses are expressed in the x500 model frame after applying x500_base's
# +0.24 m nested-model pose. The source SDF hashes are frozen with the run.
X500_COLLISIONS = (
    {'name': 'base_link_collision_0', 'pose': (0., 0., .247, 0., 0., 0.),
     'size': (.35355339059327373, .35355339059327373, .05)},
    {'name': 'base_link_collision_1', 'pose': (0., -.098, .117, -.35, 0., 0.),
     'size': (.015, .015, .21)},
    {'name': 'base_link_collision_2', 'pose': (0., .098, .117, .35, 0., 0.),
     'size': (.015, .015, .21)},
    {'name': 'base_link_collision_3', 'pose': (0., -.132, .0205, 0., 0., 0.),
     'size': (.25, .015, .015)},
    {'name': 'base_link_collision_4', 'pose': (0., .132, .0205, 0., 0., 0.),
     'size': (.25, .015, .015)},
    {'name': 'benchmark_rgbd_body', 'pose': (.12, 0., .242, 0., 0., 0.),
     'size': (.0175, .091, .028)},
)


def vehicle_envelope_radius(collisions) -> float:
    """Smallest origin-centred sphere covering the supplied box collisions.

    The exact maximum is rounded upward to the next centimetre so numeric and
    SDF parser differences cannot make route validation optimistic.
    """
    maximum = 0.0
    for collision in collisions:
        pose = np.asarray(collision['pose'], dtype=float)
        half_size = np.asarray(collision['size'], dtype=float) / 2.0
        rotation = Rotation.from_euler('xyz', pose[3:]).as_matrix()
        for signs in product((-1., 1.), repeat=3):
            corner = pose[:3] + rotation @ (half_size * np.asarray(signs))
            maximum = max(maximum, float(np.linalg.norm(corner)))
    return math.ceil((maximum - 1e-12) * 100.0) / 100.0


def dynamic_center(obstacle: dict, sim_ns: int) -> tuple[float, float, float]:
    """Return the obstacle centre from simulation time, never wall time."""
    center = np.asarray(obstacle['center'], dtype=float).copy()
    phase = float(obstacle.get('phase', 0.))
    angle = 2 * np.pi * (sim_ns / 1_000_000_000) / float(obstacle['period_s']) + phase
    center[int(obstacle['axis'])] += float(obstacle['amplitude']) * np.sin(angle)
    return tuple(float(value) for value in center)


def generate_development_world(seed: int) -> dict:
    """Return one of the three public integration worlds, never a formal world."""
    if seed == 1701:
        envelope = vehicle_envelope_radius(X500_COLLISIONS)
        world = {
            'seed': 1701,
            'family': 'development_single',
            'candidate': 0,
            'rejected_candidates': [],
            'bounds': [[-12., -8., .1], [12., 8., 4.9]],
            'start': [-8., 0., 1.5],
            'goal': [8., 0., 1.5],
            'vehicle_envelope_radius_m': envelope,
            'boxes': [],
            'cylinders': [{'center': [0., 0.], 'radius': .8, 'zlo': 0., 'zhi': 4.5}],
            'dynamic': [],
            'wind': [0., 0., 0.],
        }
        if not has_route(world, envelope):
            raise RuntimeError('fixed single-obstacle development world is not passable')
        return world
    if seed == 1702:
        return generate_world(seed, 'corridor')
    if seed == 1703:
        return generate_world(seed, 'mixed')
    raise ValueError(f'unknown development seed: {seed}')


def has_route(world: dict, radius: float) -> bool:
    lo, hi = np.asarray(world['bounds'], dtype=float)
    endpoints = np.array([world['start'], world['goal']], dtype=float)
    if np.any(endpoints < lo + radius) or np.any(endpoints > hi - radius):
        return False
    if np.any(point_clearances(endpoints, world) <= radius):
        return False
    step = .2
    axes = [np.arange(l + radius, h - radius + 1e-9, step) for l, h in zip(lo, hi)]
    if any(len(axis) == 0 for axis in axes):
        return False
    points = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1)
    # Clearance is 1-Lipschitz. This margin covers endpoints-to-grid and all
    # six-neighbour edges; a grid route therefore cannot tunnel through a wall.
    free = point_clearances(points, world) > radius + np.sqrt(3) * step
    start, goal = [tuple(int(np.argmin(abs(axis - p[j]))) for j, axis in enumerate(axes)) for p in endpoints]
    if not free[start] or not free[goal]:
        return False
    queue = deque([start])
    visited = np.zeros_like(free)
    visited[start] = True
    shape = free.shape
    while queue:
        current = queue.popleft()
        if current == goal:
            return True
        for axis in range(3):
            for delta in (-1, 1):
                nxt = list(current)
                nxt[axis] += delta
                nxt = tuple(nxt)
                if 0 <= nxt[axis] < shape[axis] and free[nxt] and not visited[nxt]:
                    visited[nxt] = True
                    queue.append(nxt)
    return False


def generate_world(seed: int, family: str) -> dict:
    if family not in {'forest', 'corridor', 'mixed', 'disturbed'}:
        raise ValueError(f'unknown family: {family}')
    rejected = []
    for attempt in range(100):
        rng = np.random.default_rng(np.random.SeedSequence([seed, attempt]))
        envelope = vehicle_envelope_radius(X500_COLLISIONS)
        world = {'seed': int(seed), 'family': family, 'candidate': attempt, 'rejected_candidates': list(rejected),
                 'bounds': [[-12., -8., .1], [12., 8., 4.9]], 'start': [-8., 0., 1.5], 'goal': [8., 0., 1.5],
                 'vehicle_envelope_radius_m': envelope,
                 'boxes': [], 'cylinders': [], 'dynamic': [], 'wind': [0., 0., 0.]}
        if family != 'corridor':
            for _ in range(35 if family == 'forest' else 18):
                xy = rng.uniform([-6., -6.], [6., 6.])
                world['cylinders'].append({'center': xy.tolist(), 'radius': float(rng.uniform(.18, .4)),
                                           'zlo': 0., 'zhi': float(rng.uniform(2.5, 4.8))})
        if family != 'forest':
            for x in (-4., 0., 4.):
                gap = float(rng.uniform(-2., 2.))
                half = float(rng.uniform(1.1, 1.6))
                world['boxes'].extend([{'lo': [x - .18, -7., 0.], 'hi': [x + .18, gap - half, 4.5]},
                                       {'lo': [x - .18, gap + half, 0.], 'hi': [x + .18, 7., 4.5]}])
        if family == 'disturbed':
            world['dynamic'] = [{'name': 'moving_obstacle', 'center': [2., 0., 1.5], 'size': [.4, .4, 1.],
                                 'axis': 1, 'amplitude': 2., 'period_s': 16., 'phase': float(rng.uniform(0, 2*np.pi))}]
            world['wind'] = [float(rng.uniform(-.5, .5)), float(rng.uniform(-.5, .5)), 0.]
        if has_route(world, envelope):
            return world
        rejected.append(attempt)
    raise ValueError(f'no valid static route for seed {seed}, rejected candidates {rejected}')


def write_sdf(world: dict, path: Path) -> None:
    sdf = ET.Element('sdf', version='1.9')
    node = ET.SubElement(sdf, 'world', name='fly_ego_benchmark')
    physics = ET.SubElement(node, 'physics', name='fixed', type='ignored')
    ET.SubElement(physics, 'max_step_size').text = '0.001'
    ET.SubElement(physics, 'real_time_factor').text = '1.0'
    for filename, name in [('gz-sim-physics-system', 'Physics'), ('gz-sim-user-commands-system', 'UserCommands'),
                           ('gz-sim-scene-broadcaster-system', 'SceneBroadcaster'), ('gz-sim-sensors-system', 'Sensors'),
                           ('gz-sim-imu-system', 'Imu'), ('gz-sim-navsat-system', 'NavSat'),
                           ('gz-sim-air-pressure-system', 'AirPressure'), ('gz-sim-magnetometer-system', 'Magnetometer'),
                           ('gz-sim-contact-system', 'Contact')]:
        plugin = ET.SubElement(node, 'plugin', filename=filename, name=f'gz::sim::systems::{name}')
        if name == 'Sensors':
            ET.SubElement(plugin, 'render_engine').text = 'ogre2'
    if np.linalg.norm(world.get('wind', (0., 0., 0.))) > 0:
        wind_plugin = ET.SubElement(node, 'plugin', filename='gz-sim-wind-effects-system',
                                    name='gz::sim::systems::WindEffects')
        ET.SubElement(wind_plugin, 'force_approximation_scaling_factor').text = '1'
        wind = ET.SubElement(node, 'wind')
        ET.SubElement(wind, 'linear_velocity').text = ' '.join(map(str, world['wind']))
    ET.SubElement(node, 'gravity').text = '0 0 -9.81'
    spherical = ET.SubElement(node, 'spherical_coordinates')
    for tag, text in [('surface_model', 'EARTH_WGS84'), ('world_frame_orientation', 'ENU'),
                      ('latitude_deg', '47.397742'), ('longitude_deg', '8.545594'), ('elevation', '488'), ('heading_deg', '0')]:
        ET.SubElement(spherical, tag).text = text
    light = ET.SubElement(node, 'light', name='sun', type='directional')
    ET.SubElement(light, 'pose').text = '0 0 10 0 0 0'
    ET.SubElement(light, 'diffuse').text = '.8 .8 .8 1'
    ET.SubElement(light, 'direction').text = '-.5 .1 -1'

    def shape(name, pose, kind, dimensions, colour, *, static=True, contact_sensor=True):
        model = ET.SubElement(node, 'model', name=name)
        ET.SubElement(model, 'static').text = str(static).lower()
        ET.SubElement(model, 'pose').text = ' '.join(map(str, [*pose, 0, 0, 0]))
        link = ET.SubElement(model, 'link', name='body')
        if not static:
            ET.SubElement(link, 'gravity').text = 'false'
            ET.SubElement(link, 'kinematic').text = 'true'
        for role in ('collision', 'visual'):
            obj = ET.SubElement(link, role, name=role)
            geom = ET.SubElement(ET.SubElement(obj, 'geometry'), kind)
            for key, value in dimensions.items():
                ET.SubElement(geom, key).text = value
            if role == 'visual':
                material = ET.SubElement(obj, 'material')
                ET.SubElement(material, 'ambient').text = colour
                ET.SubElement(material, 'diffuse').text = colour
        if contact_sensor:
            sensor = ET.SubElement(link, 'sensor', name='benchmark_contact', type='contact')
            contact = ET.SubElement(sensor, 'contact')
            ET.SubElement(contact, 'collision').text = 'collision'
            ET.SubElement(contact, 'topic').text = '/benchmark/contacts'
            ET.SubElement(sensor, 'always_on').text = '1'
            ET.SubElement(sensor, 'update_rate').text = '100'

    shape('ground', [0, 0, -.1], 'box', {'size': '100 100 .2'}, '.45 .5 .35 1', contact_sensor=False)
    for index, box in enumerate(world['boxes']):
        lo, hi = np.array(box['lo']), np.array(box['hi'])
        shape(f'wall_{index}', (lo + hi) / 2, 'box', {'size': ' '.join(map(str, hi - lo))}, '.6 .55 .5 1')
    for index, tree in enumerate(world['cylinders']):
        shape(f'tree_{index}', [*tree['center'], (tree['zlo'] + tree['zhi']) / 2], 'cylinder',
              {'radius': str(tree['radius']), 'length': str(tree['zhi'] - tree['zlo'])}, '.25 .15 .07 1')
    for obj in world.get('dynamic', []):
        shape(obj['name'], obj['center'], 'box', {'size': ' '.join(map(str, obj['size']))}, '.9 .2 .1 1', static=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(sdf)
    ET.ElementTree(sdf).write(path, encoding='utf-8', xml_declaration=True)
