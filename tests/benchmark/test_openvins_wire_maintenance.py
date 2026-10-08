"""Actual installed codec and owned coordinator; no socket or PX4 run."""
import unittest

from tests.benchmark import test_openvins_wire_bootstrap as fixtures
from tests.benchmark.test_openvins_wire_bootstrap import Connection, body, frame, mav


def status(index, ordinal):
    return b'\x1b[2J\n\x1b[H' + f'\nTOPIC: timesync_status instance 0 #{ordinal}\n'.encode() + body(index)[2]


class MaintenanceWireTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.CompositionTests()
        self.case.setUp()
        self.obj, self.backend = self.case.obj, self.case.backend

    def complete(self):
        self.case.stream_ready()
        for index in range(1, 500):
            self.backend.now += 10_000_000
            self.case.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll()
        self.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll()
        self.assertTrue(self.obj.poll()['wire_bootstrap_complete'])

    def begin(self):
        self.assertTrue(callable(getattr(self.obj, 'begin_maintenance', None)), 'wire maintenance binding missing')
        self.obj.begin_maintenance(300_000_000_010)
        self.backend.connections.append(Connection([status(499, 1)]))
        self.obj.poll()

    def test_same_codec_sequence_and_reservations_past500_and8s(self):
        self.complete()
        self.begin()
        for index in range(500, 505):
            self.backend.now += 900_000_000
            self.case.receive(index)
            self.backend.connections[3].reads.append(status(index, index - 498))
            self.obj.poll()
        self.assertGreater(self.backend.now, 8_000_000_010)
        self.assertEqual(self.obj.progress['modeled_accepted_samples'], 505)
        self.assertEqual(self.obj.progress['completed_reply_attempts'], 505)
        self.assertTrue(self.obj.progress['maintenance_healthy'])
        for index in (499, 500, 504):
            decoded = mav.MAVLink(None).decode(bytearray(self.case.sent[index][0]))
            self.assertEqual(decoded.get_seq(), index % 256)
            self.assertEqual(decoded.ts1, body(index)[0])
        self.obj.close()
        self.assertEqual(self.backend.used[3].closed, 1)
        with self.assertRaises(ValueError):
            self.case.receive(505)

    def test_repeated_old_request_fails_before_any_new_send(self):
        self.complete()
        self.begin()
        with self.assertRaises(ValueError):
            self.case.receive(499)
        self.assertEqual(len(self.case.sent), 500)
        self.assertTrue(self.obj.progress['failure'])
        self.assertEqual(self.backend.used[3].closed, 1)

    def test_deadline_and_failed_handoff_do_not_reset_or_revive(self):
        self.complete()
        self.assertTrue(callable(getattr(self.obj, 'begin_maintenance', None)), 'wire maintenance binding missing')
        self.backend.now = 8_000_000_010
        with self.assertRaises(ValueError):
            self.obj.begin_maintenance(300_000_000_010)
        self.assertTrue(self.obj.progress['failure'])
        with self.assertRaises(ValueError):
            self.case.receive(500)
        self.assertEqual(len(self.case.sent), 500)

    def test_reentrant_handoff_journal_blocks_continuation_and_no_send(self):
        self.complete()
        self.assertTrue(callable(getattr(self.obj, 'begin_maintenance', None)), 'wire maintenance binding missing')

        def hook(event):
            if event['source'] == 'wire' and event['event']['kind'] == 'maintenance_bound':
                with self.assertRaises(ValueError):
                    self.case.receive(500)

        self.case.journal_hook = hook
        with self.assertRaises(ValueError):
            self.obj.begin_maintenance(300_000_000_010)
        self.assertTrue(self.obj.progress['failure'])
        self.assertEqual(len(self.case.sent), 500)

    def test_missing_status_still_stops_at2s(self):
        self.complete()
        self.begin()
        self.case.receive(500)
        self.backend.now += 2_000_000_000
        with self.assertRaises(ValueError):
            self.obj.poll()
        self.assertEqual(self.obj.evidence['owned']['maintenance_progress']['pending_reply'], True)
        self.assertEqual(self.backend.used[3].closed, 1)


if __name__ == '__main__':
    unittest.main()
