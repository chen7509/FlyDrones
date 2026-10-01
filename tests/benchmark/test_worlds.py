import numpy as np
import pytest

from flydrones.benchmark.geometry import segment_box_clearance, segment_cylinder_clearance
from flydrones.benchmark.worlds import (
    X500_COLLISIONS,
    dynamic_center,
    generate_development_world,
    generate_world,
    has_route,
    vehicle_envelope_radius,
    write_sdf,
)


def test_thin_wall_crossing_is_collision():
    assert segment_box_clearance(np.array([-1., 0., 1.5]), np.array([1., 0., 1.5]),
                                 np.array([-.01, -1., 0.]), np.array([.01, 1., 3.]), .25) <= 0


def test_parallel_wall_distance_and_endpoints():
    lo, hi = np.array([0., 0., 0.]), np.array([1., 1., 1.])
    assert segment_box_clearance(np.array([-1., 2., .5]), np.array([2., 2., .5]), lo, hi, .2) == pytest.approx(.8)
    assert segment_box_clearance(np.array([-1., .5, .5]), np.array([-.5, .5, .5]), lo, hi, .2) == pytest.approx(.3)


def test_cylinder_crossing_and_cap():
    assert segment_cylinder_clearance(np.array([-1., 0., 1.]), np.array([1., 0., 1.]), (0., 0.), .2, 0., 2., .25) < 0
    assert segment_cylinder_clearance(np.array([0., 0., 3.]), np.array([0., 0., 4.]), (0., 0.), .2, 0., 2., .25) == pytest.approx(.75)


def test_seed_is_reproducible():
    assert generate_world(1701, 'forest') == generate_world(1701, 'forest')
    assert generate_world(1701, 'forest') != generate_world(1702, 'forest')


def test_enclosing_wall_has_no_route():
    world = {'bounds': [[-2., -2., 0.], [2., 2., 3.]], 'start': [-1., 0., 1.5], 'goal': [1., 0., 1.5],
             'boxes': [{'lo': [-.1, -2., 0.], 'hi': [.1, 2., 3.]}], 'cylinders': []}
    assert not has_route(world, .3)


@pytest.mark.parametrize('family', ['forest', 'corridor', 'mixed', 'disturbed'])
def test_generated_world_has_route_and_real_collision_shapes(family, tmp_path):
    world = generate_world(1703, family)
    assert has_route(world, .4)
    path = tmp_path / 'world.sdf'
    write_sdf(world, path)
    import xml.etree.ElementTree as ET
    root = ET.parse(path)
    for model in root.findall('.//world/model'):
        assert model.find('.//collision') is not None
        assert model.find('.//visual') is not None
        if model.get('name') != 'ground':
            sensor = model.find(".//sensor[@type='contact']")
            assert sensor is not None
            assert sensor.findtext('contact/topic') == '/benchmark/contacts'
            assert sensor.findtext('update_rate') == '100'


def test_unknown_family_rejected():
    with pytest.raises(ValueError):
        generate_world(1701, 'easy_secret_route')


def test_vehicle_envelope_is_computed_from_all_collision_boxes():
    radius = vehicle_envelope_radius(X500_COLLISIONS)
    assert radius == pytest.approx(.37)
    world = generate_world(1701, 'forest')
    assert world['vehicle_envelope_radius_m'] == radius
    assert has_route(world, radius)


def test_dynamic_obstacle_motion_depends_only_on_simulation_time():
    obstacle = {'center': [2., 0., 1.5], 'axis': 1, 'amplitude': 2., 'period_s': 16., 'phase': 0.}
    assert dynamic_center(obstacle, 0) == pytest.approx((2., 0., 1.5))
    assert dynamic_center(obstacle, 4_000_000_000) == pytest.approx((2., 2., 1.5))


def test_disturbed_sdf_has_movable_obstacle_and_physical_wind(tmp_path):
    world = generate_world(1703, 'disturbed')
    path = tmp_path / 'disturbed.sdf'
    write_sdf(world, path)
    import xml.etree.ElementTree as ET
    root = ET.parse(path)
    moving = root.find(".//model[@name='moving_obstacle']")
    assert moving.findtext('static') == 'false'
    assert root.find('.//world/wind/linear_velocity') is not None
    assert any('wind-effects' in plugin.get('filename', '') for plugin in root.findall('.//world/plugin'))


def test_only_three_named_development_worlds_are_available():
    single = generate_development_world(1701)
    assert single['family'] == 'development_single'
    assert len(single['cylinders']) + len(single['boxes']) == 1
    assert generate_development_world(1702)['family'] == 'corridor'
    assert generate_development_world(1703)['family'] == 'mixed'
    with pytest.raises(ValueError, match='development seed'):
        generate_development_world(1704)
