"""Development analytic and materialization behavior; no sensor/physics qualification."""

import importlib
import json
from pathlib import Path

import numpy as np
import pytest


def api():
    return importlib.import_module('tools.benchmark.calibration_capture_scene')


def test_parallel_axis_and_rotated_inertial_frame():
    m = api()
    r = m.rotation([0, 0, np.pi / 2])
    links = [dict(name='a', mass=2, com=[-1, 0, 0], inertia=np.diag([1, 2, 3]).tolist()),
             dict(name='b', mass=2, com=[1, 0, 0], inertia=(r @ np.diag([1, 2, 3]) @ r.T).tolist())]
    result = m.aggregate(links)
    assert result['mass_kg'] == 4
    assert result['com_model_m'] == [0, 0, 0]
    assert np.allclose(result['inertia_com_model_kg_m2'], np.diag([3, 7, 10]))


def test_complete_pulse_and_latest_anchor_fit_original_25_seconds():
    m = api()
    inertia = np.diag([.03, .04, .05])
    for axis in range(3):
        for at in (2 + axis * 2, 4 + axis * 2):
            row = m.request(at, 2.1, inertia)
            assert np.allclose(row['omega_world_rad_s'], [0, 0, 0])
            assert np.allclose(row['torque_world_nm'], [0, 0, 0])
    middle = m.request(3, 2.1, inertia)
    assert middle['rotation_rpy_rad'][0] == pytest.approx(np.deg2rad(8))
    assert middle['torque_world_nm'][0] == pytest.approx(.03 * np.deg2rad(8) * -6)
    assert np.allclose(m.request(9, 2.1, inertia)['translation_m'], [.01, 0, .4])
    assert np.allclose(m.request(14, 2.1, inertia)['translation_m'], [0, 0, .4])
    assert m.LIMITS['latest_anchor_s'] + m.LIMITS['program_end_s'] < 25


def test_load_rejects_incomplete_merged_design():
    m = api()
    # No real SDK here: a deliberately unsafe analytic geometry fixture.
    geometry = dict(mass_kg=2.1, com_model_m=[0, 0, 0], inertia_com_model_kg_m2=np.eye(3).tolist(),
                    model_pose_world=[0, 0, 0, 0, 0, 0], camera_pose_model=[.12, 0, .242, 0, 0, 0],
                    collision_vertices_model=[[.9, 0, 0]], camera=dict(width=160, height=120, hfov=1.274, near=.2, far=19.1))
    with pytest.raises(ValueError, match='collision|torque'):
        m.design(geometry)


def test_pulse_analytic_extrema_and_nonzero_cross_axis_inertia():
    m = api()
    coefficients = [-1920, 3840, -2304, 384, 0]
    critical = np.roots(np.polyder(coefficients))
    values = [m.pulse(float(x.real))[2] for x in critical if abs(x.imag) < 1e-10 and 0 <= x.real <= 1]
    assert max(abs(v) for v in values) <= 24 + 1e-10
    tensor = np.array([[.03, 0, .002], [0, .04, 0], [.002, 0, .05]])
    row = m.request(3, 2.1, tensor)
    expected = m.rotation(row['rotation_rpy_rad']) @ tensor @ m.rotation(row['rotation_rpy_rad']).T
    assert np.allclose(row['torque_world_nm'], expected @ [-6*np.deg2rad(8), 0, 0])
    assert abs(row['torque_world_nm'][2]) > 0  # full tensor, not diagonal-only scaling


def test_design_refuses_floating_nominal_start_before_unforced_readiness():
    m = api()
    geometry = dict(mass_kg=2.1, com_model_m=[.0034, 0, .24187], inertia_com_model_kg_m2=np.diag([.024, .025, .045]).tolist(),
                    model_pose_world=[0, 0, .24, 0, 0, 0], camera_pose_model=[.12, 0, .242, 0, 0, 0],
                    collision_vertices_model=[[.3, .3, .2], [0, 0, .013]],
                    camera=dict(width=160, height=120, hfov=1.274, near=.2, far=19.1))
    with pytest.raises(ValueError, match='initial ground contact'):
        m.design(geometry)


