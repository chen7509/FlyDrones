"""Raw dataset producer behavior; constructed IMU, not live qualification."""

import hashlib
import importlib
import json
import struct
import sys
import zlib
from types import SimpleNamespace

import numpy as np
import pytest


def api():
    return importlib.import_module('flydrones.benchmark.camera_imu_dataset')


def columns():
    d = {'timestamp': np.array([1000000, 1004000, 1008000], dtype=np.uint64)}
    for name in ('gyro_rad', 'accelerometer_m_s2'):
        for i in range(3):
            d[f'{name}[{i}]'] = np.array([i+.25, i+.5, i+.75], dtype=np.float32)
    for name in ('gyro_integral_dt', 'accelerometer_integral_dt'):
        d[name] = np.full(3, 4000, dtype=np.uint32)
    for name in ('gyro_clipping', 'accelerometer_clipping', 'gyro_calibration_count', 'accel_calibration_count'):
        d[name] = np.zeros(3, dtype=np.uint8)
    d['accelerometer_timestamp_relative'] = np.zeros(3, dtype=np.int32)
    return d


def test_actual_lossless_rgb_png_encoder():
    rgb = bytes(i % 256 for i in range(160*120*3))
    png = api().rgb_png(rgb, 160, 120)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    pos, compressed = 8, b''
    while pos < len(png):
        size = struct.unpack('>I', png[pos:pos+4])[0]
        name = png[pos+4:pos+8]
        data = png[pos+8:pos+8+size]
        assert struct.unpack('>I', png[pos+8+size:pos+12+size])[0] == zlib.crc32(name+data)
        if name == b'IDAT':
            compressed += data
        pos += size+12
    decoded = zlib.decompress(compressed)
    assert all(decoded[n*481] == 0 for n in range(120))
    assert b''.join(decoded[n*481+1:(n+1)*481] for n in range(120)) == rgb


def test_raw_distinct_accel_stamp_not_synchronized_or_shifted():
    d = columns()
    d['accelerometer_timestamp_relative'][1] = -400
    rows = list(api().imu_records(d))
    assert rows[1]['gyro_sample_ns'] == 1004000000
    assert rows[1]['accel_sample_ns'] == 1003600000
    assert 'gyro_accel_sample_times_differ' in rows[1]['reasons']
    assert rows[1]['raw']['accelerometer_timestamp_relative'] == -400
    assert rows[1]['raw']['gyro_integral_dt'] == 4000
    assert rows[1]['host_receipt_ns'] is None
    assert not rows[1]['training_eligible']


def test_sentinel_clipping_and_calibration_wrap_remain_in_raw_rows():
    d = columns()
    d['accelerometer_timestamp_relative'][0] = 2147483647
    d['gyro_clipping'][0] = 1
    d['gyro_calibration_count'][:] = [255, 0, 0]
    rows = list(api().imu_records(d))
    assert rows[0]['accel_sample_ns'] is None
    assert {'accel_relative_timestamp_invalid', 'gyro_clipping'} <= set(rows[0]['reasons'])
    assert 'imu_calibration_epoch_unresolved' in rows[1]['reasons']
    assert 'imu_calibration_epoch_unresolved' in rows[2]['reasons']
    assert rows[2]['raw']['gyro_calibration_count'] == 0


def capture_inputs(tmp_path):
    root = tmp_path/'capture'
    root.mkdir()
    (root/'rgb-frames').mkdir()
    raw = b'P6\n160 120\n255\n'+bytes([12, 45, 78])*(160*120)
    file = root/'rgb-frames/1000000000.ppm'
    file.write_bytes(raw)
    manifest = {'schema': 'flydrones-rgb-capture-v1', 'out_of_order_drops': 0, 'frames': [{
        'frame_ns': 1000000000, 'path': 'rgb-frames/1000000000.ppm', 'width': 160, 'height': 120,
        'sha256': hashlib.sha256(raw).hexdigest()}]}
    mp = root/'rgb-capture-manifest.json'
    mp.write_text(json.dumps(manifest))
    from test_px4_camera_source import rig
    binding = rig(tmp_path)
    output = tmp_path/'output'
    output.mkdir()
    return output, mp, hashlib.sha256(mp.read_bytes()).hexdigest(), binding


