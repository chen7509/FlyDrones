"""Actual capture runner orchestration, with external process/fixture replaced."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal


class RuntimeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(capture, 'run_capture_runtime'), 'production runner injection missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.result = dict(status='incomplete', errors=[])
        self.events = []
        self.clock = {'sim_ns': 0}
        self.process = SimpleNamespace(pid=321, args=['test-px4'], returncode=None)
        self.process.poll = lambda: self.process.returncode
        self.process.terminate = lambda: self.events.append('terminate')
        def wait(timeout):
            self.events.append(('wait', timeout))
            self.process.returncode = 0
        self.process.wait = wait
        self.process.kill = lambda: self.events.append('kill')
        self.fixture = SimpleNamespace(
            on_post_update=lambda cb: self.events.append('register'),
            finalize=lambda: self.events.append('finalize'),
            server=lambda: SimpleNamespace(run=self.step),
        )
        self.binding = SimpleNamespace(required_owned=['px4'], required_self=['worker'],
                                       register_owned=lambda *a: self.events.append('bind-process'),
                                       observe=lambda name: self.events.append(name))
        self.owner = SimpleNamespace(driver=SimpleNamespace(start=lambda: self.events.append('reader-start')))
        def bind(process, fixture, callback):
            self.assertIs(process, self.process)
            fixture.on_post_update(callback)
        self.owner.bind = bind
        self.args = dict(output=self.output, result=self.result, errors=self.result['errors'],
                         fixture=self.fixture, post_update=lambda *_: None, wire_owner=self.owner,
                         source_guard=None, binding=self.binding, owned_ready={'px4': False},
                         owned_processes={}, read_heartbeats=lambda: self.fail('legacy reader escaped'),
                         stop=threading.Event(), binary=self.output/'px4', build=self.output/'build',
                         runtime=self.output, env={}, clock=self.clock, writer=SimpleNamespace(error=None),
                         shadow=None, motion=object(), contract={'simulation_duration_ns': 25_000_000_000,
                                                               'wall_budget_s': 300}, started=0,
                         monotonic=lambda: 0, spawn=self.spawn)

    def spawn(self, command, **kwargs):
        self.events.append('spawn')
        self.assertEqual(command, [str(self.output/'px4'), '-i', '8', '-d', str(self.output/'build'/'etc')])
        self.assertFalse(kwargs['start_new_session'])
        return self.process

    def step(self, blocking, count, paused):
        self.assertEqual((blocking, count, paused), (True, 10, False))
        self.clock['sim_ns'] += count * 1_000_000
        return True

    def execute(self):
        with patch.object(capture.subprocess, 'Popen', side_effect=AssertionError('real process escaped')):
            with CaptureJournal(self.output, self.result) as journal:
                self.journal = journal
                journal.cleanup('wire', lambda: self.events.append('wire-finish'), priority=15)
                capture.run_capture_runtime(journal=journal, **self.args)
        self.assertEqual(json.loads((self.output/'result.json').read_text()), self.result)

    def test_runner_preserves25s_and_wire_cleanup_before_owned_stop(self):
        self.execute()
        self.assertEqual(self.clock['sim_ns'], 25_000_000_000)
        self.assertEqual(self.result['status'], 'capture_completed')
        self.assertEqual(self.events, ['spawn', 'bind-process', 'register', 'finalize', 'postfinalize',
                                      'reader-start', 'postfirststep', 'wire-finish', 'terminate', ('wait', 10)])

    def test_process_mapping_failure_still_stops_owned_process(self):
        self.binding.register_owned = lambda *a: (_ for _ in ()).throw(ValueError('mapping refused'))
        self.execute()
        self.assertEqual(self.result['status'], 'capture_failed')
        self.assertIn('mapping refused', str(self.result['errors']))
        self.assertEqual(self.events[-3:], ['wire-finish', 'terminate', ('wait', 10)])
        self.assertNotIn('register', self.events)

    def test_finalize_failure_does_not_start_reader(self):
        self.fixture.finalize = lambda: (_ for _ in ()).throw(ValueError('finalize refused'))
        self.execute()
        self.assertEqual(self.result['status'], 'capture_failed')
        self.assertNotIn('reader-start', self.events)
        self.assertEqual(self.events[-3:], ['wire-finish', 'terminate', ('wait', 10)])

    def test_constructor_failure_has_no_fabricated_process_exit(self):
        self.args['spawn'] = lambda *a, **kw: (_ for _ in ()).throw(OSError('spawn refused'))
        self.execute()
        self.assertEqual(self.result['status'], 'capture_failed')
        self.assertEqual(self.events, ['wire-finish'])
        self.assertNotIn('px4_exit_code', self.result)

    def test_original_wall_budget_refuses_before_first_step(self):
        self.args['monotonic'] = lambda: 300.1
        self.execute()
        self.assertEqual(self.clock['sim_ns'], 0)
        self.assertIn('wall budget', str(self.result['errors']))
        self.assertEqual(self.events[-3:], ['wire-finish', 'terminate', ('wait', 10)])

    def test_wire_cleanup_failure_keeps_capture_failed_but_does_not_leak_px4(self):
        def refused_start():
            def fail_cleanup():
                self.events.append('wire-cleanup-refused')
                raise RuntimeError('reader did not join')
            self.journal.cleanup('blocked wire', fail_cleanup, priority=15)
        self.owner.driver.start = refused_start
        self.execute()
        self.assertEqual(self.result['status'], 'capture_failed')
        self.assertIn('reader did not join', str(self.result['errors']))
        self.assertLess(self.events.index('wire-cleanup-refused'), self.events.index('terminate'))
