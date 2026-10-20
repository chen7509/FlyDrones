"""Owned read-only PX4 daemon startup query, with external socket/clock fakes."""

import copy
from types import SimpleNamespace

import pytest

from tools.benchmark.px4_owned_startup_probe import OwnedMavlinkStatusProbe, StatusProbeRefusal

OWNER = dict(pid=321, pgrp=321, session=321, start_ticks=77, uid=1000, gid=1000,
             exe='/usr/bin/px4', exe_device=8, exe_inode=11, cwd='/tmp/run',
             cwd_device=8, cwd_inode=12, net='net:[100]', user='user:[101]')
STATUS = (b'\ninstance #0:\n\tmavlink chan: #0\n\tmode: Normal\n'
          b'\ttransport protocol: UDP (18578, remote port: 14550)\n'
          b'\ninstance #1:\n\tmavlink chan: #1\n\tmode: Onboard\n'
          b'\ttransport protocol: UDP (14588, remote port: 14548)\n')


class Socket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = bytearray()
        self.closed = 0
        self.send_limit = None

    def setblocking(self, value):
        assert value is False

    def send(self, data):
        count = min(len(data), self.send_limit or len(data))
        self.sent.extend(data[:count])
        return count

    def recv(self, count):
        assert count == 4096
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Backend:
    def __init__(self, chunks):
        self.now = 10
        self.owner = copy.deepcopy(OWNER)
        self.peer_value = dict(pid=321, uid=1000, gid=1000)
        self.sock = Socket(chunks)

    def clock(self):
        return self.now

    def observe(self, process):
        assert process.pid == 321
        return copy.deepcopy(self.owner)

    def connect(self, path, timeout):
        assert path == '/tmp/private/socket' and 0 < timeout <= 2
        return self.sock

    def peer(self, connection):
        assert connection is self.sock
        return copy.deepcopy(self.peer_value)

    def close(self, connection):
        assert connection is self.sock
        connection.closed += 1


def make_probe(chunks, journal=None):
    backend = Backend(chunks)
    events = []
    probe = OwnedMavlinkStatusProbe(
        SimpleNamespace(pid=321), OWNER, '/tmp/private/socket', 10, 2_000_000_010,
        events.append if journal is None else journal, backend=backend)
    return probe, backend, events


def test_exact_read_only_command_and_split_status_frame():
    probe, backend, events = make_probe([STATUS[:24], STATUS[24:] + b'\0', b'\0', b''])
    assert probe.poll() is None
    assert probe.poll() is None
    assert probe.poll() is None
    result = probe.poll()
    assert result['phase'] == 'ready' and result['instance'] == 1
    assert result['authority'] is False and result['fusion_qualified'] is False
    assert backend.sock.sent == b'mavlink status\0'
    assert backend.sock.closed == 1
    evidence = probe.evidence
    assert evidence['raw_stdout_hex'] == STATUS.hex()
    assert evidence['raw_trailer_hex'] == '0000'
    assert evidence['exit_code'] == 0 and evidence['transport_complete'] is True
    assert [event['kind'] for event in events].count('recv_return') == 4


def test_partial_send_then_nonzero_no_instance_is_only_pending():
    probe, backend, _ = make_probe([b'\0\x01', b''])
    backend.sock.send_limit = 4
    for _ in range(4):
        assert probe.poll() is None
    result = probe.poll()
    assert result['phase'] == 'pending' and result['reason'] == 'no-instances'
    assert result['authority'] is False and result['fusion_qualified'] is False
    assert backend.sock.sent == b'mavlink status\0'
    assert backend.sock.closed == 1
    assert probe.evidence['exit_code'] == 1


@pytest.mark.parametrize('chunks', [
    [STATUS + b'\0\0extra', b''],
    [STATUS + b'\0\x02', b''],
    [STATUS + b'\0\0'],
    [b'\0\0', b''],
])
def test_malformed_or_incomplete_reply_latches_failure(chunks):
    probe, backend, _ = make_probe(chunks)
    with pytest.raises(StatusProbeRefusal):
        while True:
            probe.poll()
    assert backend.sock.closed == 1
    assert probe.evidence['transport_complete'] is False
    assert probe.evidence['error']


@pytest.mark.parametrize('drift', ['owner', 'peer', 'deadline', 'regression', 'journal'])
def test_drift_or_journal_failure_refuses_before_success(drift):
    probe, backend, _ = make_probe([STATUS + b'\0\0', b''])
    if drift == 'owner':
        backend.owner['start_ticks'] += 1
    elif drift == 'peer':
        backend.peer_value['pid'] += 1
    elif drift == 'deadline':
        backend.now = 2_000_000_010
    elif drift == 'regression':
        backend.now = 9
    else:
        probe._journal = lambda event: (_ for _ in ()).throw(OSError('journal failure'))
    with pytest.raises(StatusProbeRefusal):
        probe.poll()
    assert backend.sock.closed == 1
    assert probe.evidence['transport_complete'] is False


def test_nonblocking_empty_read_is_not_eof():
    probe, backend, _ = make_probe([BlockingIOError(), b'\0\x01', b''])
    assert probe.poll() is None
    assert probe.poll() is None
    assert probe.poll()['phase'] == 'pending'
    assert backend.sock.closed == 1


def test_returned_send_is_preserved_when_clock_read_fails_after_syscall():
    probe, backend, _ = make_probe([b'\0\x01', b''])
    send = backend.sock.send

    def fail_clock_after_send(data):
        count = send(data)
        backend.clock = lambda: (_ for _ in ()).throw(OSError('clock failed'))
        return count

    backend.sock.send = fail_clock_after_send
    with pytest.raises(StatusProbeRefusal):
        probe.poll()
    returns = [event for event in probe.evidence['events'] if event['kind'] == 'send_return']
    assert len(returns) == 1 and returns[0]['count'] == len(b'mavlink status\0')
    assert 'OSError' in returns[0]['clock_error']
    assert probe.evidence['transport_complete'] is False
    assert backend.sock.closed == 1
