"""No real socket: every socket operation is a deterministic injected object."""
import copy
import socket
from dataclasses import FrozenInstanceError

import pytest

from tools.benchmark.openvins_datagram_receive import DatagramReceiver


@pytest.fixture(autouse=True)
def synthetic_linux_flag(monkeypatch):
    # Installed WSL constant observed read-only; Windows does not execute UDP.
    monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)


class FakeSocket:
    family, type, proto = socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP

    def __init__(self):
        self.local = ("127.0.0.1", 14548)
        self.timeout = 0.0
        self.result = (b"packet", [], 0, ("127.0.0.1", 14588))
        self.calls = []
        self.hook = None

    def gettimeout(self):
        return self.timeout

    def getsockname(self):
        return self.local

    def recvmsg(self, *args):
        self.calls.append(args)
        if self.hook:
            self.hook()
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Rig:
    def __init__(self):
        self.sock, self.events, self.now = FakeSocket(), [], 100
        self.clock_hook = self.guard_hook = self.journal_hook = None
        self.obj = DatagramReceiver(self.sock, self.guard, self.clock, self.now, self.journal)

    def clock(self):
        return self.clock_hook() if self.clock_hook else self.now

    def guard(self):
        if self.guard_hook:
            return self.guard_hook()

    def journal(self, event):
        self.events.append(copy.deepcopy(event))
        if self.journal_hook:
            return self.journal_hook(event)


def test_check_revalidates_without_consuming_or_refreshing():
    r = Rig()
    assert r.obj.check() is None
    assert r.sock.calls == []
    assert r.obj.progress['failure'] is None
    r.sock.local = ('127.0.0.1', 1)
    with pytest.raises(ValueError, match='local endpoint'):
        r.obj.check()
    assert r.obj.progress['failure']
    assert r.sock.calls == []


def test_check_reentry_latches_without_second_read():
    r = Rig()
    def reenter():
        with pytest.raises(ValueError, match='concurrent'):
            r.obj.check()
    r.guard_hook = reenter
    with pytest.raises(ValueError, match='latched'):
        r.obj.check()
    assert r.sock.calls == []


def test_stdlib_msgflag_enum_accepted(monkeypatch):
    # Same enum type returned by installed WSL socket.MSG_DONTWAIT; still fake I/O.
    monkeypatch.setattr(socket, 'MSG_DONTWAIT', socket.MsgFlag(64))
    r = Rig()
    assert r.obj.poll().data == b'packet'


def test_normal_packet_immutable_and_no_authority():
    r = Rig()
    packet = r.obj.poll()
    assert (packet.data, packet.peer, packet.received_ns) == (b"packet", ("127.0.0.1", 14588), 100)
    assert r.sock.calls == [(4096, 0, 64)]
    with pytest.raises(FrozenInstanceError):
        packet.received_ns = 200
    assert not any(r.obj.evidence[key] for key in (
        "sender_process_proven", "network_authorized", "live_convergence_qualified", "fusion_qualified"))


def test_not_ready_checks_health_without_fabricating_packet():
    r = Rig()
    r.sock.result = BlockingIOError()
    assert r.obj.poll() is None
    assert r.sock.calls == [(4096, 0, 64)]
    assert not any(e["kind"] == "receive_return" for e in r.obj.evidence["events"])


@pytest.mark.parametrize("returned", [
    (b"", [], 0, ("127.0.0.1", 14588)),
    (b"x" * 4097, [], 0, ("127.0.0.1", 14588)),
    (bytearray(b"x"), [], 0, ("127.0.0.1", 14588)),
    (b"x", [], socket.MSG_TRUNC, ("127.0.0.1", 14588)),
    (b"x", [], 8, ("127.0.0.1", 14588)),
    (b"x", [], True, ("127.0.0.1", 14588)),
    (b"x", [(1, 2, b"stamp")], 0, ("127.0.0.1", 14588)),
    (b"x", (), 0, ("127.0.0.1", 14588)),
    (b"x", [], 0, ("127.0.0.2", 14588)),
    (b"x", [], 0, ("127.0.0.1", 14589)),
    (b"x", [], 0, ("127.0.0.1", True)),
    (b"x", [], 0, ["127.0.0.1", 14588]),
    (b"x", [], 0),
])
def test_bad_datagrams_preserve_refusal_and_cannot_repoll(returned):
    r = Rig()
    r.sock.result = returned
    with pytest.raises(ValueError):
        r.obj.poll()
    assert r.obj.evidence["failure"]
    assert any(e["kind"] == "receive_return" for e in r.obj.evidence["events"])
    with pytest.raises(ValueError):
        r.obj.poll()
    assert len(r.sock.calls) == 1


