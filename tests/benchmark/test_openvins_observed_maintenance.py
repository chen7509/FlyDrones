"""One real observed receiver/codec/clock stack across startup; injected I/O."""
import unittest

from tests.benchmark import test_openvins_wire_heartbeat as heartbeats
from tests.benchmark.test_openvins_wire_bootstrap import Connection, body, frame
from tests.benchmark.test_openvins_wire_maintenance import status


class ObservedMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.h = heartbeats.HeartbeatTests()
        self.h.setUp()
        self.f = self.h.f
        self.obj, self.backend = self.f.obj, self.f.backend

    def complete(self):
        self.f.receive()
        self.obj.poll_listener()
        self.obj.poll_listener()
        self.obj.poll_listener()
        for index in range(1, 500):
            self.backend.now += 10_000_000
            self.f.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll_listener()
        self.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll_listener()
        self.assertTrue(self.obj.poll_listener()['observed_bootstrap_complete'])

    def begin(self, deadline=300_000_000_010):
        self.assertTrue(callable(getattr(self.obj, 'begin_maintenance', None)), 'observed maintenance binding missing')
        self.obj.begin_maintenance(deadline)
        self.backend.connections.append(Connection([status(499, 1)]))
        self.obj.poll_listener()

    def test_single_receiver_continues_clock_heartbeat_and_reply_sequence_beyond8s(self):
        self.complete()
        self.begin()
        for index in range(500, 505):
            self.backend.now += 900_000_000
            self.f.receive(index)
            # Heartbeats must not be dropped while a status is outstanding.
            self.f.sock.input.append(heartbeats.heartbeat())
            self.assertIsNone(self.obj.poll_datagram())
            self.backend.connections[3].reads.append(status(index, index - 498))
            self.obj.poll_listener()
        self.assertGreater(self.backend.now, 8_000_000_010)
        self.assertEqual(len(self.f.sock.reads), 510)
        self.assertEqual(len(self.f.sock.sent), 505)
        self.assertEqual(len(self.h.delivered), 5)
        self.assertEqual(self.h.delivered[-1]['observed_sim_ns'], body(504)[0])
        self.assertEqual(self.h.delivered[-1]['arrival_monotonic_ns'], self.backend.now)
        msg = heartbeats.mav.MAVLink(None).decode(bytearray(self.f.sock.sent[500][0]))
        self.assertEqual(msg.get_seq(), 244)
        self.assertTrue(self.obj.progress['maintenance_healthy'])
        self.assertEqual(self.obj.progress['modeled_accepted_samples'], 505)
        self.obj.close()
        self.assertFalse(self.f.sock.closed)  # Supplied datagram socket stays caller-owned.
        self.assertEqual(self.backend.used[3].closed, 1)
        self.assertEqual(self.obj.evidence['core']['owned']['cleanup_errors'], [])
        self.assertIsNone(self.obj.progress['failure'])
        self.assertFalse(self.obj.progress['maintenance_healthy'])
        self.assertEqual(len(self.obj.evidence['selections']), 510)
        self.assertFalse(self.obj.progress['network_authorized'])

    def test_transition_late_journal_cannot_extend_original8s(self):
        self.complete()
        self.assertTrue(callable(getattr(self.obj, 'begin_maintenance', None)), 'observed maintenance binding missing')

        def hook(event):
            if event['source'] == 'receiver' and event['event']['kind'] == 'maintenance_bound':
                self.backend.now = 8_000_000_010

        self.f.journal_hook = hook
        with self.assertRaises(ValueError):
            self.obj.begin_maintenance(300_000_000_010)
        self.f.assert_failed()
        self.assertEqual(len(self.backend.used), 3)

    def test_descriptor_replacement_after_handoff_refuses_before_read(self):
        self.complete()
        self.begin()

        def reject():
            raise ValueError('descriptor replaced')

        self.f.descriptor_hook = reject
        reads = len(self.f.sock.reads)
        with self.assertRaises(ValueError):
            self.f.receive(500)
        self.assertEqual(len(self.f.sock.reads), reads)
        self.assertEqual(len(self.f.sock.sent), 500)
        self.assertEqual(self.backend.used[3].closed, 1)

    def test_source_stale_after_bootstrap_is_not_permanent_healthy(self):
        self.complete()
        self.begin()
        self.backend.now += 2_000_000_000
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.f.assert_failed()
        self.assertEqual(len(self.f.sock.sent), 500)

    def test_partial_cancel_journal_is_retained_after_outer_close(self):
        self.complete()
        self.begin()
        self.f.receive(500)
        self.backend.connections[3].reads.append(status(500, 2)[:31])
        self.obj.poll_listener()
        self.obj.close()
        self.obj.close()
        owned = self.obj.evidence['core']['owned']
        self.assertTrue(owned['maintenance_progress']['pending_reply'])
        self.assertEqual(owned['maintenance_progress']['incomplete_frame_bytes'], 31)
        self.assertEqual(owned['cleanup_errors'], [])
        self.assertIsNone(owned['transports'][3].get('cancel_journal_error'))
        journal = [e['event']['event'] for e in self.f.events
                   if e['source'] == 'core' and e['event']['source'] == 'owned']
        self.assertEqual(journal, owned['events'])
        before = len(self.f.sock.reads)
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertEqual(len(self.f.sock.reads), before)


if __name__ == '__main__':
    unittest.main()
