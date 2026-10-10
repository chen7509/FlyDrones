"""Selected capture resource path with real protocol classes and injected I/O."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.benchmark import test_capture_wire_lifecycle as driver_cases
from tests.benchmark.test_openvins_wire_bootstrap import body
from tests.benchmark.test_openvins_wire_maintenance import status


class WireOwnerTests(unittest.TestCase):
    def setUp(self):
        from tools.benchmark import capture_wire_lifecycle as module
        self.assertTrue(hasattr(module, 'CaptureWireOwner'), 'capture resource owner missing')
        self.module = module
        self.case = driver_cases.CaptureDriverTests('runTest')
        self.case.setUp()
        self.case.driver._close()
        # The fixture's unused cold session has intentionally failed on close.
        # The subsequently constructed selected owner is a separate capture.
        self.preparation_errors = tuple(self.case.errors)
        self.case.errors = []
        self.case.result = dict(status='incomplete', errors=self.case.errors)
        self.case.case.setUp()
        self.f = self.case.case.f
        self.f.obj.close()
        self.f.backend = type(self.f.backend)()
        fixture_connect = self.f.backend.connect
        def connect(path, timeout):
            self.assertEqual(path, '/tmp/px4-sock-8')
            return fixture_connect('/tmp/private/socket', timeout)
        self.f.backend.connect = connect
        # Fresh selected descriptor, with all OS interactions injected.
        self.f.sock.closed = False
        self.f.sock.bind = lambda address: setattr(self.f.sock, 'local', address)
        self.f.sock.setblocking = lambda flag: self.assertFalse(flag)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        def socket_factory(*args):
            self.calls.append(args)
            return self.f.sock
        from tools.benchmark.capture_disarmed_sensors import prepare_capture_receiver
        self.clock_patch = patch('time.monotonic_ns', self.f.backend.clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        config = dict(schema='capture-wire-v1', session_id='capture-test', sim_origin_ns=0,
                      remote_origin_ns=1_000_000)
        from tools.benchmark.capture_contract import wire_configuration_record
        config_path = Path(self.tmp.name) / 'wire.json'
        config_path.write_text(json.dumps(config))
        def wire_factory(*a, **kw):
            return module.CaptureWireOwner(*a, **kw, socket_factory=socket_factory, backend=self.f.backend,
                                          descriptor_snapshot=lambda sock: dict(fd=7, device=1, inode=2,
                                                                               mode=49152, net='net:[4]'))
        legacy, self.owner = prepare_capture_receiver(
            {'wall_budget_s': 300, 'wire': wire_configuration_record(config_path)},
            journal=self.case.journal, result=self.case.result, output=Path(self.tmp.name), start_ns=10,
            source_guard=self.f.source_guard, heartbeat_sink=lambda _: None, wire_factory=wire_factory,
            legacy_factory=lambda: self.fail('legacy reader constructed in wire mode'))
        self.assertIsNone(legacy)

    def test_prepare_bind_drive_and_close_the_selected_owner(self):
        from tests.benchmark.test_openvins_wire_fanout_integration import ForbiddenNative
        from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
        from tools.benchmark.capture_disarmed_sensors import (
            build_readiness,
            build_source_fanout,
            dispatch_capture_heartbeat,
        )
        from tools.benchmark.disarmed_sensor_provenance import CaptureWriter
        from tools.benchmark.openvins_online_shadow import ShadowInput
        pipeline = Path(self.tmp.name) / 'pipeline'
        pipeline.mkdir()
        native = ForbiddenNative()
        shadow = ShadowInput(native, pipeline, session_id='native-test', now=self.f.backend.clock)
        self.addCleanup(shadow.finish)
        _, readiness = build_readiness(pipeline, 'ready-shadow-heartbeat-estimator-v1',
                                       clock=self.f.backend.clock, native_session_id='native-test')
        self.addCleanup(readiness.finish)
        fanout = build_source_fanout(pipeline, 'ready-shadow-heartbeat-estimator-v1', readiness, shadow)
        fanout.clock = self.f.backend.clock
        self.addCleanup(fanout.finish)
        writer = CaptureWriter(pipeline, start_worker=False, sequence_records=True, on_record=fanout.on_record)
        self.addCleanup(writer.finish)
        arming = {'unarmed_wall_ns': None}
        self.owner.heartbeat_sink = lambda event: dispatch_capture_heartbeat(
            event, writer, fanout, arming, None, {'px4': False}, {'px4': object()})
        original_tick = self.case.tick
        def tick(**kwargs):
            self.f.backend.now += 1000
            original_tick(**kwargs)
            # Deterministic serial drain through the actual writer, not a mocked
            # success callback or a measurement of asynchronous latency.
            while not writer.queue.empty():
                writer._write_event(*writer.queue.get_nowait())
        self.case.tick = tick
        callbacks = []
        self.owner.bind(SimpleNamespace(pid=321), SimpleNamespace(on_post_update=callbacks.append), lambda *_: None)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(callbacks), 1)
        self.case.driver = self.owner.driver
        self.case.case.obj = self.f.obj = self.owner.driver.session
        self.case.f = self.f
        self.f.lane, self.f.step = self.owner.lane, 0
        def clock_to(ns):
            while self.f.step * 1_000_000 < ns:
                self.f.step += 1
                callbacks[0](SimpleNamespace(iterations=self.f.step, paused=False,
                                             dt=timedelta(milliseconds=1),
                                             sim_time=timedelta(milliseconds=self.f.step)), object())
        self.f.clock_to = clock_to
        self.f.clock_to(body(0)[0])
        self.case.bootstrap()
        for index in (500, 501):
            self.f.backend.now += 10_000_000
            self.f.clock_to(body(index)[0])
            self.f.enqueue(index)
            self.case.tick()
            self.f.backend.connections[3].reads.append(status(index, index - 498))
            self.case.tick()
        self.assertTrue(self.owner.health_ready())
        self.f.sock.input.append(heartbeat())
        self.case.tick()
        self.assertGreaterEqual(fanout.reconciled, 7)
        self.assertEqual(fanout.reconciled, fanout.observed)
        self.assertEqual(arming['unarmed_wall_ns'], self.f.backend.now)
        self.assertIsNone(readiness.proof())  # transport success cannot grant VIO readiness
        self.assertEqual(native.calls, [])
        self.owner.finish()
        self.assertTrue(self.f.sock.closed)
        self.assertTrue((Path(self.tmp.name) / 'wire-lifecycle.json').is_file())
        self.assertFalse(self.case.errors)

    def test_close_prepared_but_unbound_records_failure_and_releases_descriptor(self):
        self.owner.finish()
        self.assertTrue(self.f.sock.closed)
        self.assertTrue(self.case.errors)
        self.assertFalse(self.case.result['wire_lifecycle']['fusion_qualified'])

    def test_changed_descriptor_before_bind_refuses_and_releases_it(self):
        self.owner.snapshot = lambda _: dict(fd=8, device=1, inode=3, mode=49152, net='net:[1]')
        with self.assertRaises(ValueError):
            self.owner.bind(SimpleNamespace(pid=321), self.case.fixture, lambda *_: None)
        self.owner.finish()
        self.assertTrue(self.f.sock.closed)
        self.assertTrue(self.case.errors)

    def test_owned_process_in_different_network_namespace_is_refused(self):
        self.f.backend.owner['net'] = 'net:[999]'
        with self.assertRaisesRegex(ValueError, 'namespace'):
            self.owner.bind(SimpleNamespace(pid=321), self.case.fixture, lambda *_: None)
        self.owner.finish()
        self.assertTrue(self.f.sock.closed)
