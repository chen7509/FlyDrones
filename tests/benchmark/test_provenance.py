import hashlib
from pathlib import Path

import pytest

from flydrones.benchmark.provenance import (
    freeze_files,
    load_benchmark_config,
    seal_manifest,
    sha256_file,
    verify_files,
    verify_sealed_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_changed_dependency_rejected(tmp_path):
    p = tmp_path / 'config.yaml'
    p.write_text('speed: 0.8')
    frozen = freeze_files([p], tmp_path)
    p.write_text('speed: 1.2')
    with pytest.raises(ValueError, match='changed'):
        verify_files(frozen, tmp_path)


def test_missing_dependency_rejected(tmp_path):
    p = tmp_path / 'model'
    p.write_bytes(b'brain')
    frozen = freeze_files([p], tmp_path)
    p.unlink()
    with pytest.raises(ValueError, match='missing'):
        verify_files(frozen, tmp_path)


def test_relative_sorted_manifest_roundtrip(tmp_path):
    p = tmp_path / 'model'
    p.write_bytes(b'brain')
    assert sha256_file(p) == hashlib.sha256(b'brain').hexdigest()
    frozen = freeze_files([p], tmp_path)
    assert list(frozen) == ['model']
    verify_files(frozen, tmp_path)


def test_outside_root_rejected(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    p = tmp_path / 'outside'
    p.write_bytes(b'not an input')
    with pytest.raises(ValueError):
        freeze_files([p], root)
    with pytest.raises(ValueError):
        verify_files({'../outside': 'bad'}, root)


def test_sealed_manifest_detects_metadata_tampering():
    sealed = seal_manifest({'phase': 'freeze', 'files': {'a': 'b'}})
    assert verify_sealed_manifest(sealed) == sealed['manifest_sha256']
    sealed['files']['a'] = 'changed'
    with pytest.raises(ValueError, match='seal'):
        verify_sealed_manifest(sealed)


def test_ego_image_retries_transient_package_downloads():
    dockerfile = (REPO_ROOT / 'tools/benchmark/Dockerfile.ego').read_text()
    assert 'Acquire::Retries=5' in dockerfile
    assert 'https://archive.ubuntu.com' in dockerfile
    assert "find /etc/apt/sources.list.d -type f" in dockerfile
    assert '--mount=type=cache,target=/var/cache/apt' in dockerfile
    assert '--skip-keys "Eigen3 PCL Boost Armadillo"' in dockerfile


def test_invalid_benchmark_limits_are_rejected(tmp_path):
    config = tmp_path / 'benchmark.yaml'
    config.write_text(
        'control:\n  dt_s: 0.05\n  speed_max_mps: 0\n  acceleration_max_mps2: 1.2\n'
        '  yaw_rate_max_radps: 0.6\ncamera:\n  width: 160\n  height: 120\n  hz: 10\n'
        '  hfov_rad: 1.274\n  near_m: 0.2\n  far_m: 19.1\n'
    )
    with pytest.raises(ValueError, match='speed_max_mps'):
        load_benchmark_config(config)
