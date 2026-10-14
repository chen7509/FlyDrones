"""Producer composition fixtures; no real sensor/source authentication claims."""

import hashlib
import importlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation


def api():
    return importlib.import_module('flydrones.benchmark.px4_camera_source')


def write_json(path, value):
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def rig_files(tmp_path, **changes):
    info = {'schema': 'flydrones-camera-info-v1', 'camera_info': {
        'width': 160, 'height': 120, 'frame_id': 'camera_link',
        'intrinsics_k': [100., 0., 80., 0., 100., 60., 0., 0., 1.],
    }}
    mount = {'schema': 'flydrones-body-frd-from-camera-optical-v1',
             'body_id': 'body0', 'camera_id': 'camera_link',
             'rotation': [[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]],
             'translation_m': [.12, 0., -.002]}
    ih = write_json(tmp_path/'intrinsics.json', info)
    mh = write_json(tmp_path/'mount.json', mount)
    doc = {'schema': 'flydrones-px4-camera-rig-v1', 'body_id': 'body0',
           'camera_id': 'camera_link', 'domain': 'simulation-candidate',
           'intrinsics': {'path': 'intrinsics.json', 'sha256': ih},
           'extrinsics': {'path': 'mount.json', 'sha256': mh}}
    doc.update(changes)
    dh = write_json(tmp_path/'rig.json', doc)
    return tmp_path/'rig.json', dh, doc


def rig(tmp_path):
    path, digest, _ = rig_files(tmp_path)
    return api().CameraRigBinding.load(path, digest, body_id='body0', camera_id='camera_link')


def topics():
    pub = np.array([1_000_000, 1_050_000, 1_100_000], dtype=np.uint64)
    local = {'timestamp': pub, 'timestamp_sample': pub-10_000}
    for name, value in {'x': 1., 'y': 2., 'z': -3., 'vx': .1, 'vy': .2, 'vz': -.3}.items():
        local[name] = np.full(3, value)
    for name in ('xy_valid', 'z_valid', 'v_xy_valid', 'v_z_valid', 'heading_good_for_control'):
        local[name] = np.ones(3, dtype=np.uint8)
    local['dead_reckoning'] = np.zeros(3, dtype=np.uint8)
    for name in ('xy_reset_counter', 'z_reset_counter', 'vxy_reset_counter', 'vz_reset_counter',
                 'heading_reset_counter'):
        local[name] = np.zeros(3, dtype=np.uint8)
    attitude = {'timestamp': pub, 'timestamp_sample': pub-10_000,
                'quat_reset_counter': np.zeros(3, dtype=np.uint8)}
    for i, v in enumerate((1., 0., 0., 0.)):
        attitude[f'q[{i}]'] = np.full(3, v)
    return {'vehicle_local_position': local, 'vehicle_attitude': attitude,
            'estimator_status': {'timestamp': pub, 'filter_fault_flags': np.zeros(3, dtype=np.uint32)},
            'estimator_status_flags': {'timestamp': pub, 'cs_gnss_pos': np.ones(3, dtype=np.uint8),
                                       'cs_ev_pos': np.zeros(3, dtype=np.uint8)}}


def produce(producer, frames):
    # A fixture caller declaration binds these inputs; it is never a measured clock calibration.
    declaration = {'schema': 'flydrones-camera-px4-epoch-declaration-v1',
                   'relation': 'same-px4-boot-epoch', 'rig_sha256': producer.binding.sha256,
                   'ulog_sha256': producer.ulog_sha256,
                   'frame_sequence_sha256': hashlib.sha256(
                       json.dumps(frames, separators=(',', ':')).encode('ascii')).hexdigest()}
    return producer.produce(frames, epoch_declaration=declaration)


def test_bound_rig_and_state_produce_actual_optical_pose_without_grants(tmp_path):
    binding = rig(tmp_path)
    result = produce(api().Px4UlogCameraSource.from_decoded_topics(topics(), binding), [1_000_000_000])
    row = result['records'][0]
    assert row['geometry']['camera_pose_enu_xyzw'][:3] == pytest.approx((2., 1.12, 3.002))
    q = row['geometry']['camera_pose_enu_xyzw'][3:]
    assert Rotation.from_quat(q).apply([0., 0., 1.]) == pytest.approx((0., 1., 0.))
    assert row['geometry']['velocity_enu_m_s'] == pytest.approx((.2, .1, .3))
    assert result['ulog_sha256'] is None
    assert row['rig_sha256'] == binding.sha256
    assert result['live_source_authenticated'] is result['camera_calibration_qualified'] is False
    assert result['clock_epoch_qualified'] is result['training_eligible'] is result['flight_eligible'] is False


def test_noncommuting_body_camera_rotation_and_lever_arm(tmp_path):
    source = topics()
    r = Rotation.from_euler('zyx', [.7, -.4, .3])
    xyzw = r.as_quat()
    for i, value in enumerate((xyzw[3], *xyzw[:3])):
        source['vehicle_attitude'][f'q[{i}]'][:] = value
    result = produce(api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path)), [1_000_000_000])
    pose = result['records'][0]['geometry']['camera_pose_enu_xyzw']
    expected = r.apply([.12, 0., -.002]) + [1., 2., -3.]
    assert pose[:3] == pytest.approx([expected[1], expected[0], -expected[2]])
    forward_ned = r.apply([1., 0., 0.])
    assert Rotation.from_quat(pose[3:]).apply([0., 0., 1.]) == pytest.approx(
        [forward_ned[1], forward_ned[0], -forward_ned[2]])


