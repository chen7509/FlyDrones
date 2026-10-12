"""Opt-in, pre-bind Linux NEW timestamp metadata; no arrival/clock/source grant.

ABI bytes must come from a separately frozen installed-header probe. Their SHA
is an identity check, not authentication. Socket lifetime/owner remains caller
responsibility; this object never creates, binds, closes or sends a socket.
Kernel receive-time fallback may synthesize the current time; successful ABI
decoding cannot qualify the instant when a packet originally entered a queue.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import socket
import struct
import time
from threading import Lock

from tools.benchmark.owned_daemon_connection import _error

_ABI = {
    "schema": "flydrones.kernel_timestampns_new_abi.v1", "machine": "x86_64", "byteorder": "little",
    "pointer_bytes": 8, "sol_socket": 1, "so_timestampns_new": 64, "cmsg_type": 64,
    "timespec_bytes": 16, "sec_offset": 0, "sec_bytes": 8, "nsec_offset": 8, "nsec_bytes": 8,
    "cmsg_space": 32, "msg_dontwait": 64, "msg_trunc": 32, "msg_ctrunc": 8,
}
_MAX_NS = 2**63 - 1


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate kernel timestamp ABI key")
        result[name] = value
    return result


def _unbound(address):
    return (type(address) is tuple and len(address) == 2
            and type(address[0]) is str and address[0] == "0.0.0.0"
            and type(address[1]) is int and address[1] == 0)


class KernelTimestampNS:
    """One unbound-to-bound socket's software CLOCK_REALTIME ancillary profile."""

    ancillary_bytes = 32

    def __init__(self, abi_bytes: bytes, abi_sha256: str, *, realtime_ns=time.time_ns):
        if (type(abi_bytes) is not bytes or not 1 <= len(abi_bytes) <= 4096
                or type(abi_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", abi_sha256) is None
                or hashlib.sha256(abi_bytes).hexdigest() != abi_sha256):
            raise ValueError("kernel timestamp ABI identity invalid")
        try:
            abi = json.loads(abi_bytes, object_pairs_hook=_unique,
                             parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("ABI constant")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("kernel timestamp ABI JSON invalid") from exc
        if (type(abi) is not dict or abi.keys() != _ABI.keys()
                or any(type(abi[name]) is not type(value) or abi[name] != value for name, value in _ABI.items())
                or not callable(realtime_ns)):
            raise ValueError("unsupported kernel timestamp ABI or realtime reader")
        self._abi = copy.deepcopy(abi)
        self._abi_sha = abi_sha256
        self._realtime = realtime_ns
        self._sock = self._fd = None
        self._used = False
        self._failure = None
        self._last_real = self._last_kernel = None
        self._last_real_read = None
        self._enable_lock = Lock()

    @property
    def evidence(self):
        return dict(abi=copy.deepcopy(self._abi), abi_sha256=self._abi_sha,
                    enabled_before_bind=self._sock is not None, descriptor=self._fd,
                    failure=self._failure, timestamp_clock="CLOCK_REALTIME", timestamp_source="kernel software",
                    last_realtime_read_ns=self._last_real_read,
                    kernel_receive_instant_qualified=False,
                    clock_mapping_qualified=False, sender_process_proven=False, network_authorized=False,
                    fusion_qualified=False, training_eligible=False)

    def _open(self):
        if self._failure is not None:
            raise ValueError("kernel timestamp failure latched: " + self._failure)

    def _refuse(self, reason):
        self._failure = self._failure or reason
        raise ValueError(reason)

    def enable_before_bind(self, sock):
        if not self._enable_lock.acquire(blocking=False):
            self._refuse("concurrent kernel timestamp enable")
        try:
            self._open()
            if self._used:
                self._refuse("kernel timestamp enable is single-use")
            self._used = True
            if (not all(isinstance(v, int) and not isinstance(v, bool) for v in (sock.family, sock.type, sock.proto))
                    or sock.family != socket.AF_INET or sock.type != socket.SOCK_DGRAM
                    or sock.proto not in (0, socket.IPPROTO_UDP)
                    or not _unbound(sock.getsockname())):
                self._refuse("kernel timestamp must enable before bind on IPv4 UDP")
            fd = sock.fileno()
            if type(fd) is not int or fd < 0:
                self._refuse("invalid kernel timestamp descriptor")
            sock.setsockopt(self._abi["sol_socket"], self._abi["so_timestampns_new"], 1)
            enabled = sock.getsockopt(self._abi["sol_socket"], self._abi["so_timestampns_new"])
            self._open()
            current_fd = sock.fileno()
            if (type(enabled) is not int or enabled != 1 or type(current_fd) is not int or current_fd != fd
                    or not _unbound(sock.getsockname())):
                self._refuse("kernel timestamp pre-bind option confirmation failed")
            self._sock, self._fd = sock, fd
        except BaseException as exc:
            self._failure = self._failure or _error(exc)
            raise
        finally:
            self._enable_lock.release()

    def check(self, sock):
        self._open()
        if sock is not self._sock or type(sock.fileno()) is not int or sock.fileno() != self._fd:
            self._refuse("kernel timestamp socket/descriptor changed or not prepared")
        enabled = sock.getsockopt(self._abi["sol_socket"], self._abi["so_timestampns_new"])
        self._open()
        if type(enabled) is not int or enabled != 1:
            self._refuse("kernel timestamp option changed")

    def realtime(self):
        self._last_real_read = None
        self._open()
        try:
            value = self._realtime()
        except BaseException as exc:
            self._failure = self._failure or _error(exc)
            raise
        if type(value) is int and -2**63 <= value <= _MAX_NS:
            self._last_real_read = value
        self._open()
        if (type(value) is not int or not 0 < value <= _MAX_NS
                or self._last_real is not None and value < self._last_real):
            self._refuse("kernel realtime observation invalid or regressed")
        self._last_real = value
        return value

    @staticmethod
    def describe(ancillary):
        if type(ancillary) is not list:
            return None
        result = []
        for item in ancillary[:8]:
            row = dict(level=None, type=None, data_hex=None, data_length=None)
            if type(item) is tuple and len(item) == 3:
                level, kind, data = item
                for label, value in (("level", level), ("type", kind)):
                    if type(value) is int and -2**31 <= value < 2**31:
                        row[label] = value
                if type(data) is bytes:
                    row.update(data_hex=data[:64].hex(), data_length=len(data))
            result.append(row)
        return result

    def parse(self, ancillary, flags, after_realtime_ns):
        self._open()
        if (type(flags) is not int or flags != 0 or type(ancillary) is not list or len(ancillary) != 1
                or type(ancillary[0]) is not tuple or len(ancillary[0]) != 3):
            self._refuse("kernel timestamp ancillary missing/duplicate/truncated or flags invalid")
        level, kind, raw = ancillary[0]
        if (type(level) is not int or level != self._abi["sol_socket"]
                or type(kind) is not int or kind != self._abi["cmsg_type"]
                or type(raw) is not bytes or len(raw) != self._abi["timespec_bytes"]):
            self._refuse("kernel timestamp ancillary type/ABI/length invalid")
        sec, nsec = struct.unpack("<qq", raw)
        if sec <= 0 or not 0 <= nsec < 1_000_000_000:
            self._refuse("kernel timestamp sec/nsec invalid")
        value = sec * 1_000_000_000 + nsec
        if (value > _MAX_NS or type(after_realtime_ns) is not int
                or after_realtime_ns != self._last_real or value > after_realtime_ns):
            self._refuse("kernel timestamp future/overflow or realtime bracket invalid")
        if self._last_kernel is not None and value < self._last_kernel:
            self._refuse("kernel timestamp regressed")
        self._last_kernel = value
        return value