def test_target_identity_failure_precedes_output_creation(tmp_path):
    m = api()
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'manifest.json').write_text('{}')
    out = tmp_path / 'out'
    with pytest.raises(ValueError, match='target'):
        m.materialize(out, target=target, model_roots=[], template=Path('missing'))
    assert not out.exists()


def test_model_config_cannot_redirect_pinned_sdf_before_output(tmp_path, monkeypatch):
    m = api()
    root = tmp_path / 'models'
    pins = {}
    for name in ('x500_base', 'x500', 'x500_benchmark', 'OakD-Benchmark'):
        folder = root / name
        folder.mkdir(parents=True)
        data = b'<sdf version="1.9"><model name="fixture"/></sdf>'
        (folder / 'model.sdf').write_bytes(data)
        (folder / 'model.config').write_text('<model><sdf version="1.9">alternate.sdf</sdf></model>')
        (folder / 'alternate.sdf').write_bytes(data)
        pins[f'models/{name}/model.sdf'] = m.sha(data)
    monkeypatch.setattr(m, 'MODEL_SDF_HASHES', pins)
    monkeypatch.setattr(m, '_target_bytes', lambda _: {})
    # Fixture bypasses only sealed target to isolate the production selector gate;
    # no fake parser return can masquerade as a Linux/native result.
    monkeypatch.setattr(m, 'resolve_geometry', lambda *_: pytest.fail('parser invoked on redirected model.config'))
    template = tmp_path / 'template.sdf'
    template.write_bytes(b'<sdf version="1.9"><world name="fixture"/></sdf>')
    (tmp_path / 'ground_albedo.png').write_bytes(b'fixture')
    monkeypatch.setattr(m, 'TEMPLATE_SHA', m.sha(template.read_bytes()))
    with pytest.raises(ValueError, match='model.config'):
        m.materialize(tmp_path / 'out', target=tmp_path, model_roots=[root], template=template)
    assert not (tmp_path / 'out').exists()


def test_materializer_real_sdformat_includes(tmp_path):
    pytest.importorskip('sdformat14', reason='installed Linux SDK only; Windows is not semantic verification')
    m = api()
    root = Path(__file__).resolve().parents[2]
    px4 = Path.home() / 'PX4-Autopilot/Tools/simulation/gz/models'
    out = tmp_path / 'scene'
    result = m.materialize(out, target=root / 'results/aprilgrid-production-research-dev-1701/actual-target-v2',
                           model_roots=[root / 'assets/gazebo/models', px4],
                           template=root / 'results/openvins-board-pattern-dev-1701/episode-v2/world.sdf')
    assert result['geometry']['mass_kg'] == pytest.approx(2.1253076923076923)
    assert result['geometry']['camera_pose_model'][2] == pytest.approx(.242)
    # The explicit world include pose supersedes outer model raw pose; nested merge
    # of x500_base still contributes its own .24. This is resolved by libsdformat.
    assert result['geometry']['links']['base_link']['pose_model'][2] == pytest.approx(.24)
    assert result['design']['audit']['rows'] == 25001
    assert result['design']['audit']['excitation_all_corners_in_image'] is True
    assert result['qualification']['measured_calibration'] is False
    assert (out / 'world.sdf').exists()
    assert len(json.loads((out / 'manifest.json').read_text())['files']) > 20
    with pytest.raises(FileExistsError):
        m.materialize(out, target=root / 'results/aprilgrid-production-research-dev-1701/actual-target-v2',
                      model_roots=[root / 'assets/gazebo/models', px4],
                      template=root / 'results/openvins-board-pattern-dev-1701/episode-v2/world.sdf')
