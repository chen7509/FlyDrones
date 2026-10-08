"""Real writer/fanout/shadow adapters; fake UDP, source clock and no native calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pymavlink  # noqa: F401
except ImportError as exc:
    raise unittest.SkipTest('existing WSL codec required') from exc

from tests.benchmark import test_openvins_wire_heartbeat as wire_fixture
from tools.benchmark import disarmed_sensor_provenance as provenance
from tools.benchmark.capture_disarmed_sensors import build_readiness, build_source_fanout, dispatch_heartbeat
from tools.benchmark.openvins_online_shadow import ShadowInput


class ForbiddenNative:
    def __init__(self):
        self.calls = []

    def send(self, *args):
        self.calls.append(args)
        raise AssertionError('heartbeat must not call native worker')


class FanoutIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.wire = wire_fixture.HeartbeatTests('runTest')
        self.wire.setUp()
        self.f = self.wire.f
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = ForbiddenNative()
        self.shadow = ShadowInput(self.native, self.root, session_id='native-test', now=self.f.backend.clock)
        self.addCleanup(self.shadow.finish)
        self.source = self.readiness = self.fanout = self.writer = None
        self.writer_finished = False
        self.terminal = None
        self.clock_patch = patch.object(provenance.time, 'monotonic_ns', self.f.backend.clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.addCleanup(self.finish_pipeline)

    def build(self, profile='ready-shadow-heartbeat-estimator-v1', capacity=4096):
        self.source, self.readiness = build_readiness(
            self.root, profile, clock=self.f.backend.clock, native_session_id='native-test')
        self.fanout = build_source_fanout(self.root, profile, self.readiness, self.shadow)
        # Synthetic shared wall basis selected before any use; not actual timing.
        self.fanout.clock = self.f.backend.clock
        self.writer = provenance.CaptureWriter(self.root, capacity=capacity, start_worker=False,
                                               sequence_records=True, on_record=self.fanout.on_record)
        self.wire.hook = lambda event: dispatch_heartbeat(event, self.writer, self.fanout)
        # Future capture guard composition: check failure, not grant ready status.
        self.f.descriptor_hook = self.check_pipeline

    def check_pipeline(self):
        if self.writer.error:
            raise ValueError(self.writer.error)
        self.fanout.proof()  # absent sensor/native readiness returns None, not success

    def finish_writer(self):
        if not self.writer_finished:
            self.writer_finished = True
            return self.writer.finish()

    def finish_pipeline(self):
        if self.writer is not None and not self.writer_finished:
            try:
                self.finish_writer()
            except RuntimeError:
                pass  # failure assertions live in their case, cleanup still closes journals
        if self.fanout is not None and not self.fanout.closed:
            self.terminal = self.fanout.finish()
        if self.readiness is not None and hasattr(self.readiness, 'finish') and not self.readiness.closed:
            self.readiness.finish()
        self.f.obj.close()

    def rows(self, name):
        return [json.loads(row) for row in (self.root / name).read_text().splitlines()]

    def assert_no_native_or_readiness(self):
        self.assertEqual(self.native.calls, [])
        self.assertEqual(self.shadow.delivery_acks, [])
        self.assertEqual(self.shadow.delivered, 0)
        self.assertEqual(self.shadow.sequence, 0)
        self.assertIsNone(self.readiness.proof())

    def test_actual_estimator_fanout_journal_queue_and_reconcile(self):
        self.build()
        self.shadow.delivery_acks = [dict(kind='C', stale_synthetic=True)]
        self.assertIsNone(self.wire.receive(wire_fixture.heartbeat()))
        self.assertEqual((self.fanout.observed, self.fanout.reconciled), (1, 0))
        self.assertEqual(len(self.fanout.observations), 1)
        self.assertEqual(self.source.records['heartbeat']['arrival_monotonic_ns'], 10)
        self.f.backend.now = 20
        self.wire.receive(wire_fixture.heartbeat())
        self.assertEqual(self.fanout.observed, 2)
        self.finish_writer()
        self.assertEqual((self.fanout.committed, self.fanout.reconciled), (2, 2))
        self.assertFalse(self.fanout.failure)
        events = self.rows('events.jsonl')
        self.assertEqual([r['source_sequence'] for r in events], [0, 1])
        self.assertEqual([r['arrival_monotonic_ns'] for r in events], [10, 20])
        log = self.rows('heartbeat-observations.jsonl')
        self.assertEqual([r['event'] for r in log],
                         ['heartbeat_observed', 'heartbeat_observed', 'heartbeat_reconciled', 'heartbeat_reconciled'])
        self.assertEqual([r['source_sha256'] for r in log[:2]], [r['source_sha256'] for r in log[2:]])
        self.assertEqual(self.source.records['heartbeat']['arrival_monotonic_ns'], 20)
        self.assert_no_native_or_readiness()
        self.assertEqual(self.f.sock.sent, [])

    def test_actual_base_journaled_fanout_route(self):
        self.build('ready-shadow-heartbeat-v1')
        self.wire.receive(wire_fixture.heartbeat())
        self.finish_writer()
        self.assertEqual((self.fanout.observed, self.fanout.reconciled), (1, 1))
        self.assert_no_native_or_readiness()

    def test_queue_full_retains_observation_but_refuses_mixed_reply(self):
        self.build(capacity=1)
        self.wire.receive(wire_fixture.heartbeat())
        self.f.backend.now = 20
        self.wire.refuse(wire_fixture.heartbeat() + wire_fixture.packet())
        self.assertEqual(self.fanout.observed, 2)
        self.assertEqual(self.writer.queue.qsize(), 1)
        self.assertTrue(self.fanout.failure)
        self.assertEqual(len(self.fanout.observations), 2)
        self.assertEqual(self.native.calls, [])

    def test_heartbeat_journal_flush_failure_refuses_before_queue(self):
        self.build()
        with patch.object(self.fanout, '_heartbeat_emit', side_effect=OSError('injected journal failure')):
            self.wire.refuse(wire_fixture.heartbeat() + wire_fixture.packet())
        self.assertEqual(self.writer.queue.qsize(), 0)
        self.assertEqual(self.fanout.observed, 0)
        self.assertTrue(self.fanout.failure)

    def test_closed_writer_retains_observation_then_refuses(self):
        self.build()
        self.finish_writer()
        self.wire.refuse(wire_fixture.heartbeat() + wire_fixture.packet())
        self.assertEqual(self.fanout.observed, 1)
        self.assertEqual(self.fanout.reconciled, 0)
        self.assertTrue(self.fanout.failure)

    def test_reconcile_tamper_latches_and_next_wire_operation_refuses(self):
        self.build()
        self.wire.receive(wire_fixture.heartbeat())
        original = self.writer.on_record
        def tamper(row, payload):
            changed = copy.deepcopy(row)
            changed['custom_mode'] += 1
            original(changed, payload)
        self.writer.on_record = tamper
        self.finish_writer()
        self.assertTrue(self.fanout.failure)
        self.assertEqual(self.fanout.reconciled, 0)
        self.assertEqual(len(self.fanout.observations), 1)
        self.wire.refuse(wire_fixture.packet())
        self.assertEqual(self.native.calls, [])

    def test_shadow_failure_before_observation_refuses_wire(self):
        self.build()
        self.shadow.failure = 'injected downstream failure'
        self.wire.refuse(wire_fixture.heartbeat() + wire_fixture.packet())
        self.assertEqual(self.fanout.observed, 0)
        self.assertEqual(self.writer.queue.qsize(), 0)

    def test_armed_wire_never_reaches_fanout_or_writer(self):
        self.build()
        self.wire.refuse(wire_fixture.heartbeat(base=128) + wire_fixture.packet())
        self.assertEqual(self.fanout.observed, 0)
        self.assertEqual(self.writer.queue.qsize(), 0)
        self.assertFalse(self.fanout.failure)

    def test_pending_reconciliation_expiry_cannot_be_refreshed_by_new_heartbeat(self):
        self.build()
        self.wire.receive(wire_fixture.heartbeat())
        self.f.backend.now = 2_000_000_011
        self.wire.refuse(wire_fixture.heartbeat() + wire_fixture.packet())
        self.assertTrue(self.fanout.failure)
        self.assertEqual(self.fanout.observed, 1)


if __name__ == '__main__':
    unittest.main()
