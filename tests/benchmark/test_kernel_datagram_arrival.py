"""Fake sockets/clocks on Windows; actual WSL receive study is separate."""

import copy
import hashlib
import json
import socket
import struct

import pytest

from tools.benchmark.kernel_datagram_arrival import KernelTimestampNS
from tools.benchmark.openvins_datagram_receive import DatagramReceiver

ABI = {
    "schema": "flydrones.kernel_timestampns_new_abi.v1", "machine": "x86_64", "byteorder": "little",
    "pointer_bytes": 8, "sol_socket": 1, "so_timestampns_new": 64, "cmsg_type": 64,
    "timespec_bytes": 16, "sec_offset": 0, "sec_bytes": 8, "nsec_offset": 8, "nsec_bytes": 8,
    "cmsg_space": 32, "msg_dontwait": 64, "msg_trunc": 32, "msg_ctrunc": 8,
}
RAW = (json.dumps(ABI, separators=(",", ":")) + "\n").encode()
SHA = hashlib.sha256(RAW).hexdigest()


def test_decoding_kernel_metadata_never_qualifies_actual_receive_instant():
    profile = KernelTimestampNS(RAW, SHA)
    assert profile.evidence["kernel_receive_instant_qualified"] is False


@pytest.fixture(autouse=True)
def linux_receive_flag(monkeypatch):
    monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)


class FakeSocket:
    family, type, proto = socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP

    def __init__(self):
        self.local = ("0.0.0.0", 0)
        self.timeout = 0.0
        self.options = {}
        self.calls = []
        self.result = (b"opaque", [(1, 64, struct.pack("<qq", 1, 250))], 0, DatagramReceiver.PEER)
        self.hook = None

    def fileno(self):
        return 19

    def getsockname(self):
        return self.local

    def gettimeout(self):
        return self.timeout

    def setsockopt(self, level, option, value):
        self.calls.append(("setsockopt", level, option, value))
        self.options[level, option] = value

    def getsockopt(self, level, option):
        return self.options.get((level, option), 0)

    def recvmsg(self, *args):
        self.calls.append(("recvmsg", *args))
        if self.hook:
            self.hook()
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Rig:
    def __init__(self):
        self.now = 100
        self.real = 2_000_000_000
        self.events = []
        self.sock = FakeSocket()
        self.kernel = KernelTimestampNS(RAW, SHA, realtime_ns=lambda: self.real)
        self.kernel.enable_before_bind(self.sock)
        self.sock.local = DatagramReceiver.LOCAL
        self.receiver = DatagramReceiver(
            self.sock, lambda: None, lambda: self.now, self.now,
            lambda event: self.events.append(copy.deepcopy(event)), kernel_timestamps=self.kernel,
        )


def test_prebind_enable_and_buffer_are_used_without_relabelling_monotonic_time():
    rig = Rig()
    packet = rig.receiver.poll()
    assert packet.received_ns == 100
    assert packet.kernel_received_realtime_ns == 1_000_000_250
    assert rig.sock.calls == [("setsockopt", 1, 64, 1), ("recvmsg", 4096, 32, 64)]
    returned = next(event for event in rig.events if event["kind"] == "receive_return")
    assert returned["ancillary_raw"][0]["data_hex"] == struct.pack("<qq", 1, 250).hex()
    assert returned["kernel_realtime_before_ns"] == returned["kernel_realtime_after_ns"] == 2_000_000_000
    assert not rig.receiver.evidence["kernel_timestamps"]["clock_mapping_qualified"]
    assert not rig.receiver.progress["network_authorized"]


def test_bound_socket_cannot_gain_retroactive_arrival_timestamps():
    sock = FakeSocket()
    sock.local = DatagramReceiver.LOCAL
    profile = KernelTimestampNS(RAW, SHA)
    with pytest.raises(ValueError, match="before bind"):
        profile.enable_before_bind(sock)
    assert not sock.calls


def test_boolean_unbound_port_is_not_a_valid_socket_observation():
    sock = FakeSocket()
    sock.local = ("0.0.0.0", False)
    profile = KernelTimestampNS(RAW, SHA)
    with pytest.raises(ValueError, match="before bind"):
        profile.enable_before_bind(sock)
    assert not sock.calls


