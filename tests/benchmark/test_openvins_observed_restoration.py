"""Bounded cleanup on the same actual classes; all I/O factories are fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from tests.benchmark import test_openvins_observed_interval as interval_fixtures
from tests.benchmark import test_openvins_segmented_wire as storage_fixtures
from tests.benchmark.test_openvins_wire_bootstrap import mav
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal
from tools.benchmark.openvins_timesync_interval import TimesyncIntervalTransaction


class RestorationTests(unittest.TestCase):
    def setUp(self, *, retention=None, configure=True):
        self.case = interval_fixtures.ObservedIntervalTests('runTest')
        self.case.setUp(retention=retention)
        self.obj, self.f = self.case.obj, self.case.f
        self.assertTrue(callable(getattr(self.obj, 'begin_restoration', None)), 'owned restoration entry missing')
        self.assertTrue(callable(getattr(self.obj, 'poll_restoration', None)), 'single-reader restoration poll missing')
        if configure:
            self.case.configured()

    def fail_source(self):
        def lost():
            raise ValueError('source lost fixture')
        self.f.source_hook = lost
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertTrue(self.obj.progress['failure'])

    def receive(self, *messages, hb=True):
        encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
        raw = (heartbeat() if hb else b'') + b''.join(m.pack(encoder) for m in messages)
        if raw:
            self.f.sock.input.append(raw)
        return self.obj.poll_restoration()

    def restore(self):
        self.receive()  # Fresh safety heartbeat, then the one baseline SET.
        self.receive(self.case.ack())  # Finish SET, no second effect in this poll.
        self.obj.poll_restoration()  # restore GET
        self.receive(mav.MAVLink_message_interval_message(111, 100000), self.case.ack(510))
        self.obj.poll_restoration()  # final GET
        self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))

    def test_source_loss_restores_without_reopening_source_or_second_reader(self):
        receiver, codec = self.obj._receiver, self.obj._core._wire._codec
        self.fail_source()
        primary = self.obj.progress['failure']
        delivered = len(self.case.delivered)
        self.obj.begin_restoration('source failure cleanup')
        self.restore()
        result = self.obj.progress
        self.assertEqual(result['failure'], primary)
        self.assertTrue(result['restoration_finished'])
        self.assertTrue(result['restoration_verified'])
        self.assertFalse(result['modeled_bootstrap_ready'])
        self.assertFalse(result['fusion_qualified'])
        self.assertEqual(len(self.case.delivered), delivered)  # Safety observation, no normal fanout grant.
        self.assertIs(self.obj._receiver, receiver)
        self.assertIs(self.obj._core._wire._codec, codec)
        commands = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
        self.assertEqual([m.get_seq() for m in commands], list(range(6)))
        self.assertEqual([m.command for m in commands], [510, 511, 510, 511, 510, 510])
        self.assertEqual(commands[3].param2, 100000)
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertEqual(len(self.f.sock.sent), count)
        self.obj.close()
        self.assertFalse(self.f.sock.closed)

    def test_startup_expiry_keeps_original8s_and_restores_within_separate10s(self):
        self.f.backend.now = 8_000_000_010
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.obj.begin_restoration('expired startup')
        self.restore()
        self.assertTrue(self.obj.progress['restoration_verified'])
        self.assertFalse(self.obj.progress['observed_bootstrap_complete'])
        self.assertEqual(self.obj._deadline, 8_000_000_010)
        self.assertEqual(self.obj.evidence['restoration']['deadline_ns'], 18_000_000_010)

    def test_deadline_starts_at_failure_not_later_cleanup_entry_and_is_immutable(self):
        self.fail_source()
        deadline = self.obj.evidence['restoration']['deadline_ns']
        self.f.backend.now += 1_000_000_000
        self.obj.begin_restoration('first')
        self.obj.begin_restoration('second')
        self.assertEqual(self.obj.evidence['restoration']['deadline_ns'], deadline)
        self.f.backend.now = deadline
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.poll_restoration()
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertFalse(self.obj.progress['restoration_verified'])

    def test_identity_or_descriptor_change_prevents_cleanup_send(self):
        for which in ('owner', 'descriptor'):
            self.setUp()
            self.fail_source()
            if which == 'owner':
                self.f.backend.owner['start_ticks'] += 1
            else:
                def changed():
                    raise ValueError('descriptor replaced')
                self.f.descriptor_hook = changed
            count = len(self.f.sock.sent)
            with self.assertRaises(ValueError):
                self.obj.begin_restoration('cleanup')
            self.assertEqual(len(self.f.sock.sent), count)
            self.assertFalse(self.obj.progress['restoration_verified'])

    def test_armed_heartbeat_aborts_before_any_restore(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.f.sock.input.append(heartbeat(base=128))
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.poll_restoration()
        self.assertEqual(len(self.f.sock.sent), count)
        with self.assertRaises(ValueError):
            self.obj.poll_restoration()

    def test_stale_unarmed_observation_waits_for_fresh_safety_frame(self):
        self.fail_source()
        self.f.backend.now += 2_000_000_000
        self.obj.begin_restoration('cleanup')
        count = len(self.f.sock.sent)
        self.obj.poll_restoration()
        self.assertEqual(len(self.f.sock.sent), count)
        self.receive()
        self.assertEqual(len(self.f.sock.sent), count + 1)

    def test_timesync_is_retained_but_never_replied_during_cleanup(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.receive(mav.MAVLink_timesync_message(0, 200_000_000))
        sent = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
        self.assertTrue(all(m.get_type() == 'COMMAND_LONG' for m in sent))
        events = self.obj.evidence['core']['wire']['events']
        self.assertTrue(any(e['kind'] == 'restoration_ignored' for e in events))

    def test_interrupted_restore_is_recorded_and_never_retried(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        def interrupt(raw):
            raise KeyboardInterrupt()
        self.f.sock.hook = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.receive()
        self.f.sock.hook = None
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.poll_restoration()
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertTrue(self.obj.evidence['core']['wire']['interval']['restore_attempted'])

    def test_cleanup_journal_failure_latches_and_prevents_command(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        def broken(event):
            raise OSError('cleanup journal unavailable')
        self.f.journal_hook = broken
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertTrue(self.obj.evidence['restoration']['failure'])

    def test_close_before_restore_cannot_be_reported_as_verified(self):
        self.fail_source()
        self.obj.close()
        self.obj.close()
        with self.assertRaises(ValueError):
            self.obj.begin_restoration('too late')
        self.assertFalse(self.obj.progress['restoration_verified'])
        self.assertTrue(self.obj.evidence['cleanup_errors'])

    def test_lost_apply_ack_does_not_retry_candidate_and_restores_baseline(self):
        self.case.setUp()
        self.obj, self.f = self.case.obj, self.case.f
        self.case.query(100000)
        self.obj.poll_interval()  # Candidate SET, no ACK returned.
        self.fail_source()
        self.obj.begin_restoration('lost candidate ack')
        self.restore()
        commands = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
        self.assertEqual([m.param2 for m in commands if m.command == 511], [10000, 100000])
        self.assertTrue(self.obj.progress['restoration_verified'])
        self.assertTrue(self.obj.progress['failure'])

    def test_missing_restore_ack_keeps_failure_and_independent_readbacks(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.receive()  # Baseline SET, never acknowledge it.
        self.f.backend.now += 2_000_000_000
        self.receive()  # Fresh heartbeat; pending SET expires without retry.
        self.obj.poll_restoration()
        self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
        self.obj.poll_restoration()
        self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
        state = self.obj.evidence['core']['wire']['interval']
        self.assertTrue(self.obj.progress['restoration_finished'])
        self.assertFalse(self.obj.progress['restoration_verified'])
        self.assertEqual(state['final_us'], 100000)
        self.assertTrue(state['restore_failures'])
        commands = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
        self.assertEqual([m.param2 for m in commands if m.command == 511], [10000, 100000])

    def test_changed_remote_session_or_clock_rollback_blocks_restoration(self):
        for fault in ('session', 'clock'):
            with self.subTest(fault=fault):
                self.setUp()
                self.fail_source()
                self.obj.begin_restoration('cleanup')
                count = len(self.f.sock.sent)
                if fault == 'session':
                    self.f.remote.session_id = 'replacement'
                else:
                    self.f.backend.now -= 1
                with self.assertRaises(ValueError):
                    self.receive()
                self.assertEqual(len(self.f.sock.sent), count)
                self.assertFalse(self.obj.progress['restoration_verified'])

    def test_slow_descriptor_guard_cannot_extend_first_failure_deadline(self):
        self.fail_source()
        deadline = self.obj.evidence['restoration']['deadline_ns']
        def delayed():
            self.f.backend.now = deadline
        self.f.descriptor_hook = delayed
        count = len(self.f.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.begin_restoration('late entry')
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertEqual(self.obj.evidence['restoration']['deadline_ns'], deadline)

    def test_close_in_journal_callback_prevents_later_send(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        count = len(self.f.sock.sent)
        self.f.journal_hook = lambda event: self.obj.close()
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertFalse(self.obj.progress['restoration_verified'])

    def test_short_restore_write_is_not_repeated_even_when_readbacks_match(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.f.sock.hook = lambda raw: len(raw) - 1
        self.receive()
        self.f.sock.hook = None
        self.obj.poll_restoration()
        self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
        self.obj.poll_restoration()
        self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
        state = self.obj.evidence['core']['wire']['interval']
        self.assertEqual(state['phase'], 'done')
        self.assertTrue(state['restore_failures'])
        self.assertFalse(self.obj.progress['restoration_verified'])
        commands = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
        self.assertEqual([m.param2 for m in commands if m.command == 511], [10000, 100000])

    def test_no_owned_write_does_not_invent_restore_or_unknown_baseline(self):
        for baseline in (None, 10000):
            with self.subTest(baseline=baseline):
                self.setUp(configure=False)
                if baseline is not None:
                    self.case.query(baseline)
                self.fail_source()
                self.obj.begin_restoration('no mutation')
                if baseline is not None:
                    self.receive()  # final GET only
                    self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, baseline))
                state = self.obj.evidence['core']['wire']['interval']
                self.assertFalse(state['mutation_attempted'])
                self.assertFalse(state['restore_attempted'])
                self.assertEqual(self.obj.progress['restoration_verified'], baseline is not None)
                commands = [mav.MAVLink(None).decode(bytearray(r[0])) for r in self.f.sock.sent]
                self.assertTrue(all(m.command == 510 for m in commands))

    def test_wrong_peer_retains_actual_bytes_but_never_sends_restore(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        raw = heartbeat()
        count = len(self.f.sock.sent)
        with patch.object(self.f.sock, 'recvmsg', return_value=(raw, [], 0, ('127.0.0.1', 14589))):
            with self.assertRaises(ValueError):
                self.obj.poll_restoration()
        returns = [e for e in self.obj.evidence['receiver']['events'] if e['kind'] == 'receive_return']
        self.assertEqual(returns[-1]['data_hex'], raw.hex())
        self.assertEqual(returns[-1]['peer'], ('127.0.0.1', 14589))
        self.assertEqual(len(self.f.sock.sent), count)
        self.assertFalse(self.obj.progress['restoration_verified'])

    def test_progress_does_not_recopy_interval_history(self):
        # A frequent health check must consume the scalar view, not journal history.
        exchange_type = type(self.obj._core._wire._interval)
        with patch.object(exchange_type, 'evidence', new_callable=PropertyMock,
                          side_effect=AssertionError('history traversed by health poll')):
            self.assertFalse(self.obj.progress['restoration_finished'])
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.restore()
        with patch.object(exchange_type, 'evidence', new_callable=PropertyMock,
                          side_effect=AssertionError('history traversed by health poll')):
            self.assertTrue(self.obj.progress['restoration_verified'])

    def test_segmented_retention_stays_open_through_restore_then_seals(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SegmentedWireJournal(Path(directory) / 'wire')
            self.setUp(retention=store)
            self.fail_source()
            before = store.evidence['records']
            self.assertFalse(store.evidence['closed'])
            self.obj.begin_restoration('cleanup')
            self.restore()
            self.assertGreater(store.evidence['records'], before)
            self.assertFalse(store.evidence['closed'])
            self.obj.close()
            self.assertTrue(store.evidence['complete_retention'])
            self.assertTrue(self.obj.progress['restoration_verified'])

    def test_datagram_limit_is_shared_with_cleanup_and_no4097th_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SegmentedWireJournal(Path(directory) / 'wire')
            self.setUp(retention=store)
            self.fail_source()
            self.obj.begin_restoration('cleanup')
            self.restore()
            already = self.obj.evidence['receiver']['datagram_returns']
            for _ in range(4096 - already):
                self.receive()  # safety heartbeat only; no new command or normal fanout
            self.assertEqual(self.obj.evidence['receiver']['datagram_returns'], 4096)
            reads, writes = len(self.f.sock.reads), len(self.f.sock.sent)
            with self.assertRaises(ValueError):
                self.receive()
            self.assertEqual(len(self.f.sock.reads), reads)
            self.assertEqual(len(self.f.sock.sent), writes)
            self.assertFalse(self.obj.progress['restoration_verified'])
            self.obj.close()

    def test_repeated_refused_cleanup_does_not_grow_terminal_evidence(self):
        self.fail_source()
        self.obj.begin_restoration('cleanup')
        self.f.sock.input.append(heartbeat(base=128))
        with self.assertRaises(ValueError):
            self.obj.poll_restoration()
        before = self.obj.evidence
        for _ in range(100):
            for action in (lambda: self.obj.begin_restoration('retry'), self.obj.poll_restoration):
                with self.assertRaises(ValueError):
                    action()
        self.assertEqual(self.obj.evidence, before)

    def test_source_failure_outcomes_match_synchronous_oracle(self):
        for scenario in ('body', 'lost_apply_ack', 'short_restore'):
            with self.subTest(scenario=scenario):
                self.setUp(configure=scenario != 'lost_apply_ack')
                if scenario == 'lost_apply_ack':
                    self.case.query(100000)
                    self.obj.poll_interval()
                self.fail_source()
                self.obj.begin_restoration('cleanup')
                if scenario == 'short_restore':
                    self.f.sock.hook = lambda raw: len(raw) - 1
                    self.receive()
                    self.f.sock.hook = None
                    self.obj.poll_restoration()
                    self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
                    self.obj.poll_restoration()
                    self.receive(self.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
                else:
                    self.restore()
                class OracleTransport:
                    def __init__(self, selected):
                        self.scenario = selected
                        self.values = iter([100000, 100000, 100000] if selected == 'lost_apply_ack'
                                           else [100000, 10000, 100000, 100000])
                    def read_interval(self, message_id):
                        return [{'message_id': 111, 'interval_us': next(self.values)}]
                    def set_interval(self, message_id, value):
                        if (self.scenario == 'lost_apply_ack' and value == 10000
                                or self.scenario == 'short_restore' and value == 100000):
                            raise OSError('ambiguous effect')
                        return True
                expected = TimesyncIntervalTransaction(OracleTransport(scenario)).run(lambda: False)
                actual = self.obj.evidence['core']['wire']['interval']
                for field in ('baseline_us', 'final_us', 'mutation_attempted', 'restore_attempted',
                              'modeled_transaction_pass'):
                    self.assertEqual(actual[field], expected[field], (scenario, field))
                self.assertEqual(bool(actual['primary_failure']), bool(expected['primary_failure']))
                self.assertEqual(bool(actual['restore_failures']), bool(expected['restore_failures']))


class CleanupStorageTests(unittest.TestCase):
    def test_phase_failure_still_closes_owned_listener_and_store(self):
        case = storage_fixtures.SegmentedCompositionTests('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.complete()
        with patch.object(case.store, 'phase', side_effect=OSError('phase bookkeeping failed')):
            with self.assertRaises(OSError):
                case.obj.close()
        self.assertEqual(case.f.backend.used[3].closed, 1)
        self.assertTrue(case.store.evidence['closed'])
