"""Actual native CSV reader tests; never instantiate an estimator here."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dataset_executor', ROOT/'tools/benchmark/run_openvins_dataset_consumer.py')
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
IMU_HEADER = ('#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],'
              'a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]')


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    root = tmp_path_factory.mktemp('native-reader')
    facts = executor.admission()
    assert facts['admitted'], 'test resource/process gate failed, no compilation'
    binary = root/'reader'
    executor.scoped(root/'compile', ['/usr/bin/g++', '-std=c++17', '-O2',
                    '-I'+executor.linux(ROOT/'tools/benchmark/gpl'),
                    executor.linux(ROOT/'tests/benchmark/native_dataset_reader.cpp'), '-o', executor.linux(binary)],
                    label='test-reader', memory=128*1024**2, seconds=30, outer_seconds=45)
    return binary


def run_reader(native, tmp_path, *, camera='1000000000,1000000000.png\n', imu='1000000000,0,0,0,0,0,9.81\n'):
    cam, inertial = tmp_path/'cam.csv', tmp_path/'imu.csv'
    cam.write_text('#timestamp [ns],filename\n'+camera, encoding='utf8', newline='\n')
    inertial.write_text(IMU_HEADER+'\n'+imu, encoding='utf8', newline='\n')
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--', executor.linux(native),
                           executor.linux(cam), executor.linux(inertial)], capture_output=True)


def test_actual_native_preserves_integer_nanoseconds(native, tmp_path):
    p = run_reader(native, tmp_path, camera='9007199254740993,9007199254740993.png\n',
                   imu='9007199254740993,0,0,0,0,0,9.81\n')
    assert p.returncode == 0
    assert p.stdout.strip() == b'1,1,9007199254740993,9007199254740993'


@pytest.mark.parametrize('camera', ['1000000000,../1000000000.png\n',
                                  '1000000000,1000000000.png,extra\n',
                                  '1000000000,1000000000.png\n1000000000,1000000000.png\n'])
def test_native_refuses_camera_escape_extra_and_regression(native, tmp_path, camera):
    assert run_reader(native, tmp_path, camera=camera).returncode != 0


@pytest.mark.parametrize('imu', ['1000000000,nan,0,0,0,0,9.81\n',
                               '1000000000junk,0,0,0,0,0,9.81\n',
                               '9223372036854775808,0,0,0,0,0,9.81\n'])
def test_native_refuses_nonfinite_partial_integer_and_overflow(native, tmp_path, imu):
    assert run_reader(native, tmp_path, imu=imu).returncode != 0


def test_one_shot_existing_study_never_dispatches(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, 'STUDY', tmp_path)
    monkeypatch.setattr(executor, 'admission', lambda: pytest.fail('existing result attempted admission/dispatch'))
    with pytest.raises(FileExistsError):
        executor.execute()


def test_refused_admission_never_creates_or_dispatches(tmp_path, monkeypatch):
    root = tmp_path/'not-created'
    monkeypatch.setattr(executor, 'STUDY', root)
    monkeypatch.setattr(executor, 'admission', lambda: {'admitted': False})
    monkeypatch.setattr(executor, 'verify_input', lambda: pytest.fail('refused resource gate read/dispatched'))
    with pytest.raises(RuntimeError, match='admission refused'):
        executor.execute()
    assert not root.exists()
