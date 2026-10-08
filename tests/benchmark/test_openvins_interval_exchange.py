"""Nonblocking command state tests; injected transport, no networking."""
import copy
import unittest

from tools.benchmark import openvins_timesync_interval as module


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(module, 'IntervalExchange'), 'nonblocking interval exchange missing')
        self.now = 100
        self.sent = []
        self.guard_modes = []
        self.send_error = None
        self.guard_error = None
        self.exchange = module.IntervalExchange(self.send, self.guard, lambda: self.now, self.now)

    def send(self, operation, value):
        self.sent.append((operation, value))
        if self.send_error:
            raise self.send_error

    def guard(self, stopping):
        self.guard_modes.append(stopping)
        if self.guard_error:
            raise self.guard_error

    def ack(self, command, result=0):
        self.exchange.feed({'kind': 'ack', 'command': command, 'result': result}, self.now)

    def interval(self, value):
        self.exchange.feed({'kind': 'interval', 'message_id': 111, 'interval_us': value}, self.now)

    def query(self, value, reverse=False):
        self.exchange.poll()
        self.assertEqual(self.sent[-1], ('get', None))
        if reverse:
            self.ack(510)
            self.interval(value)
        else:
            self.interval(value)
            self.ack(510)
        self.exchange.poll()

    def body_ready(self):
        self.query(100000)
        self.exchange.poll()
        self.ack(511)
        self.exchange.poll()
        self.query(10000, reverse=True)
        self.assertEqual(self.exchange.evidence['phase'], 'body')

    def restore(self):
        self.exchange.poll()
        self.assertEqual(self.sent[-1], ('set', 100000))
        self.ack(511)
        self.exchange.poll()
        self.query(100000)
        self.query(100000, reverse=True)

    def test_normal_success_matches_oracle_and_one_effect_per_poll(self):
        self.body_ready()
        before = len(self.sent)
        for _ in range(20):
            self.exchange.poll()  # Heartbeat owner is free to run between polls.
        self.assertEqual(len(self.sent), before)
        self.exchange.body_complete(True)
        self.restore()
        evidence = self.exchange.evidence
        self.assertEqual(evidence['phase'], 'done')
        self.assertTrue(evidence['modeled_transaction_pass'])
        self.assertFalse(evidence['network_authorized'])
        self.assertEqual(self.sent, [('get', None), ('set', 10000), ('get', None),
                                    ('set', 100000), ('get', None), ('get', None)])
        class Oracle:
            values = iter([100000, 10000, 100000, 100000])
            def read_interval(self, _):
                return [{'message_id': 111, 'interval_us': next(self.values)}]
            def set_interval(self, *args):
                return True
        expected = module.TimesyncIntervalTransaction(Oracle()).run(lambda: True)
        for field in ['baseline_us', 'final_us', 'mutation_attempted', 'restore_attempted', 'modeled_transaction_pass']:
            self.assertEqual(evidence[field], expected[field])

    def test_already_candidate_no_owned_write(self):
        self.query(10000)
        self.exchange.body_complete(True)
        self.query(10000)
        self.assertTrue(self.exchange.evidence['modeled_transaction_pass'])
        self.assertEqual(self.sent, [('get', None), ('get', None)])

    def test_partial_reply_does_not_finish_or_extend_operation(self):
        self.exchange.poll()
        self.interval(100000)
        self.now += 1_999_999_999
        self.exchange.poll()
        self.assertEqual(len(self.sent), 1)
        self.now += 1
        self.exchange.poll()
        self.assertEqual(self.exchange.evidence['phase'], 'done')
        self.assertIn('timeout', self.exchange.evidence['primary_failure'])
        self.assertFalse(self.exchange.evidence['mutation_attempted'])

    def test_lost_apply_ack_restores_once_without_retry(self):
        self.query(100000)
        self.exchange.poll()
        self.now += 2_000_000_000
        self.exchange.poll()
        first_failure = self.exchange.evidence['primary_failure']
        self.restore()
        self.assertEqual([v for op, v in self.sent if op == 'set'], [10000, 100000])
        self.assertEqual(self.exchange.evidence['primary_failure'], first_failure)
        self.assertFalse(self.exchange.evidence['modeled_transaction_pass'])
        self.assertIn(True, self.guard_modes)

    def test_failed_send_still_owns_mutation_and_restores(self):
        self.query(100000)
        self.send_error = OSError('ambiguous write')
        self.exchange.poll()
        self.assertTrue(self.exchange.evidence['mutation_attempted'])
        self.send_error = None
        self.restore()
        self.assertIn('ambiguous write', self.exchange.evidence['primary_failure'])

    def test_duplicate_and_wrong_responses_fail(self):
        for response in [dict(kind='ack', command=511, result=0),
                         dict(kind='interval', message_id=110, interval_us=10000),
                         dict(kind='ack', command=510.0, result=0)]:
            self.setUp()
            self.exchange.poll()
            self.exchange.feed(response, self.now)
            self.assertIsNotNone(self.exchange.evidence['primary_failure'])
        self.setUp()
        self.exchange.poll()
        self.interval(100000)
        self.interval(100000)
        self.assertIn('duplicate', self.exchange.evidence['primary_failure'])

    def test_stale_future_and_timeout_response_refused(self):
        for when in [99, 101, 2_000_000_100]:
            self.setUp()
            self.exchange.poll()
            if when > 1000:
                self.now = when
            self.exchange.feed(dict(kind='ack', command=510, result=0), when)
            self.assertIsNotNone(self.exchange.evidence['primary_failure'])

    def test_stop_deadline_immutable_and_repeated_stop_does_not_cancel_restore(self):
        self.body_ready()
        self.exchange.stop('source lost')
        deadline = self.exchange.evidence['cleanup_deadline_ns']
        self.exchange.poll()
        self.now += 1
        self.exchange.stop('second reason')
        self.assertEqual(self.exchange.evidence['cleanup_deadline_ns'], deadline)
        self.assertEqual(self.exchange.evidence['pending']['command'], 511)
        self.now = deadline
        self.exchange.poll()
        self.assertEqual(self.exchange.evidence['phase'], 'done')
        self.assertEqual(len([x for x in self.sent if x == ('set', 100000)]), 1)
        self.assertFalse(self.exchange.evidence['modeled_transaction_pass'])

    def test_startup_expiry_in_body_allows_only_restore(self):
        self.body_ready()
        self.now = 8_000_000_100
        self.exchange.poll()
        self.assertEqual(self.exchange.evidence['phase'], 'restore')
        self.restore()
        self.assertIn('startup', self.exchange.evidence['primary_failure'])

    def test_identity_guard_and_clock_regression_prevent_restore_send(self):
        self.body_ready()
        self.exchange.stop('source lost')
        count = len(self.sent)
        self.guard_error = ValueError('armed or owner changed')
        self.exchange.poll()
        self.assertEqual(len(self.sent), count)
        self.assertEqual(self.exchange.evidence['phase'], 'done')
        self.setUp()
        self.body_ready()
        self.now = 99
        self.exchange.poll()
        self.assertEqual(self.exchange.evidence['phase'], 'done')
        self.assertFalse(self.exchange.evidence['restore_attempted'])

    def test_restore_failure_keeps_primary_and_independent_readbacks(self):
        self.body_ready()
        self.exchange.body_complete(False)
        self.exchange.poll()
        self.ack(511, 4)
        self.query(100000)
        self.query(100000)
        evidence = self.exchange.evidence
        self.assertIn('body', evidence['primary_failure'])
        self.assertTrue(evidence['restore_failures'])
        self.assertEqual(evidence['final_us'], 100000)
        self.assertFalse(evidence['modeled_transaction_pass'])

    def test_evidence_is_copy_and_completion_cannot_restart(self):
        self.query(10000)
        self.exchange.body_complete(True)
        self.query(10000)
        state = self.exchange.evidence
        state['events'].clear()
        self.assertTrue(self.exchange.evidence['events'])
        count = len(self.sent)
        for _ in range(3):
            self.exchange.poll()
        self.assertEqual(len(self.sent), count)
        self.assertEqual(self.exchange.evidence, copy.deepcopy(self.exchange.evidence))

    def test_identity_change_while_final_pending_cannot_qualify(self):
        self.query(10000)
        self.exchange.body_complete(True)
        self.exchange.poll()
        self.guard_error = ValueError('owner replaced during final readback')
        self.interval(10000)
        self.ack(510)
        self.exchange.poll()
        self.assertFalse(self.exchange.evidence['modeled_transaction_pass'])
        self.assertIsNotNone(self.exchange.evidence['primary_failure'])
        self.assertIsNotNone(self.exchange.evidence.get('terminal_pending'))
        self.assertEqual(self.exchange.evidence['terminal_pending']['command'], 510)

    def test_post_completion_unsolicited_reply_revokes_success(self):
        self.query(10000)
        self.exchange.body_complete(True)
        self.query(10000)
        self.ack(510)
        self.assertFalse(self.exchange.evidence['modeled_transaction_pass'])
        self.assertIn('terminal', self.exchange.evidence['primary_failure'])

    def test_callback_crossing_deadline_records_effect_and_restoration(self):
        self.query(100000)
        def slow_send(operation, value):
            self.sent.append((operation, value))
            self.now += 2_000_000_000
        self.exchange._send = slow_send
        self.exchange.poll()
        self.assertTrue(self.exchange.evidence['mutation_attempted'])
        self.assertIn('timeout', self.exchange.evidence['primary_failure'])
        self.exchange._send = self.send
        self.restore()

    def test_send_interruption_retained_before_reraise_and_one_restore(self):
        self.query(100000)
        self.send_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.exchange.poll()
        self.assertTrue(self.exchange.evidence['mutation_attempted'])
        self.send_error = None
        self.restore()
        self.assertIn('KeyboardInterrupt', self.exchange.evidence['primary_failure'])

    def test_readback_mismatch_still_reads_final_without_new_write(self):
        self.body_ready()
        self.exchange.body_complete(True)
        self.exchange.poll()
        self.ack(511)
        self.exchange.poll()
        self.query(10000)
        self.query(100000)
        self.assertEqual(self.exchange.evidence['final_us'], 100000)
        self.assertTrue(self.exchange.evidence['restore_failures'])
        self.assertFalse(self.exchange.evidence['modeled_transaction_pass'])

    def test_reentrant_guard_prevents_send(self):
        def bad_guard(stopping):
            self.exchange.poll()
        self.exchange._guard = bad_guard
        self.exchange.poll()
        self.assertFalse(self.sent)
        self.assertEqual(self.exchange.evidence['phase'], 'done')

    def test_repeated_terminal_input_retains_one_failure_without_unbounded_growth(self):
        self.exchange.stop('cancel before mutation')
        for _ in range(200):
            self.ack(510)
        self.assertLessEqual(len(self.exchange.evidence['restore_failures']), 1)
        self.assertEqual(self.exchange.evidence['primary_failure'], 'cancel before mutation')

    def test_progress_has_no_history_and_cannot_mutate_state(self):
        self.assertTrue(hasattr(self.exchange, 'progress'), 'bounded scalar exchange progress missing')
        self.exchange.poll()
        state = self.exchange.progress
        self.assertNotIn('events', state)
        self.assertNotIn('pending', state)
        self.assertEqual(state['phase'], 'baseline')
        state['phase'] = 'done'
        self.assertEqual(self.exchange.progress['phase'], 'baseline')
        self.exchange.stop('source failure')
        self.assertEqual(self.exchange.progress['failure'], 'source failure')
