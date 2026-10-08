"""Production runner, real wire/fanout and managed reader; no network or physics."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.benchmark.test_openvins_observed_wire_session import Datagram
from tests.benchmark.test_openvins_wire_bootstrap import Backend, Connection, frame, mav
from tests.benchmark.test_openvins_wire_fanout_integration import ForbiddenNative
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark.capture_contract import wire_configuration_record
from tools.benchmark.capture_wire_lifecycle import CaptureWireOwner
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal, CaptureWriter
from tools.benchmark.openvins_online_shadow import ShadowInput


class RuntimeWireIntegrationTests(unittest.TestCase):
    def test25s_runner_real_reader_bootstrap_maintenance_fanout_and_shutdown(self):
        self.run_case()

    def test_source_loss_after_mutation_restores_before_owned_stop(self):
        self.run_case('source')

    def test_descriptor_replacement_refuses_restoration_and_retains_failure(self):
        self.run_case('descriptor')

    def test_owner_replacement_refuses_restoration_and_retains_failure(self):
        self.run_case('owner')

    def test_registration_failure_releases_prepared_resources(self):
        self.run_case('registration')

    def test_missing_maintenance_status_stops_completed_bootstrap(self):
        self.run_case('missing-status')

    def test_replayed_maintenance_status_is_not_new_health(self):
        self.run_case('replayed-status')

    def test_missing_restore_reply_remains_failed_before_owned_stop(self):
        self.run_case('lost-restore')

    def run_case(self, fault=None):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        if root := os.environ.get('FLYDRONES_RUNNER_EVIDENCE'):
            self.addCleanup(shutil.copytree, tmp, str(Path(root)/self._testMethodName))
        self.exercise(Path(tmp), fault)

    def exercise(self, output, fault):
        backend, sock = Backend(), Datagram()
        events, callbacks = [], []
        result = dict(status='incomplete', errors=[])
        clock, arming = {'sim_ns': 0}, {'unarmed_wall_ns': None}
        real_connect = backend.connect
        def connect(path, timeout):
            self.assertEqual(path, '/tmp/px4-sock-8')
            return real_connect('/tmp/private/socket', timeout)
        backend.connect = connect
        sock.bind = lambda address: setattr(sock, 'local', address)
        sock.setblocking = lambda flag: self.assertFalse(flag)
        sock.close = lambda: (events.append('socket-close'), setattr(sock, 'closed', True))
        native = ForbiddenNative()
        pipeline = output/'pipeline'
        pipeline.mkdir()
        shadow = ShadowInput(native, pipeline, session_id='runner-native', now=backend.clock)
        self.addCleanup(shadow.finish)
        _, readiness = capture.build_readiness(pipeline, 'ready-shadow-heartbeat-estimator-v1',
                                              clock=backend.clock, native_session_id='runner-native')
        self.addCleanup(readiness.finish)
        fanout = capture.build_source_fanout(pipeline, 'ready-shadow-heartbeat-estimator-v1', readiness, shadow)
        fanout.clock = backend.clock
        self.addCleanup(fanout.finish)
        writer = CaptureWriter(pipeline, start_worker=False, sequence_records=True, on_record=fanout.on_record)
        self.addCleanup(writer.finish)
        config = output/'wire.json'
        config.write_text(json.dumps(dict(schema='capture-wire-v1', session_id='runner-wire',
                                         sim_origin_ns=0, remote_origin_ns=1_000_000)))
        contract = dict(wire=wire_configuration_record(config), wall_budget_s=300,
                        simulation_duration_ns=25_000_000_000)
        process = SimpleNamespace(pid=321, args=['test-px4'], returncode=None)
        process.poll = lambda: process.returncode
        process.terminate = lambda: events.append('px4-stop')
        process.wait = lambda timeout: setattr(process, 'returncode', 0)
        process.kill = lambda: self.fail('unexpected kill')
        socket_calls = []
        descriptor = dict(fd=7, device=1, inode=2, mode=49152, net='net:[4]')
        lost_source = False
        def source_guard():
            if lost_source:
                raise ValueError('injected source loss')
        def socket_factory(*args):
            socket_calls.append(args)
            return sock
        def owner_factory(*args, **kwargs):
            return CaptureWireOwner(*args, **kwargs, backend=backend, socket_factory=socket_factory,
                                    descriptor_snapshot=lambda _: dict(descriptor))
        grant, done = threading.Semaphore(0), threading.Semaphore(0)
        interval_us = 100000
        def peer_response(raw):
            nonlocal interval_us
            msg = mav.MAVLink(None).decode(bytearray(raw))
            if msg.get_type() == 'COMMAND_LONG':
                if msg.command == 511:
                    interval_us = int(msg.param2)
                    events.append(('set-interval', interval_us))
                enc = mav.MAVLink(None, srcSystem=9, srcComponent=1)
                if fault == 'lost-restore' and lost_source:
                    return len(raw)
                response = mav.MAVLink_command_ack_message(msg.command, 0, 0, 0, 254, 191).pack(enc)
                if msg.command == 510:
                    response += mav.MAVLink_message_interval_message(111, interval_us).pack(enc)
                sock.input.append(heartbeat()+response)
            return len(raw)
        sock.hook = peer_response
        def pump():
            backend.now += 1000
            before = len(sock.sent)
            grant.release()
            self.assertTrue(done.acquire(timeout=3), 'managed reader did not finish scheduled tick')
            if owner.driver.failure:
                raise RuntimeError('wire reader refused: '+owner.driver.failure)
            commands = []
            for raw, _, _ in sock.sent[before:]:
                msg = mav.MAVLink(None).decode(bytearray(raw))
                if msg.get_type() == 'COMMAND_LONG':
                    commands.append(msg)
            self.assertLessEqual(len(commands), 1)
            while not writer.queue.empty():
                writer._write_event(*writer.queue.get_nowait())
        def until(predicate):
            for _ in range(30):
                if predicate():
                    return
                pump()
            self.fail(str(owner.driver.session.progress))
        step = 0
        def server_run(blocking, count, paused):
            nonlocal step, lost_source
            self.assertEqual((blocking, count, paused), (True, 10, False))
            for _ in range(count):
                step += 1
                backend.now += 500000
                if step == 120:
                    if fault in ('source', 'lost-restore'):
                        lost_source = True
                    elif fault == 'descriptor':
                        descriptor['inode'] = 99
                    elif fault == 'owner':
                        backend.owner['start_ticks'] += 1
                callbacks[0](SimpleNamespace(iterations=step, paused=False, dt=timedelta(milliseconds=1),
                                              sim_time=timedelta(milliseconds=step)), None)
                if step < 100 or (step-100) % 20:
                    continue
                index = (step-100)//20
                if index == 0:
                    until(lambda: owner.driver.session.progress['interval_phase'] == 'body')
                enc = mav.MAVLink(None, srcSystem=9, srcComponent=1)
                enc.seq = index % 256
                if index % 25 == 0:
                    sock.input.append(heartbeat())
                    pump()
                sock.input.append(mav.MAVLink_timesync_message(0, step*1000000).pack(enc))
                pump()
                if index == 0:
                    until(lambda: owner.driver.session.progress['phase'] == 'stream_ready')
                elif index < 500:
                    backend.connections[2].reads.append(frame(index))
                    pump()
                else:
                    if index == 500 and fault == 'missing-status':
                        backend.now += 2_000_000_000
                    elif index == 500 and fault == 'replayed-status':
                        backend.connections[3].reads.append(status(499, 2))
                    else:
                        backend.connections[3].reads.append(status(index, index-498))
                    pump()
                if index == 499:
                    backend.connections[2].reads.extend([b'\0\0', b''])
                    backend.connections.append(Connection([status(499, 1)]))
                    until(lambda: owner.driver.phase == 'maintenance')
                if index >= 500:
                    self.assertTrue(owner.health_ready())
            return True
        def register(callback):
            if fault == 'registration':
                raise ValueError('injected registration failure')
            callbacks.append(callback)
        fixture = SimpleNamespace(on_post_update=register, finalize=lambda: events.append('finalize'),
                                  server=lambda: SimpleNamespace(run=server_run))
        def original_post(info, ecm):
            clock['sim_ns'] = int(info.sim_time.total_seconds()*1000000000)
        def forbidden(*args, **kwargs):
            raise AssertionError('real Gazebo/native constructor escaped')
        forbidden_module = SimpleNamespace(TestFixture=forbidden, Server=forbidden, Node=forbidden)
        with patch('time.monotonic_ns', backend.clock), \
                patch.dict(sys.modules, {'gz.sim8': forbidden_module, 'gz.transport13': forbidden_module}), \
                patch('tools.benchmark.openvins_online_shadow.NativeClient', side_effect=forbidden), \
                patch.object(capture.socket, 'socket', side_effect=AssertionError('real UDP escaped')), \
                patch.object(capture.subprocess, 'Popen', side_effect=AssertionError('real PX4 escaped')):
            with CaptureJournal(output, result) as journal:
                receiver, owner = capture.prepare_capture_receiver(
                    contract, journal=journal, result=result, output=output, start_ns=10,
                    source_guard=source_guard,
                    heartbeat_sink=lambda event: capture.dispatch_capture_heartbeat(
                        event, writer, fanout, arming, None, {'px4': False}, {'px4': process}),
                    legacy_factory=lambda: self.fail('legacy receive owner escaped'), wire_factory=owner_factory)
                self.assertIsNone(receiver)
                real_bind = owner.bind
                def bind(*args):
                    real_bind(*args)
                    tick = owner.driver.tick
                    def scheduled_tick():
                        # Only scheduling is injected; actual tick still runs on
                        # its actual managed Python reader and enforces ownership.
                        if owner.driver.phase == 'stopping':
                            backend.now += 100000000 if fault == 'lost-restore' else 1000
                            return tick()
                        if not grant.acquire(timeout=.002):
                            return owner.driver.progress
                        try:
                            return tick()
                        finally:
                            done.release()
                    owner.driver.tick = scheduled_tick
                owner.bind = bind
                capture.run_capture_runtime(
                    journal=journal, output=output, result=result, errors=result['errors'], fixture=fixture,
                    post_update=original_post, wire_owner=owner, source_guard=None, binding=None,
                    owned_ready={'px4': False}, owned_processes={}, read_heartbeats=lambda: self.fail('legacy thread'),
                    stop=threading.Event(), binary=output/'px4', build=output/'build', runtime=output, env={},
                    clock=clock, writer=writer, shadow=shadow, motion=object(), contract=contract, started=0,
                    spawn=lambda *a, **kw: process, monotonic=lambda: backend.now/1000000000)
            if fault:
                self.assertEqual(result['status'], 'capture_failed')
                self.assertTrue(result['errors'])
                self.assertLess(step, 25000)
                self.assertEqual(native.calls, [])
                self.assertTrue(sock.closed)
                self.assertLess(events.index('socket-close'), events.index('px4-stop'))
                if fault == 'registration':
                    self.assertEqual(step, 0)
                    self.assertEqual(callbacks, [])
                else:
                    self.assertFalse(owner.driver._thread.is_alive())
                    self.assertFalse(owner.driver.progress['ready'])
                    if fault in ('source', 'lost-restore'):
                        self.assertIn('injected source loss', str(result['errors']))
                        self.assertEqual(owner.driver.session.progress['restoration_verified'], fault == 'source')
                        self.assertEqual(interval_us, 100000)
                        self.assertLess(events.index(('set-interval', 100000)), events.index('px4-stop'))
                    elif fault in ('descriptor', 'owner'):
                        self.assertFalse(owner.driver.session.progress['restoration_verified'])
                        self.assertEqual(interval_us, 10000)
                    else:
                        self.assertGreaterEqual(step, 10100)
                        self.assertEqual(interval_us, 100000)
                        self.assertTrue(owner.driver.session.progress['interval_transaction_pass'])
                with self.assertRaises(ValueError):
                    owner.health_ready()
                return
            self.assertEqual(result['status'], 'capture_completed', str(result['errors']))
            self.assertEqual(step, 25000)
            self.assertEqual(len(callbacks), 1)
            self.assertEqual(len(socket_calls), 1)
            self.assertEqual(interval_us, 100000)
            self.assertGreaterEqual(owner.driver.session.progress['maintenance_correlated_samples'], 2)
            self.assertFalse(owner.driver._thread.is_alive())
            self.assertLess(events.index('socket-close'), events.index('px4-stop'))
            self.assertGreater(fanout.reconciled, 7)
            self.assertEqual(fanout.reconciled, fanout.observed)
            self.assertEqual(native.calls, [])
            self.assertIsNone(readiness.proof())
            self.assertFalse(result['wire_lifecycle']['fusion_qualified'])
            self.assertTrue((output/'wire-lifecycle.json').is_file())
