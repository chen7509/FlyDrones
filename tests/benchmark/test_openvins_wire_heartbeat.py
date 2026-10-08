"""Actual codec/shared receive path with fake transport; never opens sockets."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from pymavlink.dialects.v20 import common as mav
except ImportError as exc:
    raise unittest.SkipTest('existing WSL codec required') from exc

from tests.benchmark import test_openvins_observed_wire_session as fixtures
from tests.benchmark.test_openvins_timesync_wire import packet
from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
from tools.benchmark.openvins_timesync_wire import PinnedCodec


def heartbeat(*, base=0, autopilot=12, version=3, system=9):
    return mav.MAVLink_heartbeat_message(2, autopilot, base, 17, 3, version).pack(
        mav.MAVLink(None, srcSystem=system, srcComponent=1))


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ObservedSessionTests('runTest')
        self.f.setUp()
        self.delivered, self.hook = [], None
        self.f.obj.close()
        self.f.events.clear()
        self.f.obj = ObservedWireSession(
            SimpleNamespace(pid=321), fixtures.OWNER, '/tmp/private/socket', self.f.remote,
            self.f.lane, self.f.sock, 10, self.f.journal, self.f.descriptor_guard,
            backend=self.f.backend, heartbeat_sink=self.deliver)
        self.f.ready()

    def deliver(self, row):
        self.delivered.append(copy.deepcopy(row))
        return self.hook(row) if self.hook else None

    def receive(self, raw):
        self.f.clock_to(100_000_000)
        self.f.sock.input.append(raw)
        return self.f.obj.poll_datagram()

    def refuse(self, raw):
        with self.assertRaises(ValueError):
            self.receive(raw)
        self.assertEqual(self.f.sock.sent, [])
        self.f.assert_failed()

    def events(self, kind):
        return [e for e in self.f.obj.evidence['core']['wire']['events'] if e['kind'] == kind]

    def test_heartbeat_only_uses_capture_event_shape_without_reply(self):
        self.assertIsNone(self.receive(heartbeat()))
        self.assertEqual(self.delivered, [dict(kind='heartbeat', arrival_monotonic_ns=10,
                                            observed_sim_ns=100_000_000, system_id=9,
                                            base_mode=0, custom_mode=17)])
        self.assertEqual(self.f.obj.progress['completed_reply_attempts'], 0)
        self.assertEqual(self.f.sock.sent, [])
        self.assertEqual(len(self.events('heartbeat_dispatch_return')), 1)

    def test_mixed_frames_decode_once_and_dispatch_before_send(self):
        calls = []
        original = PinnedCodec.decode_datagram
        def decode(codec, raw):
            calls.append(raw)
            return original(codec, raw)
        self.f.sock.hook = lambda raw: (self.assertEqual(len(self.delivered), 1), len(raw))[1]
        with patch.object(PinnedCodec, 'decode_datagram', decode):
            self.receive(packet() + heartbeat())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.f.sock.sent), 1)
        self.assertEqual(self.events('heartbeat_dispatch_attempt')[0]['frame_index'], 1)

    def test_heartbeat_first_mixed_packet(self):
        self.receive(heartbeat() + packet())
        self.assertEqual(len(self.delivered), 1)
        self.assertEqual(len(self.f.sock.sent), 1)

    def test_existing_capture_dispatch_receives_exact_same_event(self):
        from tools.benchmark.capture_disarmed_sensors import dispatch_heartbeat
        rows = []
        writer = SimpleNamespace(submit=lambda row: rows.append(copy.deepcopy(row)))
        self.hook = lambda row: dispatch_heartbeat(row, writer, None)
        self.receive(heartbeat())
        self.assertEqual(rows, self.delivered)

    def test_armed_refused_before_dispatch_or_mixed_reply(self):
        self.refuse(packet() + heartbeat(base=128))
        self.assertEqual(self.delivered, [])
        self.assertTrue(self.events('decoded'))

    def test_wrong_autopilot_refused(self):
        self.refuse(heartbeat(autopilot=3))
        self.assertEqual(self.delivered, [])

    def test_wrong_header_source_refused(self):
        self.refuse(heartbeat(system=8))
        self.assertEqual(self.delivered, [])

    def test_multiple_heartbeats_refused_without_partial_delivery(self):
        self.refuse(heartbeat() + heartbeat())
        self.assertEqual(self.delivered, [])

    def test_bad_mixed_request_refused_without_heartbeat_delivery(self):
        self.refuse(heartbeat() + packet(tc1=1))
        self.assertEqual(self.delivered, [])

    def test_bad_mixed_crc_refused_without_delivery(self):
        raw = packet()
        self.refuse(heartbeat() + raw[:-1] + bytes([raw[-1] ^ 1]))
        self.assertEqual(self.delivered, [])

    def test_callback_mutation_does_not_change_evidence(self):
        self.hook = lambda row: row.update(base_mode=128, observed_sim_ns=0)
        self.receive(heartbeat() + packet())
        self.assertEqual(self.events('heartbeat_dispatch_attempt')[0]['event']['base_mode'], 0)
        self.assertEqual(len(self.f.sock.sent), 1)

    def test_callback_error_preserves_attempt_without_reply(self):
        def fail(_):
            raise OSError('capture journal failed')
        self.hook = fail
        self.refuse(heartbeat() + packet())
        self.assertEqual(len(self.events('heartbeat_dispatch_attempt')), 1)
        self.assertEqual(self.events('heartbeat_dispatch_return'), [])

    def test_non_none_return_is_retained_then_refused(self):
        self.hook = lambda _: False
        self.refuse(heartbeat() + packet())
        self.assertFalse(self.events('heartbeat_dispatch_return')[0]['returned_none'])

    def test_late_callback_preserves_return_and_refuses_send(self):
        self.hook = lambda _: setattr(self.f.backend, 'now', 2_000_000_010)
        self.refuse(heartbeat() + packet())
        self.assertTrue(self.events('heartbeat_dispatch_return')[0]['returned_none'])

    def test_callback_close_refuses_mixed_send(self):
        self.hook = lambda _: self.f.obj.close()
        self.refuse(heartbeat() + packet())
        self.assertEqual(len(self.delivered), 1)

    def test_shared_clock_failure_during_callback_refuses_mixed_send(self):
        def fail(_):
            self.f.remote.map_odometry_sample(10)
            with self.assertRaises(ValueError):
                self.f.remote.map_odometry_sample(10)
        self.hook = fail
        self.refuse(heartbeat() + packet())

    def test_journal_failure_before_dispatch_never_delivers(self):
        def fail(row):
            if (row['source'] == 'core' and row['event'].get('source') == 'wire'
                    and row['event']['event']['kind'] == 'heartbeat_dispatch_attempt'):
                raise OSError('dispatch intent log failed')
        self.f.journal_hook = fail
        self.refuse(heartbeat() + packet())
        self.assertEqual(self.delivered, [])

    def test_return_evidence_slot_required_before_callback(self):
        wire = self.f.obj._core._wire
        wire._regular_events = wire.MAX_EVENTS - 3  # receive, decoded, attempt exhaust the log
        self.refuse(heartbeat())
        self.assertEqual(self.delivered, [])

    def test_reentrant_callback_latches_before_reply(self):
        def reenter(_):
            with self.assertRaises(ValueError):
                self.f.obj.poll_datagram()
        self.hook = reenter
        self.refuse(heartbeat() + packet())
        self.assertEqual(len(self.delivered), 1)

    def test_wrong_heartbeat_version_is_refused(self):
        self.refuse(heartbeat(version=2))
        self.assertEqual(self.delivered, [])

    def test_failure_after_callback_is_not_rolled_back_or_retried(self):
        def fail(row):
            if (row['source'] == 'core' and row['event'].get('source') == 'wire'
                    and row['event']['event']['kind'] == 'heartbeat_dispatch_return'):
                raise OSError('return journal failure')
        self.f.journal_hook = fail
        self.refuse(heartbeat() + packet())
        self.assertEqual(len(self.delivered), 1)
        self.assertTrue(self.events('heartbeat_dispatch_return')[0]['returned_none'])


if __name__ == '__main__':
    unittest.main()