def test_option_drift_refuses_before_any_receive():
    rig = Rig()
    rig.sock.options[1, 64] = 0
    with pytest.raises(ValueError, match="timestamp option"):
        rig.receiver.poll()
    assert not any(call[0] == "recvmsg" for call in rig.sock.calls)
    assert rig.receiver.progress["failure"]


@pytest.mark.parametrize("ancillary,flags", [
    ([], 0), ([(1, 64, b"short")], 0), ([(1, 35, struct.pack("<qq", 1, 0))], 0),
    ([(1, 64, struct.pack("<qq", 1, 1_000_000_000))], 0),
    ([(1, 64, struct.pack("<qq", -1, 0))], 0),
    ([(1, 64, struct.pack("<qq", 3, 0))], 0),
    ([(1, 64, struct.pack("<qq", 1, 0))] * 2, 0),
    ([(1, 64, struct.pack("<qq", 1, 0))], 8),
    ([(1, 64, struct.pack("<qq", 1, 0))], 32),
])
def test_invalid_metadata_retained_then_failure_latches(ancillary, flags):
    rig = Rig()
    rig.sock.result = (b"opaque", ancillary, flags, DatagramReceiver.PEER)
    with pytest.raises(ValueError):
        rig.receiver.poll()
    assert any(event["kind"] == "receive_return" for event in rig.events)
    with pytest.raises(ValueError, match="latched"):
        rig.receiver.poll()
    assert len([call for call in rig.sock.calls if call[0] == "recvmsg"]) == 1


def test_realtime_regression_after_read_keeps_raw_ancillary():
    rig = Rig()
    rig.sock.hook = lambda: setattr(rig, "real", 1)
    with pytest.raises(ValueError, match="realtime"):
        rig.receiver.poll()
    returned = next(event for event in rig.events if event["kind"] == "receive_return")
    assert returned["data_hex"] == b"opaque".hex()
    assert returned["ancillary_raw"][0]["data_hex"] == struct.pack("<qq", 1, 250).hex()


def test_monotonic_failure_does_not_invent_a_post_read_realtime_observation():
    rig = Rig()
    rig.sock.hook = lambda: setattr(rig, "now", 99)
    with pytest.raises(ValueError, match="clock"):
        rig.receiver.poll()
    returned = next(event for event in rig.events if event["kind"] == "receive_return")
    assert returned["kernel_realtime_after_ns"] is None
    assert returned["kernel_realtime_after_raw_ns"] is None
    assert returned["ancillary_raw"][0]["data_hex"] == struct.pack("<qq", 1, 250).hex()


def test_latched_profile_does_not_reuse_a_before_read_time_as_after_read_time():
    rig = Rig()

    def latch_during_read():
        with pytest.raises(ValueError):
            rig.kernel.enable_before_bind(rig.sock)

    rig.sock.hook = latch_during_read
    with pytest.raises(ValueError, match="kernel timestamp"):
        rig.receiver.poll()
    returned = next(event for event in rig.events if event["kind"] == "receive_return")
    assert returned["kernel_realtime_before_ns"] == 2_000_000_000
    assert returned["kernel_realtime_after_ns"] is None
    assert returned["kernel_realtime_after_raw_ns"] is None


def test_kernel_timestamp_regression_refuses():
    rig = Rig()
    rig.receiver.poll()
    rig.sock.result = (b"next", [(1, 64, struct.pack("<qq", 1, 249))], 0, DatagramReceiver.PEER)
    with pytest.raises(ValueError, match="regress"):
        rig.receiver.poll()


@pytest.mark.parametrize("changed", [{"so_timestampns_new": 35}, {"sec_bytes": 4},
                                    {"sol_socket": True}, {"schema": "other"}, {"unknown": 1}])
def test_unknown_or_malformed_abi_refuses(changed):
    raw = json.dumps({**ABI, **changed}).encode()
    with pytest.raises(ValueError, match="ABI"):
        KernelTimestampNS(raw, hashlib.sha256(raw).hexdigest())
