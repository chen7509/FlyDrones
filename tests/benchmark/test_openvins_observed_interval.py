"""Actual observed/owned/codec stack with injected socket; never actual UDP."""
import inspect
import unittest
from types import SimpleNamespace

from tests.benchmark import test_openvins_observed_wire_session as fixtures
from tests.benchmark.test_openvins_wire_bootstrap import Connection, body, frame, mav
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark.openvins_observed_wire_session import ObservedWireSession


class ObservedIntervalTests(unittest.TestCase):
    def setUp(self, *, retention=None):
        self.assertIn('interval_transaction', inspect.signature(ObservedWireSession).parameters,
                      'observed single-reader interval binding missing')
        self.f = fixtures.ObservedSessionTests('runTest')
        self.f.setUp()
        self.f.obj.close()
        self.f.events.clear()
        self.delivered = []
        self.f.obj = ObservedWireSession(
            SimpleNamespace(pid=321), fixtures.OWNER, '/tmp/private/socket', self.f.remote,
            self.f.lane, self.f.sock, 10, self.f.journal, self.f.descriptor_guard,
            backend=self.f.backend, heartbeat_sink=self.delivered.append, interval_transaction=True,
            retention=retention)
        self.obj = self.f.obj
        self.f.ready()
        self.f.clock_to(body(0)[0])

    def incoming(self, *messages):
        encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
        self.f.sock.input.append(heartbeat() + b''.join(m.pack(encoder) for m in messages))
        return self.obj.poll_datagram()

    def ack(self, command=511, target=254):
        return mav.MAVLink_command_ack_message(command, 0, 0, 0, target, 191)

    def query(self, value, reverse=False):
        self.obj.poll_interval()
        ack = self.ack(510)
        interval = mav.MAVLink_message_interval_message(111, value)
        self.incoming(*([ack, interval] if reverse else [interval, ack]))
        self.obj.poll_interval()

    def configured(self):
        self.query(100000)
        self.obj.poll_interval()
        self.incoming(self.ack())
        self.obj.poll_interval()
        self.query(10000, True)
        self.assertEqual(self.obj.progress['interval_phase'], 'body')

    def complete_listener(self):
        self.f.receive()
        for _ in range(3):
            self.obj.poll_listener()
        for index in range(1, 500):
            self.f.backend.now += 10_000_000
            self.f.receive(index)
            self.f.backend.connections[2].reads.append(frame(index))
            self.obj.poll_listener()
        self.f.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll_listener()
        self.obj.poll_listener()

    def restored(self):
        self.obj.poll_interval()
        self.incoming(self.ack())
        self.obj.poll_interval()
        self.query(100000)
        self.query(100000, True)

    def test_normal500_restore_before_maintenance_same_receiver_and_sequence(self):
        receiver, codec = self.obj._receiver, self.obj._core._wire._codec
        self.configured()
        self.complete_listener()
        self.assertFalse(self.obj.progress['observed_bootstrap_complete'])
        self.assertEqual(self.obj.progress['interval_phase'], 'restore')
        self.restored()
        self.assertTrue(self.obj.progress['observed_bootstrap_complete'])
        self.assertTrue(self.obj.progress['interval_transaction_pass'])
        self.assertEqual(self.obj.progress['completed_reply_attempts'], 500)
        self.obj.begin_maintenance(300_000_000_010)
        self.f.backend.connections.append(Connection([status(499, 1)]))
        self.obj.poll_listener()
        self.obj.poll_interval()  # A regular driver tick cannot restart commands.
        self.f.backend.now += 1_000_000
        self.f.receive(500)
        self.f.backend.connections[3].reads.append(status(500, 2))
        self.obj.poll_listener()
        self.assertIs(self.obj._receiver, receiver)
        self.assertIs(self.obj._core._wire._codec, codec)
        decoded = [mav.MAVLink(None).decode(bytearray(row[0])) for row in self.f.sock.sent]
        self.assertEqual(len(decoded), 507)
        self.assertEqual([m.get_seq() for m in decoded], [i % 256 for i in range(507)])
        commands = [m for m in decoded if m.get_type() == 'COMMAND_LONG']
        self.assertEqual([m.command for m in commands], [510, 511, 510, 511, 510, 510])
        self.assertEqual([m.param2 for m in commands if m.command == 511], [10000, 100000])
        self.assertEqual(len(self.delivered), 6)
        self.assertEqual(len(self.f.sock.reads), 507)
        self.obj.close()
        self.assertFalse(self.f.sock.closed)
        self.assertFalse(self.obj.progress['fusion_qualified'])

    def test_early_timesync_retained_without_reply_or_filter_count(self):
        self.obj.poll_interval()
        self.assertIsNone(self.f.receive())
        self.assertEqual(len(self.f.sock.sent), 1)  # Only baseline GET.
        self.assertEqual(self.obj.progress['completed_reply_attempts'], 0)
        kinds = [e['kind'] for e in self.obj.evidence['core']['wire']['events']]
        self.assertIn('interval_wait_request', kinds)
        self.incoming(mav.MAVLink_message_interval_message(111, 100000), self.ack(510))
        self.assertEqual(len(self.delivered), 1)

    def test_command_wait_keeps_heartbeat_without_advancing_exchange(self):
        self.obj.poll_interval()
        for _ in range(5):
            self.incoming()
            self.obj.poll_interval()
        self.assertEqual(len(self.delivered), 5)
        self.assertEqual(len(self.f.sock.sent), 1)
        self.assertEqual(self.obj.progress['interval_phase'], 'baseline')

    def test_maintenance_before_restore_refused(self):
        self.configured()
        self.complete_listener()
        with self.assertRaises(ValueError):
            self.obj.begin_maintenance(300_000_000_010)
        self.assertFalse(self.obj.progress['modeled_bootstrap_ready'])
        self.assertEqual(len(self.f.sock.sent), 503)

    def test_descriptor_change_before_command_prevents_send(self):
        def changed():
            raise ValueError('descriptor changed')
        self.f.descriptor_hook = changed
        with self.assertRaises(ValueError):
            self.obj.poll_interval()
        self.assertEqual(self.f.sock.sent, [])

    def test_bad_ack_and_armed_mixed_frame_fail_before_next_command(self):
        for raw in [self.ack(510, target=253).pack(mav.MAVLink(None, srcSystem=9, srcComponent=1)),
                    heartbeat(base=128) + self.ack(510).pack(mav.MAVLink(None, srcSystem=9, srcComponent=1))]:
            self.setUp()
            self.obj.poll_interval()
            self.f.sock.input.append(raw)
            with self.assertRaises(ValueError):
                self.obj.poll_datagram()
            self.assertTrue(self.obj.progress['failure'])
            self.assertEqual(len(self.f.sock.sent), 1)

    def test_command_short_send_retains_actual_count_and_attempt(self):
        self.f.sock.hook = lambda raw: len(raw) - 1
        with self.assertRaises(ValueError):
            self.obj.poll_interval()
        rows = self.obj.evidence['core']['wire']['events']
        attempts = [r for r in rows if r['kind'] == 'interval_send_attempt']
        returns = [r for r in rows if r['kind'] == 'interval_send_return']
        self.assertEqual(len(attempts), 1)
        self.assertEqual(returns[0]['count'], len(bytes.fromhex(attempts[0]['raw_hex'])) - 1)

    def test_legacy_mode_cannot_enable_commands_later(self):
        legacy = fixtures.ObservedSessionTests('runTest')
        legacy.setUp()
        legacy.ready()
        with self.assertRaises(ValueError):
            legacy.obj.poll_interval()
        self.assertEqual(legacy.sock.sent, [])

    def test_heartbeat_during_first_reply_status_wait_and_interval_idle_poll(self):
        self.configured()
        self.f.receive()
        before = len(self.f.sock.sent)
        self.assertEqual(self.obj.progress['phase'], 'first_pending')
        self.incoming()
        self.obj.poll_interval()
        self.assertEqual(len(self.f.sock.sent), before)
        self.assertEqual(len(self.delivered), 4)
        self.assertEqual(self.obj.progress['phase'], 'first_pending')

    def test_second_timesync_during_pending_status_still_refused(self):
        self.configured()
        self.f.receive()
        before = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.f.receive(1)
        self.assertEqual(len(self.f.sock.sent), before)

    def test_restore_final_readback_mismatch_never_grants_maintenance(self):
        self.configured()
        self.complete_listener()
        self.obj.poll_interval()
        self.incoming(self.ack())
        self.obj.poll_interval()
        self.query(100000)
        self.obj.poll_interval()
        self.incoming(mav.MAVLink_message_interval_message(111, 10000), self.ack(510))
        with self.assertRaises(ValueError):
            self.obj.poll_interval()
        self.assertFalse(self.obj.progress['observed_bootstrap_complete'])
        self.assertFalse(self.obj.progress['interval_transaction_pass'])

    def test_idle_owner_loss_while_query_pending_blocks_response(self):
        self.obj.poll_interval()
        self.f.backend.owner['start_ticks'] += 1
        reads = len(self.f.sock.reads)
        with self.assertRaises(ValueError):
            self.incoming(self.ack(510))
        self.assertEqual(len(self.f.sock.reads), reads)
        self.assertEqual(len(self.f.sock.sent), 1)

    def test_command_return_after_operation_timeout_keeps_real_count(self):
        def slow(raw):
            self.f.backend.now += 2_000_000_000
            return len(raw)
        self.f.sock.hook = slow
        with self.assertRaises(ValueError):
            self.obj.poll_interval()
        evidence = self.obj.evidence['core']['wire']
        returned = [r for r in evidence['events'] if r['kind'] == 'interval_send_return']
        self.assertEqual(len(returned), 1)
        self.assertEqual(returned[0]['count'], len(self.f.sock.sent[0][0]))
        self.assertFalse(self.obj.progress['observed_bootstrap_complete'])
