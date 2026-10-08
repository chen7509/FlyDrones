"""Capture driver through real receive/codec objects, injected I/O only."""
import unittest
from datetime import timedelta
from types import SimpleNamespace

from tests.benchmark import test_openvins_observed_interval as fixtures
from tests.benchmark.test_openvins_wire_bootstrap import Connection, body, frame, mav
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tests.benchmark.test_openvins_wire_maintenance import status


class CaptureDriverTests(unittest.TestCase):
    def setUp(self):
        from tools.benchmark import capture_disarmed_sensors as capture
        self.assertTrue(hasattr(capture, 'bind_capture_wire'), 'capture wire registration missing')
        self.case = fixtures.ObservedIntervalTests('runTest')
        self.case.setUp()
        self.f = self.case.f
        self.callbacks, self.cleanup, self.errors = [], [], []
        self.result = dict(status='incomplete', errors=self.errors)
        self.fixture = SimpleNamespace(on_post_update=self.callbacks.append)
        self.journal = SimpleNamespace(cleanup=lambda label, action, priority: self.cleanup.append((priority, action)))
        self.original = []
        self.driver = capture.bind_capture_wire(
            self.fixture, self.journal, self.result, self.case.obj,
            lambda info, ecm: self.original.append((info, ecm)),
            total_deadline_ns=300_000_000_010)
        self.seen_commands = 0
        self.interval_us = 100000

    def tick(self, *, ack=True):
        before = len(self.f.sock.sent)
        self.driver.tick()
        emitted = []
        for row in self.f.sock.sent[before:]:
            msg = mav.MAVLink(None).decode(bytearray(row[0]))
            if msg.get_type() == 'COMMAND_LONG':
                emitted.append(msg)
        self.assertLessEqual(len(emitted), 1)
        for msg in emitted:
            if msg.command == 511:
                self.interval_us = int(msg.param2)
            if ack:
                enc = mav.MAVLink(None, srcSystem=9, srcComponent=1)
                response = self.case.ack(msg.command).pack(enc)
                if msg.command == 510:
                    response += mav.MAVLink_message_interval_message(111, self.interval_us).pack(enc)
                self.f.sock.input.append(heartbeat() + response)

    def until(self, predicate, limit=30):
        for _ in range(limit):
            if predicate():
                return
            self.tick()
        self.fail(str(self.driver.progress))

    def bootstrap(self):
        self.until(lambda: self.case.obj.progress['interval_phase'] == 'body')
        self.f.enqueue(0)
        self.tick()
        self.until(lambda: self.case.obj.progress['phase'] == 'stream_ready')
        for index in range(1, 500):
            self.f.backend.now += 10_000_000
            self.f.clock_to(body(index)[0])
            self.f.enqueue(index)
            self.tick()
            self.f.backend.connections[2].reads.append(frame(index))
            self.tick()
        self.f.backend.connections[2].reads.extend([b'\0\0', b''])
        self.f.backend.connections.append(Connection([status(499, 1)]))
        self.until(lambda: self.driver.progress['phase'] == 'maintenance')
        self.tick()  # maintenance boundary snapshot

    def test_driver_bootstrap_restore_two_maintenance_pairs_and_normal_close(self):
        self.assertEqual(len(self.callbacks), 1)
        self.assertEqual([p for p, _ in self.cleanup], [15])
        self.assertFalse(self.driver.progress['ready'])
        self.bootstrap()
        self.assertEqual(self.interval_us, 100000)
        for index in (500, 501):
            self.f.backend.now += 10_000_000
            self.f.clock_to(body(index)[0])
            self.f.enqueue(index)
            self.tick()
            self.f.backend.connections[3].reads.append(status(index, index - 498))
            self.tick()
        self.assertTrue(self.driver.progress['ready'])
        self.assertEqual(self.case.obj.progress['maintenance_correlated_samples'], 2)
        self.driver.request_stop()
        self.tick()
        self.assertTrue(self.driver.progress['closed'])
        self.assertFalse(self.driver.progress['ready'])
        self.assertTrue(self.f.sock.closed)
        self.assertEqual(self.f.backend.used[3].closed, 1)
        self.assertFalse(self.errors)

    def test_source_failure_restores_before_socket_close_and_no_readiness(self):
        self.until(lambda: self.case.obj.progress['interval_phase'] == 'body')
        self.f.source_hook = lambda: (_ for _ in ()).throw(ValueError('source gone'))
        self.tick()
        self.assertTrue(self.driver.progress['failure'])
        self.assertFalse(self.f.sock.closed)
        self.until(lambda: self.driver.progress['closed'])
        self.assertTrue(self.case.obj.progress['restoration_verified'])
        self.assertEqual(self.interval_us, 100000)
        self.assertFalse(self.driver.progress['ready'])
        self.assertTrue(self.f.sock.closed)
        self.assertTrue(self.errors)

    def test_cleanup_clock_deadline_does_not_allow_restore_after10s(self):
        self.until(lambda: self.case.obj.progress['interval_phase'] == 'body')
        self.driver.request_stop('abort startup')
        self.f.backend.now += 10_000_000_000
        before = len(self.f.sock.sent)
        self.tick()
        self.assertEqual(len(self.f.sock.sent), before)
        self.assertTrue(self.driver.progress['closed'])
        self.assertTrue(self.errors)

    def test_missing_maintenance_status_fails_after_original2s(self):
        self.bootstrap()
        self.f.backend.now += 10_000_000
        self.f.clock_to(body(500)[0])
        self.f.enqueue(500)
        self.tick()
        self.f.backend.now += 2_000_000_000
        self.tick()
        self.assertTrue(self.driver.progress['failure'])
        self.assertFalse(self.driver.progress['ready'])

    def test_registration_failure_closes_supplied_session_and_socket(self):
        from tools.benchmark.capture_disarmed_sensors import bind_capture_wire
        self.driver.request_stop('fixture teardown')
        self.driver.tick()
        self.case.setUp()
        def reject(callback):
            raise ValueError('registration failed')
        with self.assertRaisesRegex(ValueError, 'registration failed'):
            bind_capture_wire(SimpleNamespace(on_post_update=reject), self.journal,
                              self.result, self.case.obj, lambda *_: None,
                              total_deadline_ns=300_000_000_010)
        self.assertTrue(self.case.f.sock.closed)

    def test_post_update_is_independent_clock_and_original_callback_once(self):
        step = self.f.step + 1
        info = SimpleNamespace(iterations=step, paused=False, dt=timedelta(milliseconds=1),
                               sim_time=timedelta(milliseconds=step))
        ecm = object()
        before = self.f.lane.progress['committed_samples']
        self.callbacks[0](info, ecm)
        self.assertEqual(self.f.lane.progress['committed_samples'], before + 1)
        self.assertEqual(self.original, [(info, ecm)])
        self.assertEqual(self.f.sock.sent, [])

    def test_post_callback_failure_latches_driver_before_next_tick(self):
        # Original physics-reference callback failure must stop startup as well.
        from tools.benchmark.capture_wire_lifecycle import bind_capture_wire
        self.driver._close()
        self.case.setUp()
        callbacks = []
        marker = ValueError('reference post failed')
        driver = bind_capture_wire(SimpleNamespace(on_post_update=callbacks.append), self.journal,
                                   self.result, self.case.obj,
                                   lambda *_: (_ for _ in ()).throw(marker),
                                   total_deadline_ns=300_000_000_010)
        step = self.case.f.step + 1
        info = SimpleNamespace(iterations=step, paused=False, dt=timedelta(milliseconds=1),
                               sim_time=timedelta(milliseconds=step))
        with self.assertRaisesRegex(ValueError, 'reference post failed'):
            callbacks[0](info, None)
        self.assertTrue(driver.progress['failure'])
        self.assertEqual(driver.progress['phase'], 'stopping')

    def test_invalid_binding_deadline_closes_unbound_supplied_resources(self):
        from tools.benchmark.capture_wire_lifecycle import bind_capture_wire
        self.driver._close()
        self.case.setUp()
        with self.assertRaises(ValueError):
            bind_capture_wire(self.fixture, self.journal, self.result, self.case.obj,
                              lambda *_: None, total_deadline_ns=300_000_000_011)
        self.assertTrue(self.case.f.sock.closed)

    def test_stop_clock_failure_still_closes_and_records_failure(self):
        marker = ValueError('monotonic unavailable')
        self.f.backend.clock = lambda: (_ for _ in ()).throw(marker)
        self.driver.request_stop('capture failure')
        self.driver.tick()
        self.assertTrue(self.driver.progress['closed'])
        self.assertTrue(self.f.sock.closed)
        self.assertTrue(self.errors)

    def test_constructor_cold_clock_does_not_send_commands_before_post_update(self):
        from tests.benchmark import test_openvins_observed_wire_session as source
        from tools.benchmark.capture_wire_lifecycle import bind_capture_wire
        from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
        self.driver._close()
        fresh = source.ObservedSessionTests('runTest')
        fresh.setUp()
        fresh.obj.close()
        session = ObservedWireSession(SimpleNamespace(pid=321), source.OWNER,
                                      '/tmp/private/socket', fresh.remote, fresh.lane, fresh.sock,
                                      10, fresh.journal, fresh.descriptor_guard, backend=fresh.backend,
                                      heartbeat_sink=lambda _: None, interval_transaction=True)
        driver = bind_capture_wire(self.fixture, self.journal, self.result, session,
                                   lambda *_: None, total_deadline_ns=300_000_000_010)
        driver.tick()
        driver.tick()
        driver.tick()
        self.assertFalse(driver.progress['failure'])
        self.assertEqual(fresh.sock.sent, [])
        self.assertEqual(fresh.sock.reads, [])

    def test_managed_reader_joins_before_descriptor_close(self):
        import threading
        self.assertTrue(hasattr(self.driver, 'start'), 'capture polling owner missing')
        self.bootstrap()
        self.f.backend.now += 10_000_000
        self.f.clock_to(body(500)[0])
        self.f.enqueue(500)
        self.tick()
        self.f.backend.connections[3].reads.append(status(500, 2))
        self.tick()
        trace = []
        class RecordedThread(threading.Thread):
            def join(inner, timeout=None):
                super().join(timeout)
                trace.append(('joined', inner.is_alive()))
        close = self.f.sock.close
        def close_socket():
            trace.append(('close', self.driver._thread.is_alive()))
            close()
        self.f.sock.close = close_socket
        self.driver.start(thread_factory=RecordedThread)
        with self.assertRaises(ValueError):
            self.driver.start(thread_factory=RecordedThread)
        self.driver.finish()
        self.assertEqual(trace, [('joined', False), ('close', False)])
        self.assertTrue(self.f.sock.closed)
        self.assertFalse(self.errors)

    def test_join_timeout_does_not_close_descriptor_under_live_reader(self):
        self.assertTrue(hasattr(self.driver, 'start'), 'capture polling owner missing')
        class BlockedThread:
            def __init__(inner, **kwargs):
                inner.live = True
            def start(inner):
                pass
            def join(inner, timeout=None):
                self.assertLessEqual(timeout, 10)
            def is_alive(inner):
                return inner.live
        self.driver.start(thread_factory=BlockedThread)
        with self.assertRaisesRegex(RuntimeError, 'reader.*join'):
            self.driver.finish()
        self.assertFalse(self.f.sock.closed)
        self.assertTrue(self.errors)
        # A later confirmed exit permits descriptor cleanup, never success.
        self.driver._thread.live = False
        self.driver.finish()
        self.assertTrue(self.f.sock.closed)
        self.assertTrue(self.driver.progress['failure'])

    def test_thread_start_failure_allows_idempotent_registered_cleanup(self):
        class FailedThread:
            def __init__(inner, **kwargs):
                pass
            def start(inner):
                raise RuntimeError('thread unavailable')
            def is_alive(inner):
                return False
            def join(inner, timeout=None):
                raise RuntimeError('cannot join unstarted thread')
        with self.assertRaisesRegex(RuntimeError, 'thread unavailable'):
            self.driver.start(thread_factory=FailedThread)
        self.assertTrue(self.f.sock.closed)
        self.driver.finish()
        self.driver.finish()
        self.assertTrue(self.driver.progress['failure'])

    def test_no_new_post_update_after_stopping(self):
        before = self.f.lane.progress['committed_samples']
        self.driver.request_stop('aborted capture')
        step = self.f.step + 1
        info = SimpleNamespace(iterations=step, paused=False, dt=timedelta(milliseconds=1),
                               sim_time=timedelta(milliseconds=step))
        with self.assertRaisesRegex(ValueError, 'stopping|closed'):
            self.callbacks[0](info, None)
        self.assertEqual(self.f.lane.progress['committed_samples'], before)
        self.assertEqual(self.original, [])

    def test_socket_close_failure_is_preserved_separately_from_source_failure(self):
        self.driver.request_stop('source failed')
        self.f.backend.now += 10_000_000_000
        self.f.sock.close = lambda: (_ for _ in ()).throw(OSError('descriptor close failed'))
        self.driver.tick()
        self.assertIn('source failed', self.driver.progress['failure'])
        self.assertTrue(any('descriptor close failed' in e for e in self.errors))

    def test_concurrent_tick_refusal_latches_stopping_not_only_an_error_string(self):
        self.until(lambda: self.case.obj.progress['interval_phase'] == 'body')
        self.driver._serial.acquire()
        try:
            with self.assertRaisesRegex(ValueError, 'concurrent'):
                self.driver.tick()
        finally:
            self.driver._serial.release()
        self.assertEqual(self.driver.progress['phase'], 'stopping')
        self.assertFalse(self.driver.progress['ready'])
        self.until(lambda: self.driver.progress['closed'])
        self.assertTrue(self.case.obj.progress['restoration_verified'])


if __name__ == '__main__':
    unittest.main()
