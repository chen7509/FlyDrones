"""Fake sockets only; installed ABI observations and native trial are separate."""
import hashlib
import json
import socket
import struct

import pytest

from tools.benchmark.kernel_rx_timestamping import KernelRXTimestamping
from tools.benchmark.openvins_datagram_receive import DatagramReceiver

ABI = {
    "schema": "flydrones.kernel_rx_timestamping_new_abi.v1", "machine": "x86_64", "byteorder": "little",
    "pointer_bytes": 8, "sol_socket": 1, "so_timestamping_new": 65, "cmsg_type": 65,
    "rx_software": 8, "report_software": 16,
    "forbidden_timestamp_old": 29, "forbidden_timestamp_new": 63,
    "forbidden_timestampns_old": 35, "forbidden_timestampns_new": 64,
    "timespec_bytes": 48, "element_bytes": 16, "ts0_offset": 0, "ts1_offset": 16, "ts2_offset": 32,
    "sec_offset": 0, "sec_bytes": 8, "nsec_offset": 8, "nsec_bytes": 8,
    "cmsg_space": 64, "msg_dontwait": 64, "msg_trunc": 32, "msg_ctrunc": 8,
}
RAW = json.dumps(ABI).encode()
SHA = hashlib.sha256(RAW).hexdigest()


class Sock:
    family, type, proto = socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP

    def __init__(self):
        self.local = ("0.0.0.0", 0)
        self.options = {29: 0, 63: 0, 35: 0, 64: 0}
        self.calls = []
        self.hook = None
        self.raw = struct.pack("<6q", 1, 250, 0, 0, 0, 0)

    def fileno(self): return 7
    def getsockname(self): return self.local
    def gettimeout(self): return 0.0
    def setsockopt(self, level, option, value):
        self.calls.append((level, option, value))
        self.options[option] = value
    def getsockopt(self, _level, option): return self.options.get(option, 0)
    def recvmsg(self, *args):
        self.calls.append(args)
        if self.hook:
            self.hook()
        return b"opaque", [(1, 65, self.raw)], 0, DatagramReceiver.PEER


def prepared():
    stamp = KernelRXTimestamping(RAW, SHA, realtime_ns=lambda: 1_000_001_000)
    sock = Sock()
    stamp.enable_before_bind(sock)
    sock.local = DatagramReceiver.LOCAL
    return sock, stamp


def test_generated_abi_and_flags_prepare_without_legacy_enable():
    sock, profile = prepared()
    assert sock.calls == [(1, 65, 24)]
    assert profile.ancillary_bytes == 64
    assert profile.evidence["kernel_receive_instant_qualified"] is False


@pytest.mark.parametrize("option", [29, 63, 35, 64])
def test_legacy_option_conflict_never_clears_or_enables(option):
    sock = Sock()
    sock.options[option] = 1
    profile = KernelRXTimestamping(RAW, SHA)
    with pytest.raises(ValueError, match="legacy"):
        profile.enable_before_bind(sock)
    assert sock.calls == [] and profile.evidence["failure"]


@pytest.mark.parametrize("value", [False, 0.0])
def test_legacy_zero_must_be_literal_integer(value):
    sock = Sock()
    sock.options[35] = value
    profile = KernelRXTimestamping(RAW, SHA)
    with pytest.raises(ValueError, match="legacy"):
        profile.enable_before_bind(sock)
    assert sock.calls == []


def test_conflict_appearing_during_enable_latches_without_clearing():
    sock = Sock()
    original = sock.setsockopt
    def change(level, option, value):
        original(level, option, value)
        sock.options[35] = 1
    sock.setsockopt = change
    profile = KernelRXTimestamping(RAW, SHA)
    with pytest.raises(ValueError, match="legacy"):
        profile.enable_before_bind(sock)
    assert sock.calls == [(1, 65, 24)] and sock.options[35] == 1
    with pytest.raises(ValueError, match="latched"):
        profile.enable_before_bind(sock)


@pytest.mark.parametrize("method", ["getsockopt", "setsockopt"])
def test_native_option_exception_during_enable_is_latched(method):
    sock = Sock()
    def broken(*_args):
        raise OSError("injected native option error")
    setattr(sock, method, broken)
    profile = KernelRXTimestamping(RAW, SHA)
    with pytest.raises(OSError, match="native"):
        profile.enable_before_bind(sock)
    assert profile.evidence["failure"]
    with pytest.raises(ValueError, match="latched"):
        profile.enable_before_bind(sock)