@pytest.mark.parametrize('field', ['heading_good_for_control', 'v_xy_valid', 'v_z_valid'])
def test_unhealthy_px4_does_not_produce_usable_pose(tmp_path, field):
    source = topics()
    source['vehicle_local_position'][field][:] = 0
    result = produce(api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path)), [1_000_000_000])
    assert result['records'][0]['geometry'] is None
    assert result['records'][0]['reasons']


def test_reset_transition_stays_refused_after_stable_counter(tmp_path):
    source = topics()
    source['vehicle_local_position']['xy_reset_counter'][:] = [255, 0, 0]
    rows = produce(api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path)),
        [1_000_000_000, 1_050_000_000, 1_100_000_000])['records']
    assert rows[0]['geometry'] is not None
    assert all(row['geometry'] is None and 'reset_epoch_unresolved' in row['reasons'] for row in rows[1:])


def test_future_and_stale_state_never_produce_pose(tmp_path):
    rows = produce(api().Px4UlogCameraSource.from_decoded_topics(topics(), rig(tmp_path)),
        [900_000_000, 1_250_000_000])['records']
    assert all(row['geometry'] is None for row in rows)
    assert any('missing' in reason for reason in rows[0]['reasons'])
    assert any('stale' in reason for reason in rows[1]['reasons'])


def test_rig_rejects_changed_evidence_and_wrong_device(tmp_path):
    path, digest, _ = rig_files(tmp_path)
    with pytest.raises(ValueError):
        api().CameraRigBinding.load(path, digest, body_id='another-body', camera_id='camera_link')
    (tmp_path/'mount.json').write_text('{}')
    with pytest.raises(ValueError):
        api().CameraRigBinding.load(path, digest, body_id='body0', camera_id='camera_link')


def test_reflection_and_escaping_mount_refused(tmp_path):
    path, digest, doc = rig_files(tmp_path)
    mount = json.loads((tmp_path/'mount.json').read_text())
    mount['rotation'] = [[-1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
    doc['extrinsics']['sha256'] = write_json(tmp_path/'mount.json', mount)
    digest = write_json(path, doc)
    with pytest.raises(ValueError):
        api().CameraRigBinding.load(path, digest, body_id='body0', camera_id='camera_link')
    doc['extrinsics']['path'] = '../outside.json'
    digest = write_json(path, doc)
    with pytest.raises(ValueError):
        api().CameraRigBinding.load(path, digest, body_id='body0', camera_id='camera_link')


def test_source_columns_are_snapshotted_and_missing_reset_refused(tmp_path):
    source = topics()
    producer = api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path))
    source['vehicle_local_position']['x'][:] = 999.
    assert produce(producer, [1_000_000_000])['records'][0]['geometry']['position_enu_m'] == [2.,1.,3.]
    del source['vehicle_attitude']['quat_reset_counter']
    with pytest.raises(ValueError):
        produce(api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path)), [1_000_000_000])


def test_bound_ulog_refuses_hash_before_parser_or_receipt_invention(tmp_path):
    path = tmp_path/'source.ulg'
    path.write_bytes(b'not a ULog')
    with pytest.raises(ValueError, match='SHA'):
        api().Px4UlogCameraSource.from_ulog(path, 'a'*64, rig(tmp_path))


def test_missing_epoch_declaration_is_explicit_refusal(tmp_path):
    row = api().Px4UlogCameraSource.from_decoded_topics(topics(), rig(tmp_path)).produce(
        [1_000_000_000])['records'][0]
    assert row['geometry'] is None
    assert 'camera_px4_epoch_unbound' in row['reasons']


def test_each_row_preserves_source_rig_evidence_and_all_selected_topic_indices(tmp_path):
    producer = api().Px4UlogCameraSource.from_decoded_topics(topics(), rig(tmp_path))
    row = producer.produce([1_000_000_000])['records'][0]
    assert row['source_identity']['ulog_sha256'] is None
    assert row['source_identity']['rig_sha256'] == producer.binding.sha256
    assert row['source_identity']['rig_evidence_sha256'] == dict(producer.binding.evidence_sha256)
    assert set(row['source_rows']) == set(topics())
    assert all(value['index'] == 0 and value['publication_us'] == 1_000_000
               for value in row['source_rows'].values())


def test_real_file_parser_boundary_selects_instance_zero_not_other_instances(tmp_path, monkeypatch):
    path = tmp_path/'parser-boundary.ulg'
    raw = b'constructed parser-boundary fixture; not a real ULog'
    path.write_bytes(raw)
    decoded = topics()
    datasets = [SimpleNamespace(name=name, multi_id=i, data=decoded[name])
                for name in decoded for i in (0, 1)]
    monkeypatch.setitem(sys.modules, 'pyulog', SimpleNamespace(ULog=lambda *_args, **_kwargs:
                                                           SimpleNamespace(data_list=datasets)))
    monkeypatch.setattr(api(), 'version', lambda _name: '1.2.4')
    source = api().Px4UlogCameraSource.from_ulog(path, hashlib.sha256(raw).hexdigest(), rig(tmp_path))
    assert source.ulog_sha256 == hashlib.sha256(raw).hexdigest()


def test_decoded_source_refuses_nonnumeric_columns_before_copy(tmp_path):
    source = topics()
    source['vehicle_local_position']['unexpected_text'] = np.array(['x', 'y', 'z'])
    with pytest.raises(ValueError):
        api().Px4UlogCameraSource.from_decoded_topics(source, rig(tmp_path))
