"""Recorded calibration-input production; no estimator or live authority."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import struct
import zlib
from collections import Counter
from importlib.metadata import version
from io import BytesIO

import numpy as np

from .px4_camera_source import MAX_COLUMN_BYTES, MAX_ULOG, _bound_bytes, _unique

FLAGS = {name: False for name in ('live_source_authenticated', 'clock_epoch_qualified',
                                 'camera_calibration_qualified', 'training_eligible', 'flight_eligible')}
FIELDS = ('timestamp', 'accelerometer_timestamp_relative', 'gyro_integral_dt',
          'accelerometer_integral_dt', 'gyro_clipping', 'accelerometer_clipping',
          'gyro_calibration_count', 'accel_calibration_count',
          *(f'gyro_rad[{i}]' for i in range(3)), *(f'accelerometer_m_s2[{i}]' for i in range(3)))
MAX_US = (2**63-1)//1000


class _BoundImuSource:
    """Private loader result, not runtime authentication or an adversarial seal."""
    __slots__ = ('_columns', '_sha256')

    def __new__(cls, *args, **kwargs):
        raise TypeError('use the byte reader load_imu')

    def __setattr__(self, key, value):
        raise AttributeError('immutable loader result')


def write_bytes(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path, value):
    write_bytes(path, (json.dumps(value, indent=2, allow_nan=False)+'\n').encode('utf8'))


def load_imu(path, digest):
    payload = _bound_bytes(path, digest, MAX_ULOG)
    if version('pyulog') != '1.2.4':
        raise RuntimeError('pyulog1.2.4 required')
    from pyulog import ULog
    log = ULog(BytesIO(payload), message_name_filter_list=['sensor_combined'])
    selected = [x for x in log.data_list if x.name == 'sensor_combined' and x.multi_id == 0]
    if len(selected) != 1:
        raise ValueError('sensor_combined instance0 missing or ambiguous')
    result = object.__new__(_BoundImuSource)
    object.__setattr__(result, '_columns', _columns(selected[0].data))
    object.__setattr__(result, '_sha256', digest)
    return result


def _columns(data):
    if (type(data) is not dict or not set(FIELDS) <= data.keys() or len(data) > 256
            or any(type(v) is not np.ndarray or v.ndim != 1 or v.dtype.kind not in 'iuf'
                   or v.dtype.itemsize > 8 for v in data.values())):
        raise ValueError('bounded numeric sensor_combined columns required')
    n = len(data['timestamp'])
    if (not 0 < n <= 100000 or any(v.shape != (n,) for v in data.values())
            or sum(v.nbytes for v in data.values()) > MAX_COLUMN_BYTES):
        raise ValueError('sensor_combined rows/bytes/shape invalid')
    result = {k: v.copy() for k, v in data.items()}
    for v in result.values():
        v.setflags(write=False)
    return result


def imu_records(data):
    """Preserve source rows and separate sample epochs; no nearest-time merge."""
    data = _columns(data)
    previous_gyro = previous_accel = None
    previous_counts = {}
    reset = clock_fault = False
    for index in range(len(data['timestamp'])):
        raw = {k: v[index].item() for k, v in data.items()}
        reasons = []
        stamp, relative = raw['timestamp'], raw['accelerometer_timestamp_relative']
        gyro = stamp if type(stamp) is int and 0 < stamp <= MAX_US else None
        if gyro is None:
            reasons.append('gyro_timestamp_invalid')
        accel = None
        if type(relative) is not int or not -2**31 <= relative < 2**31:
            reasons.append('accel_relative_timestamp_type_invalid')
        elif relative == 2147483647:
            reasons.append('accel_relative_timestamp_invalid')
        elif gyro is not None:
            value = gyro+relative
            if 0 < value <= MAX_US:
                accel = value
            else:
                reasons.append('accel_timestamp_invalid')
        for name, stamp_value, previous in (('gyro', gyro, previous_gyro), ('accel', accel, previous_accel)):
            if stamp_value is None or (previous is not None and stamp_value <= previous):
                clock_fault = True
                if stamp_value is not None:
                    reasons.append(name+'_timestamp_nonincreasing')
        if gyro is not None:
            previous_gyro = gyro
        if accel is not None:
            previous_accel = accel
        if clock_fault:
            reasons.append('imu_timing_epoch_unresolved')
        if gyro != accel:
            reasons.append('gyro_accel_sample_times_differ')
        for name, prefix, time_us in (('gyro', 'gyro', gyro), ('accel', 'accelerometer', accel)):
            dt, clipping = raw[prefix+'_integral_dt'], raw[prefix+'_clipping']
            if type(dt) is not int or not 0 < dt <= 1000000 or time_us is None or dt > time_us:
                reasons.append(name+'_integration_period_invalid')
            if type(clipping) is not int or clipping != 0:
                reasons.append(name+'_clipping')
            field = 'gyro_rad' if name == 'gyro' else 'accelerometer_m_s2'
            if any(not math.isfinite(raw[f'{field}[{i}]']) for i in range(3)):
                reasons.append(name+'_nonfinite')
        for name in ('gyro_calibration_count', 'accel_calibration_count'):
            value = raw[name]
            if type(value) is not int or not 0 <= value <= 255:
                reset = True
                reasons.append(name+'_invalid')
            elif name in previous_counts and previous_counts[name] != value:
                reset = True
            previous_counts[name] = value
        if reset:
            reasons.append('imu_calibration_epoch_unresolved')
        encoded = {k: {'nonfinite': float(v).hex()} if type(v) is float and not math.isfinite(v) else v
                   for k, v in raw.items()}
        yield {'index': index, 'gyro_sample_ns': None if gyro is None else gyro*1000,
               'accel_sample_ns': None if accel is None else accel*1000,
               'raw': encoded, 'reasons': sorted(set(reasons)), 'frame': 'body-FRD',
               'semantics': 'scaled offset-compensated interval averages, not instantaneous raw ADC',
               'host_receipt_ns': None, **FLAGS}


def rgb_png(rgb, width, height):
    if type(rgb) is not bytes or (width, height) != (160, 120) or len(rgb) != width*height*3:
        raise ValueError('exact160x120 RGB pixels required')
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    scans = b''.join(b'\0'+rgb[n*width*3:(n+1)*width*3] for n in range(height))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scans))+chunk(b'IEND', b''))


def write_dataset(output, manifest_path, manifest_sha, binding, data, *, ulog_sha=None, epoch=None):
    """Compose parsed columns; CLI enforces actual ULog byte binding separately."""
    bound = type(data) is _BoundImuSource
    effective_sha = data._sha256 if bound else None
    if ulog_sha is not None and ulog_sha != effective_sha:
        raise ValueError('ULog identity must come from the byte reader')
    ulog_sha = effective_sha
    # One immutable snapshot feeds both journal and native CSV passes.
    data = _columns(data._columns if bound else data)
    raw_manifest = _bound_bytes(manifest_path, manifest_sha, 1024*1024)
    doc = json.loads(raw_manifest, object_pairs_hook=_unique)
    if (type(doc) is not dict or set(doc) != {'schema', 'frames', 'out_of_order_drops'}
            or doc['schema'] != 'flydrones-rgb-capture-v1' or type(doc['frames']) is not list
            or not 1 <= len(doc['frames']) <= 512 or type(doc['out_of_order_drops']) is not int
            or doc['out_of_order_drops'] < 0 or (binding.width, binding.height) != (160, 120)):
        raise ValueError('RGB manifest/rig structure invalid')
    frames, previous = [], -1
    for row in doc['frames']:
        if type(row) is not dict or set(row) != {'frame_ns', 'path', 'width', 'height', 'sha256'}:
            raise ValueError('RGB manifest frame fields invalid')
        stamp = row['frame_ns']
        if (type(stamp) is not int or not previous < stamp <= 2**63-1 or stamp <= 0
                or row['path'] != f'rgb-frames/{stamp}.ppm' or type(row['width']) is not int
                or type(row['height']) is not int or (row['width'], row['height']) != (160, 120)):
            raise ValueError('RGB manifest frame identity invalid')
        frames.append(stamp)
        previous = stamp
    expected_epoch = {'schema': 'flydrones-camera-px4-epoch-declaration-v1',
                      'relation': 'same-px4-boot-epoch', 'rig_sha256': binding.sha256,
                      'ulog_sha256': ulog_sha,
                      'frame_sequence_sha256': hashlib.sha256(json.dumps(frames, separators=(',', ':')).encode()).hexdigest()}
    if epoch is not None and (type(epoch) is not dict or epoch != expected_epoch):
        raise ValueError('epoch declaration does not bind these inputs')
    (output/'cam0/data').mkdir(parents=True, exist_ok=False)
    (output/'inputs/rgb-frames').mkdir(parents=True, exist_ok=False)
    write_bytes(output/'inputs/rgb-capture-manifest.json', raw_manifest)
    identity = {'ulog_sha256': ulog_sha, 'rgb_manifest_sha256': manifest_sha,
                'rig_sha256': binding.sha256, 'rig_evidence_sha256': dict(binding.evidence_sha256),
                'body_id': binding.body_id, 'camera_id': binding.camera_id}
    with (output/'cam0/data.csv').open('x', encoding='utf8', newline='') as cam, \
            (output/'camera-source.jsonl').open('x', encoding='utf8') as journal:
        csv_writer = csv.writer(cam)
        csv_writer.writerow(['#timestamp [ns]', 'filename'])
        for index, row in enumerate(doc['frames']):
            payload = _bound_bytes(manifest_path.parent/row['path'], row['sha256'], 65536)
            header = b'P6\n160 120\n255\n'
            if not payload.startswith(header) or len(payload) != len(header)+160*120*3:
                raise ValueError('exact recorder P6 frame required')
            png = rgb_png(payload[len(header):], 160, 120)
            name = f"{row['frame_ns']}.png"
            write_bytes(output/'inputs'/row['path'], payload)
            write_bytes(output/'cam0/data'/name, png)
            csv_writer.writerow([row['frame_ns'], name])
            journal.write(json.dumps({'index': index, **row, 'output_png': 'cam0/data/'+name,
                                     'output_png_sha256': hashlib.sha256(png).hexdigest(),
                                     'source_identity': identity, 'host_receipt_ns': None, **FLAGS})+'\n')
        for stream in (cam, journal):
            stream.flush()
            os.fsync(stream.fileno())
    reasons, rows, invalid = Counter(), 0, 0
    with (output/'imu-source.jsonl').open('x', encoding='utf8') as stream:
        for row in imu_records(data):
            row.update(source_identity=identity)
            stream.write(json.dumps(row, allow_nan=False)+'\n')
            rows += 1
            invalid += bool(row['reasons'])
            reasons.update(row['reasons'])
        stream.flush()
        os.fsync(stream.fileno())
    emit = bound and invalid == 0 and epoch is not None and doc['out_of_order_drops'] == 0
    if emit:
        (output/'imu0').mkdir(exist_ok=False)
        with (output/'imu0/data.csv').open('x', encoding='utf8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['#timestamp [ns]', 'w_RS_S_x [rad s^-1]', 'w_RS_S_y [rad s^-1]',
                             'w_RS_S_z [rad s^-1]', 'a_RS_S_x [m s^-2]', 'a_RS_S_y [m s^-2]', 'a_RS_S_z [m s^-2]'])
            for row in imu_records(data):
                writer.writerow([row['gyro_sample_ns'],
                                 *(format(row['raw'][f'{name}[{i}]'], '.17g')
                                   for name in ('gyro_rad', 'accelerometer_m_s2') for i in range(3))])
            stream.flush()
            os.fsync(stream.fileno())
    return {'schema': 'flydrones-camera-px4-imu-file-dataset-v1', 'camera_frames': len(frames),
            'imu_rows': rows, 'imu_structurally_refused_rows': invalid, 'imu_reason_counts': dict(reasons),
            'out_of_order_drops': doc['out_of_order_drops'], 'candidate_imu_csv_emitted': emit,
            'ulog_bytes_bound_by_reader': bound,
            'epoch_declaration': epoch, 'source_identity': identity, 'rig_domain': binding.domain,
            'consumer_executed': False, 'pixels': 'lossless RGB8; no resize/grayscale',
            'imu_semantics': 'body FRD SI interval averages; covariance/orientation absent', **FLAGS}
