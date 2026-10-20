"""Real local append-only files. Does not create network or simulation objects."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest


def new(path):
    name = 'tools.benchmark.openvins_segmented_journal'
    assert importlib.util.find_spec(name) is not None, 'segmented lifecycle storage missing'
    return importlib.import_module(name).SegmentedWireJournal(path)


def read_all(evidence):
    rows = []
    for member in evidence['segments']:
        data = (Path(evidence['directory']) / member['name']).read_bytes()
        assert len(data) == member['bytes']
        assert hashlib.sha256(data).hexdigest() == member['sha256']
        items = [json.loads(line) for line in data.splitlines()]
        assert len(items) == member['records']
        assert items[0]['index'] == member['first_index']
        assert items[-1]['index'] == member['last_index']
        rows.extend(items)
    assert [row['index'] for row in rows] == list(range(len(rows)))
    return rows


def test_shared_segments_cross8192_preserve_indices_bytes_and_channel_refs(tmp_path):
    store = new(tmp_path / 'wire')
    left, right = store.channel('wire'), store.channel('receiver')
    for index in range(8200):
        channel = left if index % 2 == 0 else right
        channel.append({'kind': 'packet', 'value': index})
    assert len(left) == len(right) == 4100
    # An evidence getter never seals a partial segment or copies its history.
    before = copy.deepcopy(left)
    assert before['channel'] == 'wire' and before['records'] == 4100
    assert before['journal']['active']['records'] == 8
    assert len(before['journal']['segments']) == 1
    store.close()
    evidence = store.evidence
    assert evidence['closed'] and evidence['failure'] is None
    assert evidence['active'] is None
    rows = read_all(evidence)
    assert [len((Path(evidence['directory']) / m['name']).read_bytes().splitlines())
            for m in evidence['segments']] == [8192, 8]
    assert [row['source_index'] for row in rows if row['source'] == 'wire'] == list(range(4100))
    assert [row['event']['value'] for row in rows] == list(range(8200))
    assert all(row['phase'] == 'bootstrap' for row in rows)
    assert json.loads((tmp_path / 'wire' / 'manifest.json').read_text())['segments'] == evidence['segments']
    with pytest.raises(ValueError):
        left.append({'kind': 'too late'})
    assert len(read_all(store.evidence)) == 8200


def test_existing_directory_and_segment_are_never_overwritten(tmp_path):
    old = tmp_path / 'wire'
    old.mkdir()
    sentinel = old / 'keep.txt'
    sentinel.write_text('old failure')
    with pytest.raises((ValueError, FileExistsError)):
        new(old)
    assert sentinel.read_text() == 'old failure'
    store = new(tmp_path / 'next')
    channel = store.channel('wire')
    (tmp_path / 'next' / 'segment-0000.jsonl').write_bytes(b'old evidence')
    with pytest.raises((ValueError, FileExistsError)):
        channel.append({'kind': 'new'})
    store.close()
    assert (tmp_path / 'next' / 'segment-0000.jsonl').read_bytes() == b'old evidence'
    assert store.evidence['failure']


@pytest.mark.parametrize('fault', ['short-write', 'flush', 'close', 'corrupt'])
def test_io_refusal_retains_failed_file_and_prevents_future_append(tmp_path, monkeypatch, fault):
    store = new(tmp_path / 'wire')
    channel = store.channel('wire')
    original = Path.open

    class Writer:
        def __init__(self, path, file):
            self.path, self.file = path, file

        def write(self, data):
            if fault == 'short-write':
                return self.file.write(data[:7])
            return self.file.write(data)

        def flush(self):
            if fault == 'flush':
                raise OSError('flush refused')
            return self.file.flush()

        def close(self):
            self.file.close()
            if fault == 'close':
                raise OSError('close refused')
            if fault == 'corrupt':
                with original(self.path, 'ab') as target:
                    target.write(b'corrupt')

    def opening(path, mode='r', *args, **kwargs):
        file = original(path, mode, *args, **kwargs)
        return Writer(path, file) if path.name.startswith('segment-') and mode == 'xb' else file

    monkeypatch.setattr(Path, 'open', opening)
    if fault == 'short-write':
        with pytest.raises(ValueError):
            channel.append({'kind': 'packet', 'raw_hex': '010203'})
    else:
        channel.append({'kind': 'packet', 'raw_hex': '010203'})
    store.close()
    evidence = store.evidence
    assert evidence['failure'] and not evidence['complete_retention']
    assert list((tmp_path / 'wire').glob('segment-*.jsonl'))
    assert evidence['unsealed']
    with pytest.raises(ValueError):
        channel.append({'kind': 'forbidden'})


def test_failure_slot_keeps_original_primary_and_rejects_replacement(tmp_path):
    store = new(tmp_path / 'wire')
    channel = store.channel('wire')
    channel.append({'kind': 'packet', 'raw_hex': 'ab'})
    # A rejected JSON value fails the shared journal, not just one producer.
    with pytest.raises(ValueError):
        channel.append({'kind': 'bad', 'number': float('nan')})
    reason = store.evidence['failure']
    channel.record_failure({'kind': 'refusal', 'reason': 'first'})
    channel.record_failure({'kind': 'refusal', 'reason': 'second'})
    store.close()
    assert store.evidence['failure'] == reason
    assert store.evidence['unpersisted_failures']['wire']['reason'] == 'first'
    assert read_all(store.evidence)[0]['event']['raw_hex'] == 'ab'


def test_phase_change_is_monotonic_and_channels_are_not_reopened(tmp_path):
    store = new(tmp_path / 'wire')
    channel = store.channel('owned')
    channel.append({'kind': 'start'})
    store.phase('maintenance')
    channel.append({'kind': 'status'})
    store.phase('stopping')
    channel.append({'kind': 'cancel'})
    with pytest.raises(ValueError):
        store.phase('bootstrap')
    with pytest.raises(ValueError):
        store.channel('owned')
    store.close()
    assert [row['phase'] for row in read_all(store.evidence)] == ['bootstrap', 'maintenance', 'stopping']


def test_segment_capacity_is_shared_across_producers_not_reset_per_channel(tmp_path, monkeypatch):
    store = new(tmp_path / 'wire')
    # Scaled boundary test; full profile exhaustion is exercised by a separate
    # actual-file harness, not falsely inferred from this smaller fixture.
    monkeypatch.setattr(type(store), 'EVENTS_PER_SEGMENT', 2)
    left, right = store.channel('wire'), store.channel('receiver')
    for index in range(128):
        (left if index % 2 else right).append({'kind': 'small', 'value': index})
    with pytest.raises(ValueError, match='segment|capacity'):
        left.append({'kind': 'overflow'})
    store.close()
    assert len(store.evidence['segments']) == 64
    assert len(read_all(store.evidence)) == 128


def test_byte_quota_rejects_before_writing_an_extra_record(tmp_path, monkeypatch):
    store = new(tmp_path / 'wire')
    monkeypatch.setattr(type(store), 'MAX_BYTES', 1024)
    channel = store.channel('wire')
    for index in range(3):
        channel.append({'kind': 'record', 'raw': 'x' * 150, 'value': index})
    with pytest.raises(ValueError, match='byte|capacity'):
        channel.append({'kind': 'overflow', 'raw': 'x' * 400})
    store.close()
    assert store.evidence['bytes'] <= 1024
    assert len(read_all(store.evidence)) == 3


def test_close_reentry_cannot_publish_manifest_before_the_member_is_closed(tmp_path, monkeypatch):
    store = new(tmp_path / 'wire')
    channel = store.channel('wire')
    original = Path.open
    outcomes = []

    class Writer:
        def __init__(self, file):
            self.file = file

        def write(self, data):
            return self.file.write(data)

        def flush(self):
            try:
                store.close()
            except ValueError:
                outcomes.append('refused')
            else:
                outcomes.append('returned')
            return self.file.flush()

        def close(self):
            return self.file.close()

    def opening(path, mode='r', *args, **kwargs):
        file = original(path, mode, *args, **kwargs)
        return Writer(file) if path.name.startswith('segment-') and mode == 'xb' else file

    monkeypatch.setattr(Path, 'open', opening)
    channel.append({'kind': 'packet'})
    store.close()
    assert outcomes == ['refused']
    assert store.evidence['failure']
    assert not store.evidence['complete_retention']
    assert len(read_all(store.evidence)) == 1


def test_manifest_close_failure_does_not_leave_a_manifest_claiming_success(tmp_path, monkeypatch):
    store = new(tmp_path / 'wire')
    store.channel('wire').append({'kind': 'packet'})
    original = Path.open

    class Manifest:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def write(self, data):
            return self.file.write(data)

        def flush(self):
            return self.file.flush()

        def __exit__(self, *args):
            self.file.close()
            raise OSError('manifest close refused')

    def opening(path, mode='r', *args, **kwargs):
        file = original(path, mode, *args, **kwargs)
        return Manifest(file) if path.name == 'manifest.json' and mode == 'xb' else file

    monkeypatch.setattr(Path, 'open', opening)
    store.close()
    assert store.evidence['failure']
    manifest = json.loads((tmp_path / 'wire' / 'manifest.json').read_text())
    assert manifest['complete_retention'] is False
    assert len(read_all(store.evidence)) == 1
