"""Exact new-dataset bridge behavior, not a mock of native estimator output."""

import importlib
import json
import subprocess
from types import SimpleNamespace

import pytest


def api():
    return importlib.import_module('tools.benchmark.openvins_cached_bridge')


def test_lossless_nanosecond_to_existing_microsecond_interface():
    assert api().microsecond_stamp('1004000000') == 1004000
    with pytest.raises(ValueError):
        api().microsecond_stamp('1004000001')
    with pytest.raises(ValueError):
        api().microsecond_stamp('1004000000junk')


def test_complete_source_partition_and_retained_tail():
    ledger = api().frame_partition([2, 500, 600, 700], [500, 550, 600, 650])
    assert [x['status'] for x in ledger] == ['imu_range_refused', 'native_requested', 'native_requested', 'imu_range_refused']
    assert [x['source_index'] for x in ledger] == [0, 1, 2, 3]
    counts = api().native_counts('frames=2 imu_fed=3 initialized_frames=0\n', 2, 4)
    assert counts['imu_unconsumed_tail_indices'] == [3]
    assert counts['public_initialized_frames'] == 0
    assert not counts['teacher_qualified']


def test_returned_native_count_is_not_invented_from_requested_inputs():
    with pytest.raises(ValueError):
        api().native_counts('frames=1 imu_fed=2 initialized_frames=0\n', 2, 4)
    with pytest.raises(ValueError):
        api().native_counts('', 2, 4)


def test_actual_sealed_file_bridge_retains_every_identity(tmp_path):
    module = api()
    binding = module.prepare(tmp_path / 'bridge')
    ledger = json.loads((tmp_path / 'bridge/frame-ledger.json').read_text(encoding='utf8'))
    assert binding['source_frames'] == len(ledger) == 251
    assert binding['frames_requested'] == 245
    assert binding['source_imu_rows'] == 6123
    assert sum(x['status'] == 'imu_range_refused' for x in ledger) == 6
    assert len((tmp_path / 'bridge/imu.csv').read_text().splitlines()) == 6124


def test_changed_sealed_journal_is_refused_before_bridge(tmp_path, monkeypatch):
    module = api()
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}', encoding='utf8')
    monkeypatch.setattr(module.execution, 'MANIFEST', manifest)
    with pytest.raises(ValueError, match='sealed manifest changed'):
        module.prepare(tmp_path / 'bridge')
    assert not (tmp_path / 'bridge').exists()


def test_windows_build_and_estimator_competitors_refuse():
    execution = api().execution
    for name in ('g++.exe', 'gcc.exe', 'cmake.exe', 'ninja.exe', 'openvins.exe', 'gzclient.exe'):
        assert execution.heavy_process({'name': name, 'cmdline': [name]})
    assert execution.heavy_process({'name': 'python.exe', 'cmdline': ['python', 'open_vins/consumer.py']})
    assert not execution.heavy_process({'name': 'git.exe', 'cmdline': ['git', '-C', 'open_vins', 'status']})


def test_timeout_without_inside_identity_records_unknown_residual(tmp_path, monkeypatch):
    execution = api().execution
    class Process:
        pid = 12345
        terminated = False
        def wait(self, timeout):
            if self.terminated:
                return 1
            raise subprocess.TimeoutExpired('owned-launcher', timeout)
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
    process = Process()
    monkeypatch.setattr(execution, 'linux', lambda path: str(path))
    monkeypatch.setattr(execution, 'wsl', lambda *args, **kwargs: SimpleNamespace(stdout=b'LoadState=not-found\n'))
    monkeypatch.setattr(execution.subprocess, 'Popen', lambda *args, **kwargs: process)
    with pytest.raises(RuntimeError, match='ownership unknown'):
        execution.scoped(tmp_path / 'scope', ['command'], label='test', memory=1, seconds=1)
    record = json.loads((tmp_path / 'scope/timeout-ownership-unknown.json').read_text())
    assert record['owned_group_released'] is None
    assert record['launcher_pid'] == 12345
    assert process.terminated


@pytest.mark.parametrize('live_id', ['owned-id', 'other-id'])
def test_scope_stop_requires_observed_invocation_and_group(tmp_path, monkeypatch, live_id):
    execution = api().execution
    unit = 'declared.scope'
    group = '/user.slice/' + unit
    calls = []
    def observe(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=(f'InvocationID={live_id}\nControlGroup={group}\n').encode(), stderr=b'')
    monkeypatch.setattr(execution, 'wsl', observe)
    inside = {'cgroup': group, 'systemd_properties': f'InvocationID=owned-id\nControlGroup={group}\n'}
    if live_id == 'other-id':
        with pytest.raises(RuntimeError, match='ownership unknown'):
            execution.stop_owned(tmp_path, unit, inside, 'stop.json')
        assert not any('stop' in argv for argv in calls)
    else:
        execution.stop_owned(tmp_path, unit, inside, 'stop.json')
        assert calls[-1] == ('systemctl', '--user', 'stop', unit)


def test_first_refusal_retains_exact_admission_without_reserving_runtime(tmp_path, monkeypatch):
    module = api()
    study = tmp_path / 'study'
    record = tmp_path / 'fresh-admission.json'
    facts = {'admitted': False, 'windows_available': 1234}
    monkeypatch.setattr(module, 'STUDY', study)
    monkeypatch.setattr(module, 'cached_admission', lambda: facts)
    with pytest.raises(RuntimeError, match='fresh admission refused'):
        module.execute(admission_record=record)
    assert json.loads(record.read_text()) == facts
    assert not study.exists()
