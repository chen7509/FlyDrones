"""Return-byte/timestamp evidence must survive clocks or storage refusing it."""
import socket

import pytest

from tests.benchmark.test_openvins_datagram_receive import Rig
from tests.benchmark.test_openvins_segmented_journal import read_all
from tools.benchmark.openvins_datagram_receive import DatagramReceiver
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


@pytest.mark.parametrize('fault', ['none', 'expired-clock', 'storage-after-read', 'reentry'])
def test_segmented_receive_retains_return_bytes_without_fabricating_a_time(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(socket, 'MSG_DONTWAIT', 64, raising=False)
    rig = Rig()
    store = SegmentedWireJournal(tmp_path / 'records')
    rig.obj = DatagramReceiver(rig.sock, rig.guard, rig.clock, 100, rig.journal, retention=store)

    def returned():
        if fault == 'expired-clock':
            rig.now = 8_000_000_100
        elif fault == 'storage-after-read':
            store.MAX_BYTES = store.evidence['bytes'] + 1
        elif fault == 'reentry':
            with pytest.raises(ValueError):
                rig.obj.check()

    rig.sock.hook = returned
    if fault == 'none':
        assert rig.obj.poll().data == b'packet'
    else:
        with pytest.raises(ValueError):
            rig.obj.poll()
        assert rig.obj.progress['failure']
    store.close()
    assert rig.sock.calls == [(4096, 0, 64)]
    rows = [row['event'] for row in read_all(store.evidence) if row['event']['kind'] == 'receive_return']
    if fault == 'storage-after-read':
        assert rows == []
        draft = rig.obj.evidence['unpublished_event']
        assert draft['data_hex'] == '7061636b6574'
        assert draft['received_ns'] == 100
        assert not store.evidence['complete_retention']
    else:
        assert len(rows) == 1
        assert rows[0]['data_hex'] == '7061636b6574'
        assert rows[0]['received_ns'] == (100 if fault == 'none' else None)
        assert rig.obj.evidence['unpublished_event'] is None
