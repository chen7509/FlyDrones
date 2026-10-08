"""Independent review counterexamples, injected I/O only."""
import tempfile
import unittest
from pathlib import Path

from tests.benchmark import test_capture_wire_lifecycle as driver_cases
from tests.benchmark import test_openvins_observed_interval as interval_cases
from tests.benchmark import test_openvins_observed_restoration as restore_cases
from tests.benchmark import test_openvins_timesync_wire as wire_cases
from tests.benchmark.test_openvins_wire_bootstrap import body
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat, packet
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


class ReviewSafetyTests(unittest.TestCase):
    def test_rejected_first_maintenance_correlation_cannot_grant_motion_readiness(self):
        c = driver_cases.CaptureDriverTests('runTest')
        c.setUp()
        self.addCleanup(c.driver.finish)
        c.bootstrap()
        c.f.backend.now += 1000000
        c.f.clock_to(body(500)[0])
        c.f.enqueue(500)
        c.tick()
        raw = status(500, 2).replace(b'round_trip_time: 2000', b'round_trip_time: 10000')
        raw = raw.replace(b'timestamp: 10102000', b'timestamp: 10110000')
        raw = raw.replace(b'observed_offset: 0', b'observed_offset: 4000')
        c.f.backend.connections[3].reads.append(raw)
        c.tick()
        self.assertEqual(c.driver.session.progress['modeled_accepted_samples'], 500)
        self.assertFalse(c.driver.progress['ready'])
        self.assertFalse(c.driver.health_ready())

    def test_armed_packet_revokes_cached_unarmed_restore_permission(self):
        c = restore_cases.RestorationTests('runTest')
        c.setUp()
        self.addCleanup(c.obj.close)
        c.f.sock.input.append(heartbeat(base=128))
        with self.assertRaises(ValueError):
            c.obj.poll_datagram()
        before = len(c.f.sock.sent)
        try:
            c.obj.begin_restoration('armed observed')
            c.obj.poll_restoration()
        except ValueError:
            pass  # Either refusal or waiting must not send using the old grant.
        self.assertEqual(len(c.f.sock.sent), before)

    def test_invalid_mixed_requests_have_no_heartbeat_side_effect(self):
        for raw in (heartbeat()+packet(tc1=1), heartbeat()+packet()+packet()):
            with self.subTest(raw=raw.hex()):
                c = interval_cases.ObservedIntervalTests('runTest')
                c.setUp()
                self.addCleanup(c.obj.close)
                c.f.sock.input.append(raw)
                with self.assertRaises(ValueError):
                    c.obj.poll_datagram()
                self.assertEqual(c.delivered, [])

    def test_duplicate_ack_batch_cannot_deliver_heartbeat_or_accept_first_ack(self):
        c = interval_cases.ObservedIntervalTests('runTest')
        c.setUp()
        self.addCleanup(c.obj.close)
        c.obj.poll_interval()
        from tests.benchmark.test_openvins_wire_bootstrap import mav
        enc = mav.MAVLink(None, srcSystem=9, srcComponent=1)
        ack = c.ack(510).pack(enc)
        c.f.sock.input.append(heartbeat()+ack+ack)
        with self.assertRaises(ValueError):
            c.obj.poll_datagram()
        self.assertEqual(c.delivered, [])
        events = c.obj._core._wire._interval.evidence['events']
        self.assertFalse(any(e['kind'] == 'response' for e in events))

    def test_byte_quota_keeps_return_of_executed_send_in_bounded_failure_slot(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        c = wire_cases.WireTests('runTest')
        c.setUp()
        store = SegmentedWireJournal(Path(tmp)/'wire')
        self.addCleanup(store.close)
        store.MAX_BYTES = 1300
        c.wire = c.responder_class(c.remote, c.reserve, c.sink, c.journal,
                                   lambda: c.time, 0, retention=store)
        with self.assertRaisesRegex(ValueError, 'byte capacity'):
            c.receive()
        self.assertEqual(len(c.sent), 1)
        rejected = store.evidence['failed_record']
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected['event']['kind'], 'send_return')
        self.assertEqual(rejected['event']['count'], len(c.sent[0][0]))

    def test_byte_quota_preserves_other_bounded_callback_return_records(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        for channel, kind in [('wire', 'heartbeat_dispatch_return'), ('listener-0', 'read_return')]:
            with self.subTest(kind=kind):
                store = SegmentedWireJournal(Path(tmp)/kind)
                self.addCleanup(store.close)
                events = store.channel(channel)
                store.MAX_BYTES = 32
                with self.assertRaisesRegex(ValueError, 'byte capacity'):
                    events.append({'kind': kind, 'count': 12, 'returned_none': True})
                self.assertEqual(store.evidence['failed_record']['event'],
                                 {'kind': kind, 'count': 12, 'returned_none': True})

    def test_invalid_mixed_clock_mapping_has_no_heartbeat_side_effect(self):
        c = interval_cases.ObservedIntervalTests('runTest')
        c.setUp()
        self.addCleanup(c.obj.close)
        c.f.remote.respond_to_px4_request(tc1_ns=0, ts1_ns=80000000, observed_sim_ns=100000000)
        c.f.sock.input.append(heartbeat()+packet())
        with self.assertRaises(ValueError):
            c.obj.poll_datagram()
        self.assertEqual(c.delivered, [])