@pytest.mark.parametrize("value", [True, -1, 25, 0])
def test_native_option_flags_drift_is_latched(value):
    sock, profile = prepared()
    sock.options[65] = value
    with pytest.raises(ValueError, match="option"):
        profile.check(sock)
    assert profile.evidence["failure"]


@pytest.mark.parametrize("values", [(0, 0, 0, 0, 0, 0), (1, -1, 0, 0, 0, 0),
                                  (1, 1_000_000_000, 0, 0, 0, 0), (1, 1, 1, 0, 0, 0),
                                  (1, 1, 0, 0, 2, 1), (10, 0, 0, 0, 0, 0)])
def test_missing_invalid_or_nonsoftware_triple_refuses(values):
    _sock, profile = prepared()
    after = profile.realtime()
    with pytest.raises(ValueError):
        profile.parse([(1, 65, struct.pack("<6q", *values))], 0, after)
    assert profile.evidence["failure"]


def test_valid_generated_triple_and_kernel_regression():
    _sock, profile = prepared()
    after = profile.realtime()
    assert profile.parse([(1, 65, struct.pack("<6q", 1, 250, 0, 0, 0, 0))], 0, after) == 1_000_000_250
    with pytest.raises(ValueError, match="regressed"):
        profile.parse([(1, 65, struct.pack("<6q", 1, 249, 0, 0, 0, 0))], 0, after)


@pytest.mark.parametrize("kind,length,flags,count", [(37, 48, 0, 1), (65, 47, 0, 1),
                                                     (65, 49, 0, 1), (65, 48, 8, 1),
                                                     (65, 48, 32, 1), (65, 48, 0, 0),
                                                     (65, 48, 0, 2), (True, 48, 0, 1)])
def test_malformed_generated_metadata_is_latched(kind, length, flags, count):
    _sock, profile = prepared()
    after = profile.realtime()
    valid = struct.pack("<6q", 1, 250, 0, 0, 0, 0)
    raw = valid[:length] if length <= 48 else valid + b"x"
    with pytest.raises(ValueError):
        profile.parse([(1, kind, raw)] * count, flags, after)
    assert profile.evidence["failure"]


def test_ancillary_level_bool_cannot_alias_sol_socket_one():
    _sock, profile = prepared()
    after = profile.realtime()
    with pytest.raises(ValueError):
        profile.parse([(True, 65, struct.pack("<6q", 1, 250, 0, 0, 0, 0))], 0, after)


def test_forbidden_get_failure_after_preparation_is_latched():
    sock, profile = prepared()
    def broken(_level, _option):
        raise OSError("injected native getsockopt failure")
    sock.getsockopt = broken
    with pytest.raises(OSError, match="getsockopt"):
        profile.check(sock)
    with pytest.raises(ValueError, match="latched"):
        profile.realtime()


@pytest.mark.parametrize("key,value", [("timespec_bytes", 16), ("cmsg_type", 37), ("rx_software", True),
                                       ("ts2_offset", 16), ("cmsg_space", 48)])
def test_unknown_or_wrong_abi_refuses_even_rehashed(key, value):
    bad = {**ABI, key: value}
    raw = json.dumps(bad).encode()
    with pytest.raises(ValueError, match="ABI"):
        KernelRXTimestamping(raw, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("post_conflict", [False, True])
def test_existing_receiver_retains_triple_before_post_receive_refusal(monkeypatch, post_conflict):
    monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)
    sock, profile = prepared()
    events = []
    receiver = DatagramReceiver(sock, lambda: None, lambda: 100, 100, events.append, kernel_timestamps=profile)
    if post_conflict:
        sock.hook = lambda: sock.options.update({64: 1})
        with pytest.raises(ValueError, match="legacy"):
            receiver.poll()
        raw = next(row for row in events if row["kind"] == "receive_return")
        assert raw["data_hex"] == b"opaque".hex() and raw["ancillary_raw"][0]["data_hex"] == sock.raw.hex()
    else:
        packet = receiver.poll()
        assert packet.kernel_received_realtime_ns == 1_000_000_250
        assert packet.received_ns == 100 and sock.calls[-1] == (4096, 64, 64)


def test_caller_subclass_is_not_a_receiver_decoder(monkeypatch):
    monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)
    class CallerProfile(KernelRXTimestamping):
        pass
    value = CallerProfile(RAW, SHA)
    with pytest.raises(ValueError, match="exact optional"):
        DatagramReceiver(Sock(), lambda: None, lambda: 100, 100, lambda _row: None, kernel_timestamps=value)
