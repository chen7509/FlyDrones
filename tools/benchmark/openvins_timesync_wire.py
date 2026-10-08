"""Pinned TIMESYNC bytes to an injected sink; no socket or live authority.

Source/header equality is not authentication. Synchronous callbacks require
outer bounded supervision. A sink byte count is not PX4 receipt or convergence.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
from pathlib import Path
from threading import Lock

from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.owned_daemon_connection import _error


class PinnedCodec:
    SOURCE_SHA256 = "a7c6b23d908322134d19cb94b937c1ea6b1f5d5ffa9d1b0ad139174bf8d75809"
    MAX_DATAGRAM_BYTES = 4096
    MAX_FRAMES = 64

    def __init__(self):
        from pymavlink.dialects.v20 import common

        self._mav = common
        if importlib.metadata.version("pymavlink") != "2.4.49":
            raise ValueError("pymavlink version mismatch")
        if hashlib.sha256(Path(common.__file__).read_bytes()).hexdigest() != self.SOURCE_SHA256:
            raise ValueError("pymavlink selected source hash mismatch")
        self.check()

    def check(self):
        if self._mav.MAVLINK_IGNORE_CRC:
            raise ValueError("CRC bypass forbidden")
        cls = self._mav.MAVLink_timesync_message
        if cls.fieldnames != ["tc1", "ts1"] or cls.crc_extra != 34:
            raise ValueError("TIMESYNC schema mismatch")

    def decode_datagram(self, raw):
        self.check()
        if type(raw) is not bytes or not 0 < len(raw) <= self.MAX_DATAGRAM_BYTES:
            raise ValueError("invalid datagram bytes/size")
        offset, decoded = 0, []
        while offset < len(raw):
            if len(decoded) >= self.MAX_FRAMES:
                raise ValueError("datagram frame limit")
            magic = raw[offset]
            if magic not in (0xFE, 0xFD):
                raise ValueError("invalid MAVLink framing")
            header = 10 if magic == 0xFD else 6
            if len(raw) - offset < header:
                raise ValueError("truncated header")
            if magic == 0xFD and (raw[offset + 2] or raw[offset + 3]):
                raise ValueError("unsigned fixed profile forbids flags/signed frames")
            payload = raw[offset + 1]
            size = header + payload + 2
            if len(raw) - offset < size:
                raise ValueError("truncated payload/checksum")
            msgid = int.from_bytes(raw[offset + 7:offset + 10], "little") if magic == 0xFD else raw[offset + 5]
            if msgid not in self._mav.mavlink_map:
                raise ValueError("unknown dialect message")
            if msgid == 111 and (payload > 16 or (magic == 0xFE and payload != 16)):
                raise ValueError("TIMESYNC payload schema length")
            frame = raw[offset:offset + size]
            msg = self._mav.MAVLink(None).decode(bytearray(frame))
            decoded.append(dict(type=msg.get_type(), system=msg.get_srcSystem(), component=msg.get_srcComponent(),
                                sequence=msg.get_seq(), framing=1 if magic == 0xFE else 2,
                                fields=msg.to_dict(), raw_hex=frame.hex()))
            offset += size
        return decoded

    def encode_reply(self, request_ns, response_ns, sequence):
        self.check()
        for value in (request_ns, response_ns):
            if type(value) is not int or not 0 < value < 2**63 or value % 1000:
                raise ValueError("invalid reply identity")
        if type(sequence) is not int or not 0 <= sequence <= 255:
            raise ValueError("invalid sender sequence")
        encoder = self._mav.MAVLink(None, srcSystem=254, srcComponent=191)
        encoder.seq = sequence
        return self._mav.MAVLink_timesync_message(response_ns, request_ns).pack(encoder)


class TimesyncWireResponder:
    MAX_EVENTS = 8192

    def __init__(self, remote_clock, reserve_reply, send_sink, journal, now, start_ns, peer=("127.0.0.1", 14588)):
        if not isinstance(remote_clock, RemoteMonotonicClock):
            raise ValueError("existing remote clock required")
        if any(not callable(c) for c in (reserve_reply, send_sink, journal, now)):
            raise ValueError("explicit callbacks required")
        if type(start_ns) is not int or not 0 <= start_ns < 2**64 - 8_000_000_000:
            raise ValueError("invalid start clock")
        if peer != ("127.0.0.1", 14588) or type(peer) is not tuple:
            raise ValueError("fixed peer profile required")
        self._codec = PinnedCodec()
        self._remote, self._session = remote_clock, remote_clock.session_id
        self._reserve, self._sink, self._journal, self._now = reserve_reply, send_sink, journal, now
        self._peer = peer
        self._start = self._last_now = start_ns
        self._received = None
        self._events = []
        self._regular_events = 0
        self._journal_errors = []
        self._failure = self._refusal_journal_error = None
        self._sequence = 0
        self._last_identity = None
        self._lock = Lock()

    @property
    def evidence(self):
        return dict(events=copy.deepcopy(self._events), failure=self._failure,
                    journal_errors=copy.deepcopy(self._journal_errors),
                    refusal_journal_error=self._refusal_journal_error, clock_session=self._session,
                    network_authorized=False, delivery_proven=False, live_convergence_qualified=False,
                    fusion_qualified=False)

    def _check(self):
        if self._failure is not None:
            raise ValueError("wire failure latched: " + self._failure)
        value = self._accept_time(self._now())
        if value - self._start >= 8_000_000_000:
            raise ValueError("wire global deadline")
        if self._received is not None and value - self._received >= 2_000_000_000:
            raise ValueError("wire request deadline")
        if self._remote.session_id != self._session:
            raise ValueError("remote clock session changed")
        self._codec.check()
        return value

    def _accept_time(self, value):
        if type(value) is not int or not self._last_now <= value < 2**64:
            raise ValueError("local clock regression/type")
        self._last_now = value
        return value

    def _record(self, kind, **data):
        self._require_event_capacity()
        self._regular_events += 1
        # For send_return record the actual effect before checking clock/result.
        event = dict(kind=kind, at_last_checked_ns=self._last_now, **copy.deepcopy(data))
        clock_error = None
        if kind == "send_return":
            try:
                event["returned_ns"] = self._now()
            except BaseException as exc:
                clock_error = exc
                event["return_clock_error"] = _error(exc)
        self._events.append(copy.deepcopy(event))
        try:
            if self._journal(copy.deepcopy(event)) is not None:
                raise ValueError("journal must return None")
        except BaseException as exc:
            self._journal_errors.append(dict(kind=kind, error=_error(exc)))
            if clock_error is not None and (not isinstance(clock_error, Exception) or isinstance(exc, Exception)):
                raise clock_error from exc
            raise
        if clock_error is not None:
            raise clock_error
        if kind == "send_return":
            self._accept_time(event["returned_ns"])
        self._check()

    def _require_event_capacity(self):
        if self._regular_events >= self.MAX_EVENTS:
            raise ValueError("wire event limit")

    def _abort(self, error):
        if self._failure is not None:
            return
        # Latch before running even an exception's potentially user-defined str.
        self._failure = "wire refusal (formatting error)"
        self._failure = _error(error)
        event = dict(kind="refusal", reason=self._failure, at_last_checked_ns=self._last_now)
        self._events.append(copy.deepcopy(event))
        try:
            if self._journal(copy.deepcopy(event)) is not None:
                raise ValueError("refusal journal must return None")
        except BaseException as exc:
            self._refusal_journal_error = _error(exc)

    def receive(self, raw, peer, received_ns, observed_sim_ns):
        if not self._lock.acquire(blocking=False):
            self._abort(ValueError("concurrent wire operation"))
            raise ValueError("concurrent wire operation")
        try:
            self._check()
            if type(raw) is not bytes or not 0 < len(raw) <= self._codec.MAX_DATAGRAM_BYTES:
                raise ValueError("invalid datagram bytes/size")
            # Retain rejected bounded input before interpreting its contents.
            self._record("receive", raw_hex=raw.hex(), peer=peer, received_ns=received_ns,
                         observed_sim_ns=observed_sim_ns)
            if type(peer) is not tuple or peer != self._peer:
                raise ValueError("unexpected peer")
            if type(received_ns) is not int or not 0 <= received_ns <= self._last_now:
                raise ValueError("invalid receive time")
            self._received = received_ns
            self._check()
            messages = self._codec.decode_datagram(raw)
            self._record("decoded", messages=messages)
            if any(m["system"] != 9 or m["component"] != 1 for m in messages):
                raise ValueError("unexpected header source")
            requests = [m for m in messages if m["type"] == "TIMESYNC"]
            if len(requests) > 1:
                raise ValueError("multiple TIMESYNC requests")
            if not requests:
                return None
            message = requests[0]
            tc1, request = message["fields"]["tc1"], message["fields"]["ts1"]
            if tc1 != 0 or type(request) is not int or not 0 < request < 2**63 or request % 1000:
                raise ValueError("invalid request identity or unexpected response")
            if self._last_identity is not None and request <= self._last_identity[0]:
                raise ValueError("request identity regression or reuse")
            reply = self._remote.respond_to_px4_request(tc1_ns=tc1, ts1_ns=request, observed_sim_ns=observed_sim_ns)
            response = reply["tc1_ns"]
            if self._last_identity is not None and response <= self._last_identity[1]:
                raise ValueError("response identity regression or reuse")
            encoded = self._codec.encode_reply(request, response, self._sequence)
            self._record("reply_prepared", request_ns=request, response_ns=response, raw_hex=encoded.hex(),
                         sequence=self._sequence, clock_session=reply["clock_session_id"])
            self._check()
            intent = self._reserve(request, response)
            expected = dict(request_ns=request, response_ns=response, transmission_proven=False,
                            network_authorized=False, fusion_qualified=False)
            if type(intent) is not dict or intent != expected or any(type(intent[k]) is not type(v) for k, v in expected.items()):
                raise ValueError("reservation intent mismatch")
            self._record("reserved", intent=intent)
            self._check()
            self._record("send_attempt", raw_hex=encoded.hex(), peer=self._peer)
            send_started_ns = self._check()
            # One return slot remains reserved; the refusal slot is separate.
            self._require_event_capacity()
            count = self._sink(encoded, self._peer)
            self._record("send_return", count=count, send_started_ns=send_started_ns)
            if type(count) is not int or count != len(encoded):
                raise ValueError("invalid or short send count")
            self._last_identity = (request, response)
            self._sequence = (self._sequence + 1) % 256
            self._check()
            return dict(sink_accepted_all_bytes=True, request_ns=request, response_ns=response,
                        network_authorized=False, delivery_proven=False, live_convergence_qualified=False,
                        fusion_qualified=False)
        except BaseException as exc:
            self._abort(exc)
            if not isinstance(exc, Exception):
                raise
            raise ValueError(_error(exc)) from exc
        finally:
            self._received = None
            self._lock.release()