@pytest.mark.parametrize("field,value", [("family", socket.AF_INET6), ("type", socket.SOCK_STREAM),
    ("proto", True), ("timeout", None), ("timeout", 2), ("timeout", False),
    ("local", ("0.0.0.0", 14548)), ("local", ("127.0.0.1", 1))])
def test_socket_drift_prevents_read(field, value):
    r = Rig()
    setattr(r.sock, field, value)
    with pytest.raises(ValueError):
        r.obj.poll()
    assert not r.sock.calls


@pytest.mark.parametrize("now", [99, True, 100 + 8_000_000_000])
def test_clock_refusal_before_read(now):
    r = Rig()
    r.now = now
    with pytest.raises(ValueError):
        r.obj.poll()
    assert not r.sock.calls


@pytest.mark.parametrize("fault", ["clock", "guard", "journal", "timeout"])
def test_post_receive_failure_retains_returned_bytes(fault):
    r = Rig()
    def fail():
        raise OSError("after consume")
    def hook():
        if fault == "clock":
            r.clock_hook = fail
        if fault == "guard":
            r.guard_hook = fail
        if fault == "timeout":
            r.now += 2_000_000_000
    r.sock.hook = hook
    if fault == "journal":
        def journal(event):
            if event["kind"] == "receive_return":
                fail()
        r.journal_hook = journal
    with pytest.raises(ValueError):
        r.obj.poll()
    rows = [e for e in r.obj.evidence["events"] if e["kind"] == "receive_return"]
    assert len(rows) == 1 and rows[0]["data_hex"] == b"packet".hex()
    assert len(r.sock.calls) == 1


def test_journal_reentry_refuses_before_consume():
    r = Rig()
    def hook(event):
        if event["kind"] == "receive_attempt":
            with pytest.raises(ValueError):
                r.obj.poll()
    r.journal_hook = hook
    with pytest.raises(ValueError):
        r.obj.poll()
    assert not r.sock.calls


def test_guard_before_read_failure_and_non_none_refuse():
    for value in (False, {"okay": True}):
        r = Rig()
        r.guard_hook = lambda value=value: value
        with pytest.raises(ValueError):
            r.obj.poll()
        assert not r.sock.calls


def test_journal_mutation_cannot_change_internal_record_or_return():
    r = Rig()
    def hook(event):
        event.clear()
    r.journal_hook = hook
    assert r.obj.poll().data == b"packet"
    assert any(e.get("data_hex") == b"packet".hex() for e in r.obj.evidence["events"])


def test_event_capacity_refuses_before_read():
    r = Rig()
    r.obj.MAX_EVENTS = 1
    with pytest.raises(ValueError):
        r.obj.poll()
    assert not r.sock.calls


def test_empty_polls_do_not_extend_global_deadline():
    r = Rig()
    r.sock.result = BlockingIOError()
    assert r.obj.poll() is None
    r.now += 8_000_000_000
    with pytest.raises(ValueError):
        r.obj.poll()
    assert len(r.sock.calls) == 1


def test_reentry_during_receive_at_capacity_keeps_return_bytes():
    r = Rig()
    r.obj.MAX_EVENTS = 2
    def hook():
        with pytest.raises(ValueError):
            r.obj.poll()
    r.sock.hook = hook
    with pytest.raises(ValueError):
        r.obj.poll()
    rows = [e for e in r.obj.evidence["events"] if e["kind"] == "receive_return"]
    assert len(rows) == 1 and rows[0]["data_hex"] == b"packet".hex()
    assert len(r.sock.calls) == 1


@pytest.mark.parametrize("field,value", [("family", 2.0), ("type", 2.0), ("proto", 17.0)])
def test_float_socket_metadata_refused(field, value):
    r = Rig()
    setattr(r.sock, field, value)
    with pytest.raises(ValueError):
        r.obj.poll()
    assert not r.sock.calls


def test_alias_blocking_mode_requires_per_call_nonblocking_flag():
    r = Rig()
    def alias_mode():
        if r.sock.calls[-1][2] != 64:
            raise RuntimeError("synthetic alias would block without per-call flag")
    r.sock.hook = alias_mode
    assert r.obj.poll().data == b"packet"


def test_missing_nonblocking_flag_refuses_before_socket_read(monkeypatch):
    monkeypatch.delattr(socket, "MSG_DONTWAIT")
    with pytest.raises(ValueError, match="MSG_DONTWAIT"):
        Rig()
