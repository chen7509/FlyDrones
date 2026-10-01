"""Fingerprint actual inputs, including uncommitted experiment dependencies."""

import hashlib
import json
import math
from numbers import Real
from pathlib import Path

import yaml


def _manifest_digest(manifest: dict) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != 'manifest_sha256'}
    payload = json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def seal_manifest(manifest: dict) -> dict:
    sealed = json.loads(json.dumps(manifest))
    sealed['manifest_sha256'] = _manifest_digest(sealed)
    return sealed


def verify_sealed_manifest(manifest: dict) -> str:
    expected = manifest.get('manifest_sha256')
    actual = _manifest_digest(manifest)
    if not isinstance(expected, str) or expected != actual:
        raise ValueError('freeze manifest seal mismatch')
    return actual


def sha256_file(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'input outside workspace: {path}')
    return resolved


def freeze_files(paths: list[Path], root: Path) -> dict[str, str]:
    root = root.resolve()
    return dict(sorted((str(_inside(p, root).relative_to(root)).replace('\\', '/'), sha256_file(p)) for p in paths))


def verify_files(manifest: dict[str, str], root: Path) -> None:
    for relative, expected in manifest.items():
        path = _inside(root / relative, root)
        if not path.is_file():
            raise ValueError(f'missing frozen input: {relative}')
        if sha256_file(path) != expected:
            raise ValueError(f'changed frozen input: {relative}')


def load_benchmark_config(path: Path) -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('benchmark config must be a mapping')

    def value(section: str, name: str):
        try:
            return config[section][name]
        except (KeyError, TypeError) as exc:
            raise ValueError(f'missing {section}.{name}') from exc

    def positive(section: str, name: str) -> float:
        item = value(section, name)
        if isinstance(item, bool) or not isinstance(item, Real) or not math.isfinite(float(item)) or item <= 0:
            raise ValueError(f'{section}.{name} must be finite and positive')
        return float(item)

    for name in ('dt_s', 'speed_max_mps', 'acceleration_max_mps2', 'yaw_rate_max_radps'):
        positive('control', name)
    for name in ('width', 'height'):
        item = value('camera', name)
        if type(item) is not int or item <= 0:
            raise ValueError(f'camera.{name} must be a positive integer')
    for name in ('hz', 'hfov_rad', 'near_m', 'far_m'):
        positive('camera', name)
    if not 0 < value('camera', 'hfov_rad') < math.pi:
        raise ValueError('camera.hfov_rad must be between zero and pi')
    if value('camera', 'near_m') >= value('camera', 'far_m'):
        raise ValueError('camera.near_m must be below far_m')
    for name in ('goal_radius_m', 'goal_hold_s', 'timeout_s'):
        positive('task', name)
    if value('task', 'goal_hold_s') >= value('task', 'timeout_s'):
        raise ValueError('task.goal_hold_s must be below timeout_s')
    size = value('world', 'size_m')
    altitude = value('world', 'altitude_m')
    if len(size) != 3 or not all(isinstance(item, Real) and math.isfinite(float(item)) and item > 0 for item in size):
        raise ValueError('world.size_m must contain three finite positive values')
    if len(altitude) != 2 or not all(isinstance(item, Real) and math.isfinite(float(item)) for item in altitude) or altitude[0] >= altitude[1]:
        raise ValueError('world.altitude_m must be an increasing finite pair')
    return config
