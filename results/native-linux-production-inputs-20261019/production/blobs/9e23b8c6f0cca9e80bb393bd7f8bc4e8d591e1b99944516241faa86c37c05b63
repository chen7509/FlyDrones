"""File production of PX4-derived camera poses; no live/flight authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from importlib.metadata import version
from io import BytesIO
from pathlib import Path, PurePosixPath

import numpy as np
from scipy.spatial.transform import Rotation

from .ekf2_shadow import audit_shadow_frames, audit_state_sample_times

MAX_DOCUMENT = 64 * 1024
MAX_ULOG = 16 * 1024 * 1024
MAX_ROWS = 100_000
MAX_FRAMES = 4096
MAX_COLUMN_BYTES = 64 * 1024 * 1024
TOPICS = ('vehicle_local_position', 'vehicle_attitude', 'estimator_status', 'estimator_status_flags')
RESETS = {'vehicle_local_position': ('xy_reset_counter', 'z_reset_counter', 'vxy_reset_counter',
                                   'vz_reset_counter', 'heading_reset_counter'),
          'vehicle_attitude': ('quat_reset_counter',)}
NED_TO_ENU = np.array([[0., 1., 0.], [1., 0., 0.], [0., 0., -1.]])


def _linked(path):
    for p in (path.absolute(), *path.absolute().parents):
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            return True
    return False


def _bound_bytes(path, expected, maximum):
    path = Path(path)
    if (type(expected) is not str or re.fullmatch('[0-9a-f]{64}', expected) is None
            or _linked(path) or not path.is_file()):
        raise ValueError('bound source path or SHA invalid')
    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns
    before = path.stat()
    if before.st_size > maximum:
        raise ValueError('bound source exceeds byte limit')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (len(data) > maximum or len(data) != before.st_size
            or not identity(before) == identity(opened) == identity(after) == identity(path.stat())):
        raise ValueError('bound source changed during read')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('bound source SHA mismatch')
    return data


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate calibration key')
        result[name] = value
    return result


def _document(path, digest):
    value = json.loads(_bound_bytes(path, digest, MAX_DOCUMENT), object_pairs_hook=_unique)
    if type(value) is not dict:
        raise ValueError('calibration document must be a mapping')
    return value


def _evidence(root, value):
    if type(value) is not dict or set(value) != {'path', 'sha256'}:
        raise ValueError('calibration evidence reference invalid')
    name = value['path']
    if (type(name) is not str or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or any(x in ('', '.', '..') for x in name.split('/'))):
        raise ValueError('calibration evidence escapes rig root')
    path = root.joinpath(*PurePosixPath(name).parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('calibration evidence escapes rig root')
    return _document(path, value['sha256'])


def _array(value, shape):
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in 'iuf':
        raise ValueError('calibration numeric shape/type invalid')
    data = raw.astype(float)
    if not np.isfinite(data).all() or np.any(np.abs(data) > np.finfo(np.float32).max):
        raise ValueError('calibration values nonfinite/unrepresentable')
    return data


@dataclass(frozen=True)
class CameraRigBinding:
    sha256: str
    body_id: str
    camera_id: str
    domain: str
    width: int
    height: int
    intrinsics_k: tuple[float, ...]
    body_from_optical: tuple[tuple[float, ...], ...]
    translation_body_m: tuple[float, ...]
    evidence_sha256: tuple[tuple[str, str], ...]

    @classmethod
    def load(cls, path, expected_sha256, *, body_id, camera_id):
        path = Path(path)
        doc = _document(path, expected_sha256)
        if (set(doc) != {'schema', 'body_id', 'camera_id', 'domain', 'intrinsics', 'extrinsics'}
                or doc['schema'] != 'flydrones-px4-camera-rig-v1'
                or type(body_id) is not str or not body_id or type(camera_id) is not str or not camera_id
                or doc['body_id'] != body_id or doc['camera_id'] != camera_id
                or doc['domain'] not in ('simulation-candidate', 'hardware-candidate')):
            raise ValueError('camera rig schema/device/domain mismatch')
        intrinsic = _evidence(path.parent, doc['intrinsics'])
        mount = _evidence(path.parent, doc['extrinsics'])
        info = intrinsic.get('camera_info')
        if (intrinsic.get('schema') != 'flydrones-camera-info-v1' or type(info) is not dict
                or info.get('frame_id') != camera_id
                or any(type(info.get(n)) is not int or info[n] <= 0 for n in ('width', 'height'))):
            raise ValueError('camera intrinsics identity/size invalid')
        k = _array(info.get('intrinsics_k'), (9,)).reshape(3, 3)
        if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.array_equal(k[2], [0., 0., 1.]):
            raise ValueError('camera intrinsics convention invalid')
        if (set(mount) != {'schema', 'body_id', 'camera_id', 'rotation', 'translation_m'}
                or mount['schema'] != 'flydrones-body-frd-from-camera-optical-v1'
                or mount['body_id'] != body_id or mount['camera_id'] != camera_id):
            raise ValueError('camera mounting identity/convention invalid')
        r = _array(mount['rotation'], (3, 3))
        t = _array(mount['translation_m'], (3,))
        if not np.allclose(r.T @ r, np.eye(3), atol=1e-9, rtol=0) or abs(np.linalg.det(r)-1.) > 1e-9:
            raise ValueError('camera mounting is not a proper rotation')
        return cls(expected_sha256, body_id, camera_id, doc['domain'], info['width'], info['height'],
                   tuple(k.flatten()), tuple(tuple(row) for row in r), tuple(t),
                   tuple((name, doc[name]['sha256']) for name in ('intrinsics', 'extrinsics')))


class Px4UlogCameraSource:
    """Offline recorded-source producer. No host receipt or calibration is inferred."""

    @classmethod
    def from_decoded_topics(cls, topics, binding):
        """Compose supplied columns; explicitly unbound to any file or live process."""
        if type(binding) is not CameraRigBinding or not isinstance(topics, dict):
            raise ValueError('camera binding and PX4 topic columns required')
        obj = cls()
        obj.binding = binding
        obj.ulog_sha256 = None
        obj._topics = {}
        total_bytes = 0
        for name in TOPICS:
            data = topics.get(name)
            if not isinstance(data, dict) or 'timestamp' not in data:
                raise ValueError(f'PX4 source topic missing: {name}')
            if (len(data) > 256 or any(type(v) is not np.ndarray or v.ndim != 1
                                      or v.dtype.kind not in 'biuf' or v.dtype.itemsize > 8
                                      for v in data.values())):
                raise ValueError('PX4 source requires bounded numeric NumPy columns')
            length = len(data['timestamp'])
            total_bytes += sum(v.nbytes for v in data.values())
            if (not 0 < length <= MAX_ROWS or any(v.shape != (length,) for v in data.values())
                    or total_bytes > MAX_COLUMN_BYTES):
                raise ValueError('PX4 topic row bound or shape invalid')
            obj._topics[name] = {k: np.array(v, copy=True) for k, v in data.items()}
            for values in obj._topics[name].values():
                values.setflags(write=False)
        return obj

    @classmethod
    def from_ulog(cls, path, expected_sha256, binding):
        payload = _bound_bytes(path, expected_sha256, MAX_ULOG)
        try:
            if version('pyulog') != '1.2.4':
                raise RuntimeError('pyulog1.2.4 required')
            from pyulog import ULog
        except ImportError as exc:
            raise RuntimeError('pyulog1.2.4 required') from exc
        ulog = ULog(BytesIO(payload), message_name_filter_list=list(TOPICS))
        selected = {}
        for name in TOPICS:
            rows = [item for item in ulog.data_list if item.name == name and item.multi_id == 0]
            if len(rows) != 1:
                raise ValueError(f'PX4 topic instance missing or ambiguous: {name}')
            selected[name] = rows[0].data
        obj = cls.from_decoded_topics(selected, binding)
        obj.ulog_sha256 = expected_sha256
        return obj

    def _reset_at(self, frame_ns):
        selected = {}
        unresolved = False
        for name, fields in RESETS.items():
            data = self._topics[name]
            pub = np.asarray(data['timestamp'])
            index = int(np.searchsorted(pub, frame_ns//1000, side='right'))-1
            counters = {}
            for field in fields:
                values = data.get(field)
                if (values is None or values.dtype.kind not in 'iu'
                        or np.any(values > 255) or np.any(values < 0)):
                    raise ValueError(f'PX4 reset field missing/invalid: {field}')
                if index >= 0:
                    counters[field] = int(values[index])
                    unresolved |= bool(np.any(np.diff(values[:index+1].astype(np.int64)) != 0))
            selected[name] = counters if index >= 0 else None
        return unresolved, selected

    def produce(self, frame_ns, *, epoch_declaration=None, calibration_artifact=None):
        if (type(frame_ns) is not list or not 0 < len(frame_ns) <= MAX_FRAMES
                or any(type(t) is not int or not 0 <= t <= 2**63-1 for t in frame_ns)
                or any(b <= a for a, b in zip(frame_ns, frame_ns[1:]))):
            raise ValueError('bounded strictly increasing frame timestamps required')
        declaration = None
        if epoch_declaration is not None:
            frames_sha = hashlib.sha256(json.dumps(frame_ns, separators=(',', ':')).encode('ascii')).hexdigest()
            expected = {'schema': 'flydrones-camera-px4-epoch-declaration-v1',
                        'relation': 'same-px4-boot-epoch', 'rig_sha256': self.binding.sha256,
                        'ulog_sha256': self.ulog_sha256, 'frame_sequence_sha256': frames_sha}
            if type(epoch_declaration) is not dict or epoch_declaration != expected:
                raise ValueError('camera/PX4 epoch declaration does not bind these inputs')
            declaration = dict(epoch_declaration)
        health = audit_shadow_frames(frame_ns, self._topics)
        timing = audit_state_sample_times(frame_ns, self._topics)
        calibration_records = [None] * len(frame_ns)
        if calibration_artifact is not None:
            from .kalibr_camera_consumption import IMU_CONTRACT, KalibrCameraArtifact

            if (type(calibration_artifact) is not KalibrCameraArtifact
                    or calibration_artifact.imu_contract != IMU_CONTRACT
                    or calibration_artifact.rig_sha256 != self.binding.sha256):
                raise ValueError('byte-bound calibration artifact for this rig required')
            selected = []
            for index, stamp in enumerate(frame_ns):
                try:
                    selected.append((index, calibration_artifact.lookup_ns(stamp)))
                except ValueError as error:
                    calibration_records[index] = {'imu_lookup_ns': None, 'health': None, 'sample_timing': None,
                                                  'reset_counters': None, 'error': str(error),
                                                  'reasons': ['lookup_timestamp_outside_boot_range']}
            if selected:
                lookup = [stamp for _, stamp in selected]
                shifted_health = audit_shadow_frames(lookup, self._topics)
                shifted_timing = audit_state_sample_times(lookup, self._topics)
                for (index, stamp), h, c in zip(selected, shifted_health['records'], shifted_timing['records'], strict=True):
                    reset, counts = self._reset_at(stamp)
                    rows = {}
                    for name, data in self._topics.items():
                        row_index = int(np.searchsorted(data['timestamp'], stamp//1000, side='right'))-1
                        rows[name] = None if row_index < 0 else {
                            'index': row_index, 'publication_us': int(data['timestamp'][row_index]),
                            'sample_us': int(data['timestamp_sample'][row_index]) if 'timestamp_sample' in data else None}
                    calibration_records[index] = {'imu_lookup_ns': stamp, 'health': h, 'sample_timing': c,
                                                  'source_rows': rows, 'reset_counters': counts,
                                                  'reasons': sorted(set(h['reasons'] + c['reasons']
                                                                       + (['reset_epoch_unresolved'] if reset else [])))}
        records = []
        for h, clock, calibration in zip(health['records'], timing['records'], calibration_records, strict=True):
            reset, counters = self._reset_at(h['frame_ns'])
            reasons = sorted(set(h['reasons'] + clock['reasons'] + (['reset_epoch_unresolved'] if reset else [])))
            if declaration is None:
                reasons.append('camera_px4_epoch_unbound')
            geometry_clock = clock
            if calibration is not None:
                reasons.extend('calibration_lookup:' + r for r in calibration['reasons'])
                geometry_clock = calibration['sample_timing']
            source_rows = {}
            for name, data in self._topics.items():
                index = int(np.searchsorted(data['timestamp'], h['frame_ns']//1000, side='right'))-1
                source_rows[name] = None if index < 0 else {
                    'index': index, 'publication_us': int(data['timestamp'][index]),
                    'sample_us': int(data['timestamp_sample'][index]) if 'timestamp_sample' in data else None,
                }
            geometry = None
            raw_q = None
            if not reasons:
                pi = geometry_clock['topics']['vehicle_local_position']['index']
                qi = geometry_clock['topics']['vehicle_attitude']['index']
                local, att = self._topics['vehicle_local_position'], self._topics['vehicle_attitude']
                p = np.array([local[n][pi] for n in ('x', 'y', 'z')], dtype=float)
                v = np.array([local[n][pi] for n in ('vx', 'vy', 'vz')], dtype=float)
                raw_q = [float(att[f'q[{i}]'][qi]) for i in range(4)]
                body = Rotation.from_quat([*raw_q[1:], raw_q[0]]).as_matrix()
                mount = np.asarray(self.binding.body_from_optical)
                translation = np.asarray(self.binding.translation_body_m)
                if calibration is not None:
                    mount, translation = calibration_artifact.body_from_camera()
                camera_p = NED_TO_ENU @ (p + body @ translation)
                camera_q = Rotation.from_matrix(NED_TO_ENU @ body @ mount).as_quat()
                geometry = {'position_enu_m': (NED_TO_ENU @ p).tolist(),
                            'velocity_enu_m_s': (NED_TO_ENU @ v).tolist(),
                            'camera_pose_enu_xyzw': [*camera_p.tolist(), *camera_q.tolist()]}
            records.append({'frame_ns': h['frame_ns'], 'reasons': reasons, 'geometry': geometry,
                            'source_quaternion_wxyz': raw_q, 'health': h, 'sample_timing': clock,
                            'reset_counters': counters, 'rig_sha256': self.binding.sha256,
                            'host_receipt_ns': None, 'source_rows': source_rows,
                            'source_identity': {'ulog_sha256': self.ulog_sha256,
                                                'rig_sha256': self.binding.sha256,
                                                'rig_evidence_sha256': dict(self.binding.evidence_sha256)},
                            'epoch_declaration': declaration,
                            'live_source_authenticated': False, 'clock_epoch_qualified': False,
                            'camera_calibration_qualified': False, 'training_eligible': False,
                            'flight_eligible': False})
            if calibration is not None:
                records[-1]['calibration_lookup'] = calibration
                records[-1]['calibration_artifact'] = calibration_artifact.record()
        result = {'schema': 'flydrones-px4-camera-file-production-v1', 'ulog_sha256': self.ulog_sha256,
                'source_kind': 'bound-ULog' if self.ulog_sha256 else 'unbound-decoded-columns',
                'body_id': self.binding.body_id, 'camera_id': self.binding.camera_id,
                'rig_sha256': self.binding.sha256, 'rig_domain': self.binding.domain,
                'rig_evidence_sha256': dict(self.binding.evidence_sha256), 'records': records,
                'epoch_assumption': 'caller-declared common; unqualified' if declaration else 'unbound',
                'missing_qualification': ['owned_runtime_source', 'continuous_clock_epoch',
                                          'measured_spatial_temporal_camera_calibration', 'goal_reset_policy',
                                          'inspected_running_teacher'],
                'live_source_authenticated': False, 'clock_epoch_qualified': False,
                'camera_calibration_qualified': False, 'training_eligible': False, 'flight_eligible': False}
        if calibration_artifact is not None:
            result['calibration_artifact'] = calibration_artifact.record()
            applied = sum(r['calibration_lookup']['imu_lookup_ns'] is not None for r in records)
            result['calibration_artifact']['lookup_applied_frames'] = applied
            result['calibration_artifact']['lookup_refused_frames'] = len(records)-applied
            result['calibration_artifact']['pose_applied_frames'] = sum(r['geometry'] is not None for r in records)
        return result
