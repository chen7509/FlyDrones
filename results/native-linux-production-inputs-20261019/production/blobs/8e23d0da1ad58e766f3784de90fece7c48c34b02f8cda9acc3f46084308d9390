"""Timestamped RGB-D transport. No world geometry belongs on this boundary."""

import base64
import bisect
import json
from dataclasses import asdict, fields

import numpy as np

from .contract import Observation


class PoseHistory:
    """Monotonic timestamped poses with linear position and quaternion SLERP."""

    def __init__(self, max_samples: int = 512):
        self.max_samples = int(max_samples)
        if self.max_samples < 2:
            raise ValueError('pose history needs at least two samples')
        self._times: list[int] = []
        self._poses: list[tuple[float, ...]] = []

    def add(self, sim_ns: int, pose: tuple[float, ...]) -> None:
        if type(sim_ns) is not int or (self._times and sim_ns <= self._times[-1]):
            raise ValueError('pose timestamps must increase')
        if len(pose) != 7 or not np.all(np.isfinite(pose)):
            raise ValueError('pose must be finite xyz plus xyzw quaternion')
        q = np.asarray(pose[3:], dtype=float)
        norm = float(np.linalg.norm(q))
        if norm <= 1e-12:
            raise ValueError('pose quaternion cannot be zero')
        normalized = tuple(float(v) for v in (*pose[:3], *(q / norm)))
        self._times.append(sim_ns)
        self._poses.append(normalized)
        if len(self._times) > self.max_samples:
            del self._times[0]
            del self._poses[0]

    def at(self, frame_ns: int) -> tuple[float, ...]:
        index = bisect.bisect_left(self._times, frame_ns)
        if index < len(self._times) and self._times[index] == frame_ns:
            return self._poses[index]
        if index == 0 or index == len(self._times):
            raise ValueError('pose history does not bracket frame timestamp')
        before_ns, after_ns = self._times[index - 1], self._times[index]
        fraction = (frame_ns - before_ns) / (after_ns - before_ns)
        before, after = np.asarray(self._poses[index - 1]), np.asarray(self._poses[index])
        position = before[:3] + fraction * (after[:3] - before[:3])
        quaternion = _slerp(before[3:], after[3:], fraction)
        return tuple(float(v) for v in np.concatenate((position, quaternion)))

    def latest_at_or_before(self, sim_ns: int, *, max_age_ns: int) -> tuple[float, ...]:
        """Return measured state near a stopped clock without extrapolating it."""
        index = bisect.bisect_right(self._times, sim_ns) - 1
        if index < 0:
            raise ValueError('pose history has no sample at or before timestamp')
        age = int(sim_ns) - self._times[index]
        if age > int(max_age_ns):
            raise ValueError(f'latest pose is stale by {age} ns')
        return self._poses[index]

    def at_or_recent_before(self, sim_ns: int, *, max_age_ns: int) -> tuple[float, ...]:
        """Interpolate when bracketed, otherwise accept one recent measurement."""
        try:
            return self.at(sim_ns)
        except ValueError:
            return self.latest_at_or_before(sim_ns, max_age_ns=max_age_ns)


def _slerp(a: np.ndarray, b: np.ndarray, fraction: float) -> np.ndarray:
    dot = float(a @ b)
    if dot < 0:
        b = -b
        dot = -dot
    dot = float(np.clip(dot, -1., 1.))
    if dot > .9995:
        result = a + fraction * (b - a)
        return result / np.linalg.norm(result)
    angle = np.arccos(dot)
    return (np.sin((1 - fraction) * angle) * a + np.sin(fraction * angle) * b) / np.sin(angle)


def _quaternion_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    av, aw = a[:3], a[3]
    bv, bw = b[:3], b[3]
    return np.concatenate((aw * bv + bw * av + np.cross(av, bv), [aw * bw - av @ bv]))


def _quaternion_rotate(quaternion: np.ndarray, vector: np.ndarray) -> np.ndarray:
    qv = quaternion[:3]
    return vector + 2 * np.cross(qv, np.cross(qv, vector) + quaternion[3] * vector)