def epoch(binding, ulog_sha=None):
    return {'schema': 'flydrones-camera-px4-epoch-declaration-v1',
            'relation': 'same-px4-boot-epoch', 'rig_sha256': binding.sha256, 'ulog_sha256': ulog_sha,
            'frame_sequence_sha256': hashlib.sha256(b'[1000000000]').hexdigest()}


def test_stream_export_produces_pixels_csv_and_all_raw_rows(tmp_path):
    output, mp, digest, binding = capture_inputs(tmp_path)
    result = api().write_dataset(output, mp, hashlib.sha256(mp.read_bytes()).hexdigest(), binding, columns())
    assert (output/'cam0/data/1000000000.png').read_bytes().startswith(b'\x89PNG')
    assert len((output/'cam0/data.csv').read_text().splitlines()) == 2
    assert len((output/'imu-source.jsonl').read_text().splitlines()) == 3
    assert not (output/'imu0/data.csv').exists()  # no caller epoch declaration
    assert result['imu_rows'] == 3 and not result['candidate_imu_csv_emitted']
    assert not result['clock_epoch_qualified'] and not result['camera_calibration_qualified']


def fixture_bound(tmp_path, monkeypatch, data):
    # Parser-boundary fixture only. Real pyulog parsing is a separate WSL run.
    file = tmp_path/'fixture.ulg'
    file.write_bytes(b'parser fixture bytes, not a real ULog')
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    monkeypatch.setattr(api(), 'version', lambda name: '1.2.4')
    monkeypatch.setitem(sys.modules, 'pyulog', SimpleNamespace(ULog=lambda *a, **kw: SimpleNamespace(
        data_list=[SimpleNamespace(name='sensor_combined', multi_id=0, data=data)])))
    return api().load_imu(file, digest), digest


def test_exact_csv_preserves_all_equal_sample_rows_but_not_qualification(tmp_path, monkeypatch):
    output, mp, digest, binding = capture_inputs(tmp_path)
    data, source_sha = fixture_bound(tmp_path, monkeypatch, columns())
    result = api().write_dataset(output, mp, digest, binding, data, epoch=epoch(binding, source_sha))
    csv = (output/'imu0/data.csv').read_text().splitlines()
    assert len(csv) == 4
    assert csv[1].split(',') == ['1000000000', '0.25', '1.25', '2.25', '0.25', '1.25', '2.25']
    assert csv[-1].startswith('1008000000,')
    assert result['candidate_imu_csv_emitted'] and not result['training_eligible']
    assert not result['consumer_executed']


def test_any_invalid_row_withholds_whole_imu_csv_and_keeps_failure(tmp_path, monkeypatch):
    output, mp, digest, binding = capture_inputs(tmp_path)
    data = columns()
    data['gyro_integral_dt'][1] = 0
    source, source_sha = fixture_bound(tmp_path, monkeypatch, data)
    result = api().write_dataset(output, mp, digest, binding, source, epoch=epoch(binding, source_sha))
    rows = [json.loads(s) for s in (output/'imu-source.jsonl').read_text().splitlines()]
    assert len(rows) == 3 and rows[1]['raw']['gyro_integral_dt'] == 0
    assert not (output/'imu0/data.csv').exists()
    assert not result['candidate_imu_csv_emitted'] and result['imu_structurally_refused_rows'] == 1


def test_nonfinite_original_value_is_preserved_without_json_nan():
    d = columns()
    d['gyro_rad[1]'][1] = np.nan
    rows = list(api().imu_records(d))
    assert 'gyro_nonfinite' in rows[1]['reasons']
    assert rows[1]['raw']['gyro_rad[1]'] == {'nonfinite': 'nan'}
    json.dumps(rows, allow_nan=False)


def test_unbound_columns_never_emit_candidate_csv_even_with_null_epoch(tmp_path):
    output, mp, digest, binding = capture_inputs(tmp_path)
    result = api().write_dataset(output, mp, digest, binding, columns(), epoch=epoch(binding))
    assert not result['candidate_imu_csv_emitted']
    assert not (output/'imu0/data.csv').exists()


def test_supplied_sha_label_cannot_make_columns_byte_bound(tmp_path):
    output, mp, digest, binding = capture_inputs(tmp_path)
    declaration = epoch(binding)
    declaration['ulog_sha256'] = 'a'*64
    with pytest.raises(ValueError, match='byte reader'):
        api().write_dataset(output, mp, digest, binding, columns(), ulog_sha='a'*64, epoch=declaration)
