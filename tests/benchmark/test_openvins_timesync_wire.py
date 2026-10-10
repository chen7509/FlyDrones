"""Real installed codec tests; explicit WSL unittest run, no network traffic."""

import copy
import unittest

try:
    from pymavlink.dialects.v20 import common as mav
except ImportError as exc:
    raise unittest.SkipTest("real pymavlink unavailable; run this suite in WSL") from exc

from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.openvins_timesync_observer import SerialTimesyncObserver

PEER = ("127.0.0.1", 14588)


def packet(tc1=0, ts1=100_000_000, *, system=9, component=1, seq=0, v1=False, signed=False):
    encoder = mav.MAVLink(None, srcSystem=system, srcComponent=component)
    encoder.seq = seq
    if signed:
        encoder.signing.secret_key = b"fixture-key-not-a-credential!!!!!"[:32].ljust(32, b"!")
        encoder.signing.sign_outgoing = True
    return mav.MAVLink_timesync_message(tc1, ts1).pack(encoder, force_mavlink1=v1)


def heartbeat(system=9):
    return mav.MAVLink_heartbeat_message(2, 12, 0, 0, 3, 3).pack(mav.MAVLink(None, srcSystem=system, srcComponent=1))


class WireTests(unittest.TestCase):
    def setUp(self):
        from tools.benchmark.openvins_timesync_wire import PinnedCodec, TimesyncWireResponder

        self.codec_class = PinnedCodec
        self.responder_class = TimesyncWireResponder
        self.time = 0
        self.events = []
        self.sent = []
        self.observer = SerialTimesyncObserver("clock-a", 0)
        self.remote = RemoteMonotonicClock("clock-a", sim_origin_ns=0, remote_origin_ns=1_000_000)
        self.reserve_hook = None
        self.sink_hook = None
        self.journal_hook = None
        self.wire = self.responder_class(self.remote, self.reserve, self.sink, self.journal, lambda: self.time, 0)

    def reserve(self, request, response):
        if self.reserve_hook:
            return self.reserve_hook(request, response)
        self.observer.reserve_reply(request, response, self.time)
        return dict(request_ns=request, response_ns=response, transmission_proven=False, network_authorized=False, fusion_qualified=False)

    def sink(self, raw, peer):
        self.sent.append((raw, peer))
        return self.sink_hook(raw, peer) if self.sink_hook else len(raw)

    def journal(self, event):
        self.events.append(copy.deepcopy(event))
        if self.journal_hook:
            return self.journal_hook(event)
        return None

    def receive(self, raw=None, **kwargs):
        return self.wire.receive(packet() if raw is None else raw, kwargs.get("peer", PEER),
                                 kwargs.get("received_ns", self.time), kwargs.get("observed_sim_ns", 100_000_000))

    def refusal(self, raw=None, reason=None, **kwargs):
        with self.assertRaisesRegex(ValueError, reason or "."):
            self.receive(raw, **kwargs)
        count = len(self.sent)
        with self.assertRaisesRegex(ValueError, "latched"):
            self.receive()
        self.assertEqual(len(self.sent), count)

    def status(self, index=0):
        request_us = 100_000 + index * 20_000
        return dict(instance=0, ordinal=index + 1, timestamp=request_us + 2001,
                    remote_timestamp=request_us + 1000, observed_offset=0, estimated_offset=0,
                    round_trip_time=2000, source_protocol=0)

    def test_real_codec_roundtrip_trimmed_request_and_send_accounting(self):
        result = self.receive()
        self.assertLess(len(packet()), 28)
        decoded = mav.MAVLink(None).decode(bytearray(self.sent[0][0]))
        self.assertEqual((decoded.tc1, decoded.ts1), (101_000_000, 100_000_000))
        self.assertEqual((decoded.get_srcSystem(), decoded.get_srcComponent()), (254, 191))
        self.assertTrue(result["sink_accepted_all_bytes"])
        for flag in ("network_authorized", "delivery_proven", "live_convergence_qualified", "fusion_qualified"):
            self.assertIs(result[flag], False)
        self.assertEqual(self.events, self.wire.evidence["events"])

    def test_v1_and_batched_heartbeat_accepted(self):
        self.receive(heartbeat() + packet(v1=True) + heartbeat())
        self.assertEqual(len(self.sent), 1)

    def test_heartbeat_only_is_recorded_without_send(self):
        self.assertIsNone(self.receive(heartbeat()))
        self.assertEqual(self.sent, [])
        self.assertTrue(self.events)

    def test_bad_last_frame_prevents_valid_first_request_send(self):
        self.refusal(packet() + heartbeat()[:-1], "truncated")
        self.assertEqual(self.sent, [])

    def test_all_request_split_points_refused_not_buffered(self):
        for end in range(1, len(packet())):
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.codec_class().decode_datagram(packet()[:end])

    def test_crc_corruption(self):
        raw = bytearray(packet())
        raw[-1] ^= 1
        self.refusal(bytes(raw), "CRC")

    def test_signed_frames_rejected_even_with_valid_signature_bytes(self):
        self.refusal(packet(signed=True), "flags|signed")

    def test_unknown_message_rejected(self):
        raw = bytearray(packet())
        raw[7:10] = bytes([255, 255, 255])
        self.refusal(bytes(raw), "unknown")

    def test_frame_limits_and_garbage(self):
        for raw in (b"", b"garbage", packet() + b"x", b"x" * 4097, heartbeat() * 65):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                self.codec_class().decode_datagram(raw)

    def test_both_protocol_flags_rejected(self):
        for offset in (2, 3):
            raw = bytearray(packet())
            raw[offset] = 2
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "flags"):
                self.codec_class().decode_datagram(bytes(raw))

    def test_crc_bypass_mutation_refused(self):
        previous = mav.MAVLINK_IGNORE_CRC
        try:
            mav.MAVLINK_IGNORE_CRC = True
            self.refusal(reason="CRC")
        finally:
            mav.MAVLINK_IGNORE_CRC = previous

    def test_wrong_peer(self):
        self.refusal(peer=("127.0.0.2", 14588), reason="peer")
        self.assertEqual(self.sent, [])

    def test_wrong_system_and_component(self):
        for raw in (packet(system=1), packet(component=2), heartbeat(1) + packet()):
            self.setUp()
            self.refusal(raw, "source")
            self.assertEqual(self.sent, [])

    def test_two_requests_in_datagram_refuse_before_any_effect(self):
        self.refusal(packet() + packet(ts1=120_000_000), "multiple")
        self.assertEqual(self.sent, [])

    def test_unexpected_response_and_bad_timestamp(self):
        for raw in (packet(tc1=1), packet(ts1=-1), packet(ts1=0), packet(ts1=1001)):
            self.setUp()
            self.refusal(raw)
            self.assertEqual(self.sent, [])

    def test_pending_real_observer_blocks_second_send(self):
        self.receive()
        self.refusal(packet(ts1=120_000_000), "pending", observed_sim_ns=120_000_000)
        self.assertEqual(len(self.sent), 1)

    def test_matched_status_allows_new_request_despite_header_sequence_wrap(self):
        self.receive(packet(seq=255))
        self.observer.observe_status(self.status(), self.time)
        self.receive(packet(ts1=120_000_000, seq=0), observed_sim_ns=120_000_000)
        decoded = mav.MAVLink(None).decode(bytearray(self.sent[1][0]))
        self.assertEqual(decoded.get_seq(), 1)

    def test_replayed_request_refused_even_after_status(self):
        self.receive()
        self.observer.observe_status(self.status(), 0)
        self.refusal(reason="reuse|regression", observed_sim_ns=120_000_000)

    def test_remote_session_replacement_refused(self):
        self.remote.replace_session("other", sim_origin_ns=0, remote_origin_ns=0)
        self.refusal(reason="session")
        self.assertEqual(self.sent, [])

    def test_remote_time_alignment_and_overflow(self):
        for value in (1, 2**63):
            self.setUp()
            self.remote.remote_origin_ns = value
            self.refusal(reason="identity")

    def test_exact_two_second_receive_age(self):
        self.time = 2_000_000_000
        self.refusal(received_ns=0, reason="deadline")

    def test_future_and_noninteger_receive_time(self):
        for value in (1, True, -1, 0.0):
            self.setUp()
            self.refusal(received_ns=value, reason="receive")

    def test_exact_eight_second_global_deadline(self):
        self.time = 8_000_000_000
        self.refusal(reason="global")

    def test_clock_regression(self):
        self.time = 1
        self.receive(heartbeat())
        self.time = 0
        self.refusal(reason="clock")

    def test_reservation_failure_prevents_send(self):
        self.reserve_hook = lambda *_: (_ for _ in ()).throw(ValueError("reservation failed"))
        self.refusal(reason="reservation failed")
        self.assertEqual(self.sent, [])

    def test_reservation_authority_or_identity_mismatch(self):
        for change in ({"network_authorized": True}, {"response_ns": 1}, {"extra": 1}):
            self.setUp()
            self.reserve_hook = lambda a, b, c=change: dict(request_ns=a, response_ns=b, transmission_proven=False,
                                                           network_authorized=False, fusion_qualified=False) | c
            self.refusal(reason="reservation")
            self.assertEqual(self.sent, [])

    def test_short_noninteger_send_preserves_return(self):
        for value in (0, True, None, 3.0):
            self.setUp()
            self.sink_hook = lambda *_, v=value: v
            self.refusal(reason="send count")
            self.assertEqual(len(self.sent), 1)
            event = next(e for e in self.wire.evidence["events"] if e["kind"] == "send_return")
            self.assertEqual(event["count"], value)

    def test_send_exception_retains_attempt_not_success(self):
        self.sink_hook = lambda *_: (_ for _ in ()).throw(OSError("sink uncertain"))
        self.refusal(reason="sink uncertain")
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(any(e["kind"] == "send_attempt" for e in self.events))

    def test_late_successful_send_preserves_return_and_fails(self):
        def late(raw, peer):
            self.time = 2_000_000_000
            return len(raw)
        self.sink_hook = late
        self.refusal(reason="deadline")
        self.assertTrue(any(e["kind"] == "send_return" for e in self.wire.evidence["events"]))

    def test_journal_failure_before_send(self):
        self.journal_hook = lambda e: (_ for _ in ()).throw(OSError("journal failed"))
        self.refusal(reason="journal failed")
        self.assertEqual(self.sent, [])
        self.assertIsNotNone(self.wire.evidence["refusal_journal_error"])

    def test_journal_failure_after_send_preserves_effect(self):
        def hook(event):
            if event["kind"] == "send_return":
                raise OSError("post send journal failed")
        self.journal_hook = hook
        self.refusal(reason="post send journal failed")
        self.assertEqual(len(self.sent), 1)

    def test_callback_mutation_cannot_change_evidence(self):
        self.journal_hook = lambda e: e.clear()
        self.receive()
        self.assertEqual(self.events, self.wire.evidence["events"])

    def test_reservation_delay_blocks_send(self):
        original = self.reserve
        def late(a, b):
            self.reserve_hook = None
            intent = original(a, b)
            self.time = 2_000_000_000
            return intent
        self.reserve_hook = late
        self.refusal(reason="deadline")
        self.assertEqual(self.sent, [])

    def test_reentrant_callback_failure_cannot_resume_send(self):
        def hook(event):
            if event["kind"] == "receive":
                try:
                    self.receive()
                except ValueError:
                    pass
        self.journal_hook = hook
        self.refusal(reason="concurrent|latched")
        self.assertEqual(self.sent, [])

    def test_interrupt_preserved_and_latched(self):
        self.sink_hook = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.receive()
        self.refusal(reason="latched")

    def test_event_capacity_refuses_before_send(self):
        self.wire.MAX_EVENTS = 1
        self.refusal(reason="event limit")
        self.assertEqual(self.sent, [])
        self.assertLessEqual(len(self.wire.evidence["events"]), 2)

    def test_send_return_has_actual_post_sink_clock_not_prior_check(self):
        def sink(raw, peer):
            self.time = 1234
            return len(raw)
        self.sink_hook = sink
        self.receive()
        returned = next(e for e in self.events if e["kind"] == "send_return")
        self.assertEqual(returned.get("returned_ns"), 1234)

    def test_bad_return_clock_does_not_hide_returned_count(self):
        def sink(raw, peer):
            self.time = -1
            return len(raw)
        self.sink_hook = sink
        self.refusal(reason="clock")
        returned = next(e for e in self.wire.evidence["events"] if e["kind"] == "send_return")
        self.assertEqual(returned.get("returned_ns"), -1)
        self.assertEqual(returned["count"], len(self.sent[0][0]))

    def test_return_capacity_required_before_send(self):
        self.wire.MAX_EVENTS = 5
        self.refusal(reason="event limit")
        self.assertEqual(self.sent, [])

    def test_reentrant_refusal_does_not_consume_reserved_return_slot(self):
        self.wire.MAX_EVENTS = 6
        def sink(raw, peer):
            try:
                self.receive()
            except ValueError:
                pass
            return len(raw)
        self.sink_hook = sink
        self.refusal(reason="latched|concurrent")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(sum(e["kind"] == "send_return" for e in self.wire.evidence["events"]), 1)
        self.assertEqual(sum(e["kind"] == "refusal" for e in self.wire.evidence["events"]), 1)

    def test_return_clock_interrupt_survives_secondary_journal_failure(self):
        def stop_clock():
            raise KeyboardInterrupt("return clock interrupted")
        def sink(raw, peer):
            self.wire._now = stop_clock
            return len(raw)
        def journal(event):
            if event["kind"] == "send_return":
                raise OSError("secondary journal error")
        self.sink_hook, self.journal_hook = sink, journal
        with self.assertRaisesRegex(KeyboardInterrupt, "return clock interrupted"):
            self.receive()
        self.assertIn("secondary journal error", str(self.wire.evidence))
        self.assertIsNotNone(self.wire.evidence["failure"])

    def test_hostile_error_string_still_latches_refusal(self):
        class BadError(Exception):
            def __str__(self):
                raise RuntimeError("cannot format")
        self.journal_hook = lambda e: (_ for _ in ()).throw(BadError())
        with self.assertRaisesRegex(ValueError, "BadError.*unprintable"):
            self.receive()
        self.journal_hook = None
        self.assertIsNotNone(self.wire.evidence["failure"])
        self.refusal(reason="latched")
        self.assertEqual(self.sent, [])

    def test_receive_clock_regression_even_on_heartbeat_refuses(self):
        self.time = 1000
        self.receive(heartbeat(), received_ns=1000)
        self.time = 1001
        self.refusal(heartbeat(), received_ns=999, reason="receive.*regression")
        self.assertEqual(self.sent, [])

    def test_equal_receive_clocks_are_allowed_for_resolution_ties(self):
        self.time = 1000
        self.receive(heartbeat(), received_ns=1000)
        self.receive(received_ns=1000)
        self.assertEqual(len(self.sent), 1)

    def test_public_check_does_not_send_or_journal_and_enforces_idle_deadline(self):
        self.assertIsNone(self.wire.check())
        self.assertEqual(self.events, [])
        self.assertEqual(self.sent, [])
        self.time = 8_000_000_000
        with self.assertRaisesRegex(ValueError, "global"):
            self.wire.check()
        self.assertIsNotNone(self.wire.evidence["failure"])

    def test_reentrant_public_check_latches_before_send(self):
        def hook(event):
            if event["kind"] == "receive":
                try:
                    self.wire.check()
                except ValueError:
                    pass
        self.journal_hook = hook
        self.refusal(reason="latched|concurrent")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