def camera_pose_from_model(model_pose: tuple[float, ...]) -> tuple[float, ...]:
    """Compose the fixed camera location and optical-frame convention."""
    if len(model_pose) != 7 or not np.all(np.isfinite(model_pose)):
        raise ValueError('model pose must be finite xyz plus xyzw quaternion')
    model_q = np.asarray(model_pose[3:], dtype=float)
    norm = float(np.linalg.norm(model_q))
    if norm <= 1e-12:
        raise ValueError('model quaternion cannot be zero')
    model_q /= norm
    camera_position = np.asarray(model_pose[:3], dtype=float) + _quaternion_rotate(
        model_q, np.asarray((.12, 0., .242), dtype=float)
    )
    # Gazebo camera: +X forward, +Y left, +Z up. EGO's optical frame uses
    # +Z forward, +X right, +Y down.
    optical_to_model = np.asarray((.5, -.5, .5, -.5), dtype=float)
    camera_q = _quaternion_multiply(model_q, optical_to_model)
    camera_q /= np.linalg.norm(camera_q)
    return tuple(float(value) for value in np.concatenate((camera_position, camera_q)))


def camera_matrix(width: int, height: int, hfov: float) -> np.ndarray:
    if width <= 0 or height <= 0 or not 0 < hfov < np.pi:
        raise ValueError('invalid camera geometry')
    focal = width / (2 * np.tan(hfov / 2))
    return np.array([[focal, 0., (width-1)/2], [0., focal, (height-1)/2], [0., 0., 1.]])


def optical_to_body(point: np.ndarray) -> np.ndarray:
    x, y, z = point
    return np.array([z, -x, -y])


class FrameCache:
    def __init__(self):
        self.frame_ns = -1
        self.rgb = self.depth_m = self.camera_pose = None

    def add(self, frame_ns: int, rgb: np.ndarray, depth_m: np.ndarray, camera_pose: tuple) -> bool:
        if camera_pose is None or len(camera_pose) != 7 or not np.all(np.isfinite(camera_pose)):
            raise ValueError('frame requires capture-time camera pose')
        if frame_ns <= self.frame_ns:
            return False
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[:2] != depth_m.shape:
            raise ValueError('RGB and depth must have matching geometry')
        self.frame_ns, self.rgb, self.depth_m = frame_ns, rgb.copy(), depth_m.copy()
        self.camera_pose = tuple(camera_pose)
        return True


def encode_observation(obs: Observation) -> bytes:
    data = asdict(obs)
    for key, dtype in (('rgb', np.uint8), ('depth_m', np.dtype('<f4'))):
        array = np.ascontiguousarray(data[key], dtype=dtype)
        data[key] = {'shape': list(array.shape), 'data': base64.b64encode(array.tobytes()).decode('ascii')}
    return json.dumps(data, allow_nan=False, separators=(',', ':')).encode('utf-8')


def decode_observation(payload: bytes) -> Observation:
    if len(payload) > 8_000_000:
        raise ValueError('observation too large')
    data = json.loads(payload)
    if set(data) != {f.name for f in fields(Observation)}:
        raise ValueError('unexpected observation fields (truth is forbidden)')
    for key, dtype in (('rgb', np.uint8), ('depth_m', np.dtype('<f4'))):
        packed = data[key]
        if set(packed) != {'shape', 'data'}:
            raise ValueError('invalid image encoding')
        shape = packed['shape']
        if not isinstance(shape, list) or any(type(n) is not int or not 0 < n <= 4096 for n in shape):
            raise ValueError('invalid image shape')
        raw = base64.b64decode(packed['data'], validate=True)
        if np.prod(shape) * np.dtype(dtype).itemsize != len(raw):
            raise ValueError('image size mismatch')
        data[key] = np.frombuffer(raw, dtype=dtype).reshape(shape).copy()
    cache = FrameCache()
    cache.add(data['frame_ns'], data['rgb'], data['depth_m'], data['camera_pose'])
    if not 0 <= data['frame_ns'] <= data['sim_ns']:
        raise ValueError('invalid frame timestamp')
    for key in ('position', 'velocity', 'goal'):
        if len(data[key]) != 3 or not np.all(np.isfinite(data[key])):
            raise ValueError('invalid navigation vector')
        data[key] = tuple(data[key])
    if not np.all(np.isfinite([data['yaw'], data['yaw_rate']])):
        raise ValueError('invalid angular state')
    data['camera_pose'] = tuple(data['camera_pose'])
    return Observation(**data)
