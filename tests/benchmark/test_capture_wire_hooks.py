"""Actual capture hooks and journal; local files/injected callbacks, no runtime."""
import json
from types import SimpleNamespace

import pytest

from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark import disarmed_sensor_provenance as provenance


def heartbeat(**changes):
    return dict(kind='heartbeat', arrival_monotonic_ns=10, observed_sim_ns=1_000_000,
                system_id=9, base_mode=0, custom_mode=0, **changes)


@pytest.mark.parametrize('where', ['body', 'restore', 'both'])
@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
def test_interrupt_still_attempts_owned_cleanup_and_persists_failed_result(tmp_path, where, exception):
    called = []
    result = dict(status='capture_completed', errors=[])
    first = exception('original stop')
    second = KeyboardInterrupt('cleanup stop')
    def restore():
        called.append('restore')
        if where in ('restore', 'both'):
            raise first if where == 'restore' else second
    with pytest.raises((KeyboardInterrupt, SystemExit)) as caught:
        with provenance.CaptureJournal(tmp_path, result) as journal:
            journal.cleanup('ULog', lambda: called.append('ulog'), priority=100)
            journal.cleanup('owned PX4', lambda: called.append('px4'), priority=20)
            journal.cleanup('receiver restoration', restore, priority=15)
            if where in ('body', 'both'):
                raise first
    assert caught.value is first
    assert called == ['restore', 'px4', 'ulog']
    saved = json.loads((tmp_path / 'result.json').read_text())
    assert saved['status'] == 'capture_failed'
    assert 'original stop' in str(saved['errors'])
    if where == 'both':
        assert 'cleanup stop' in str(saved['errors'])


def test_unprintable_cleanup_error_cannot_skip_next_owner(tmp_path):
    class BadError(Exception):
        def __repr__(self):
            raise RuntimeError('repr unavailable')
    called = []
    def fail():
        raise BadError()
    result = dict(status='capture_completed', errors=[])
    with provenance.CaptureJournal(tmp_path, result) as journal:
        journal.cleanup('restore', fail, priority=15)
        journal.cleanup('PX4', lambda: called.append('px4'), priority=20)
    assert called == ['px4']
    assert result['status'] == 'capture_failed'
    assert result['errors']
    assert (tmp_path / 'result.json').is_file()


def test_terminal_write_failure_does_not_replace_original_interrupt(tmp_path):
    (tmp_path / 'result.json').write_text('preserved prior file')
    original = KeyboardInterrupt('original')
    called = []
    with pytest.raises(KeyboardInterrupt) as caught:
        with provenance.CaptureJournal(tmp_path, dict(status='incomplete', errors=[])) as journal:
            journal.cleanup('PX4', lambda: called.append('px4'), priority=20)
            raise original
    assert caught.value is original
    assert isinstance(caught.value.__cause__, FileExistsError)
    assert called == ['px4']
    assert (tmp_path / 'result.json').read_text() == 'preserved prior file'


def test_terminal_write_failure_cannot_leave_completed_result_in_memory(tmp_path):
    (tmp_path / 'result.json').write_text('preserved')
    result = dict(status='capture_completed', errors=[])
    with pytest.raises(FileExistsError):
        with provenance.CaptureJournal(tmp_path, result):
            pass
    assert result['status'] == 'capture_failed'
    assert result['errors']


@pytest.mark.parametrize('armed', [False, True])
def test_capture_sink_preserves_actual_arrival_and_records_arming(tmp_path, monkeypatch, armed):
    assert hasattr(capture, 'dispatch_capture_heartbeat'), 'actual capture heartbeat hook missing'
    monkeypatch.setattr(provenance.time, 'monotonic_ns', lambda: 1000)
    writer = provenance.CaptureWriter(tmp_path, start_worker=False)
    arming, ready, calls = {'unarmed_wall_ns': 9}, {'px4': False}, []
    binding = SimpleNamespace(required_owned={'px4'}, observe_owned=lambda *args: calls.append(args))
    event = heartbeat()
    event['base_mode'] = 128 if armed else 0
    try:
        if armed:
            with pytest.raises(ValueError, match='armed'):
                capture.dispatch_capture_heartbeat(event, writer, None, arming, binding, ready, {'px4': object()})
        else:
            capture.dispatch_capture_heartbeat(event, writer, None, arming, binding, ready, {'px4': object()})
    finally:
        writer.finish()
    rows = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
    if armed:
        assert rows == []
    else:
        assert rows[0]['arrival_monotonic_ns'] == 10
        assert rows[0]['observed_sim_ns'] == 1_000_000
    assert arming['unarmed_wall_ns'] == (None if armed else 10)
    assert calls == ([] if armed else [('px4', 'ready')])
    assert ready['px4'] is (not armed)


def test_mapping_failure_cannot_deliver_heartbeat_to_readiness(tmp_path, monkeypatch):
    assert hasattr(capture, 'dispatch_capture_heartbeat'), 'actual capture heartbeat hook missing'
    monkeypatch.setattr(provenance.time, 'monotonic_ns', lambda: 1000)
    writer = provenance.CaptureWriter(tmp_path, start_worker=False)
    arming, ready = {'unarmed_wall_ns': None}, {'px4': False}
    def fail(*args):
        raise OSError('mapping unavailable')
    binding = SimpleNamespace(required_owned={'px4'}, observe_owned=fail)
    try:
        with pytest.raises(OSError, match='mapping unavailable'):
            capture.dispatch_capture_heartbeat(heartbeat(), writer, None, arming, binding, ready, {'px4': object()})
    finally:
        summary = writer.finish()
    assert summary['written'].get('heartbeat', 0) == 0
    assert not ready['px4']
    assert arming['unarmed_wall_ns'] is None
