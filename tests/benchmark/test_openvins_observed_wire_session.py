"""Real pinned codec and interfaces; injected sockets/process backend, no UDP."""
import copy
import socket
import unittest
from collections import deque
from datetime import timedelta
from types import SimpleNamespace

try:
    from pymavlink.dialects.v20 import common as mav
except ImportError as exc:
    raise unittest.SkipTest('pinned codec tests require existing WSL installation') from exc

from tests.benchmark.check_openvins_owned_bootstrap import body, frame
from tests.benchmark.test_openvins_wire_bootstrap import OWNER, Backend
from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.openvins_simulation_clock import JournaledSimulationClock


class Datagram:
    family, type, proto = socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP

    def __init__(self):
        self.input, self.sent, self.reads = deque(), [], []
        self.local, self.closed = ('127.0.0.1', 14548), False
        self.hook = None

    def getsockname(self):
        return self.local

    def gettimeout(self):
        return 0.0

    def recvmsg(self, *args):
        self.reads.append(args)
        if not self.input:
            raise BlockingIOError()
        return self.input.popleft(), [], 0, ('127.0.0.1', 14588)

    def sendto(self, raw, flags, peer):
        self.sent.append((raw, flags, peer))
        return self.hook(raw) if self.hook else len(raw)

    def close(self):
        self.closed = True


class ObservedSessionTests(unittest.TestCase):
    def setUp(self):
        from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
        self.backend, self.sock, self.events = Backend(), Datagram(), []
        self.journal_hook = self.descriptor_hook = self.source_hook = None
        self.remote = RemoteMonotonicClock('observed', sim_origin_ns=0, remote_origin_ns=1_000_000)
        self.lane = JournaledSimulationClock('observed', self.backend.clock, lambda _: None, 10, self.source_guard)
        self.step = 0
        self.obj = ObservedWireSession(SimpleNamespace(pid=321), OWNER, '/tmp/private/socket', self.remote,
                                       self.lane, self.sock, 10, self.journal, self.descriptor_guard,
                                       backend=self.backend)

    def source_guard(self):
        return self.source_hook() if self.source_hook else None

    def descriptor_guard(self, sock):
        self.assertIs(sock, self.sock)
        return self.descriptor_hook() if self.descriptor_hook else None

    def journal(self, event):
        self.events.append(copy.deepcopy(event))
        return self.journal_hook(event) if self.journal_hook else None

    def clock_to(self, sim_ns):
        while self.step * 1_000_000 < sim_ns:
            self.step += 1
            self.lane.post_update(SimpleNamespace(iterations=self.step, paused=False,
                                                  dt=timedelta(milliseconds=1),
                                                  sim_time=timedelta(milliseconds=self.step)))

    def ready(self):
        self.obj.poll_listener()
        self.assertEqual(self.obj.poll_listener()['phase'], 'first_ready')

    def enqueue(self, index=0):
        request = body(index)[0]
        encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
        encoder.seq = index % 256
        self.sock.input.append(mav.MAVLink_timesync_message(0, request).pack(encoder))

    def receive(self, index=0):
        self.clock_to(body(index)[0])
        self.enqueue(index)
        return self.obj.poll_datagram()

    def assert_failed(self):
        self.assertTrue(self.obj.progress['failure'])
        self.assertFalse(self.obj.progress['observed_bootstrap_complete'])
        count = len(self.sock.sent)
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertEqual(len(self.sock.sent), count)
        self.assertFalse(self.sock.closed)

    def test_normal500_real_codec_all_actual_classes(self):
        self.ready()
        self.receive()
        self.obj.poll_listener()
        self.obj.poll_listener()
        self.obj.poll_listener()
        for index in range(1, 500):
            self.backend.now += 1_000_000
            self.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll_listener()
        self.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll_listener()
        result = self.obj.poll_listener()
        self.assertTrue(result['observed_bootstrap_complete'])
        self.assertEqual(result['completed_reply_attempts'], 500)
        self.assertEqual(len(self.sock.sent), 500)
        for index, (raw, flags, peer) in enumerate(self.sock.sent):
            msg = mav.MAVLink(None).decode(bytearray(raw))
            self.assertEqual((msg.tc1, msg.ts1), (body(index)[1], body(index)[0]))
            self.assertEqual((flags, peer), (socket.MSG_DONTWAIT, ('127.0.0.1', 14588)))
        self.assertTrue(all(args == (4096, 0, socket.MSG_DONTWAIT) for args in self.sock.reads))
        selections = self.obj.evidence['selections']
        self.assertEqual(len(selections), 500)
        self.assertEqual(selections[0]['observation']['sim_ns'], 100_000_000)
        self.assertFalse(any(result[k] for k in ('network_authorized', 'delivery_proven', 'fusion_qualified')))
        self.obj.close()
        self.obj.close()
        self.assertFalse(self.sock.closed)

    def test_no_packet_does_not_send_or_select(self):
        self.ready()
        self.assertIsNone(self.obj.poll_datagram())
        self.assertEqual(self.obj.evidence['selections'], [])
        self.assertEqual(self.sock.sent, [])

    def test_profile_check_expiry_refuses_before_send(self):
        self.ready()
        def install_slow_profile():
            def local():
                self.backend.now = 2_000_000_010
                return self.sock.local
            self.sock.getsockname = local
        self.at_send_attempt(install_slow_profile)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_profile_check_expiry_refuses_final_completion(self):
        self.ready()
        self.receive()
        for _ in range(3):
            self.obj.poll_listener()
        for index in range(1, 500):
            self.backend.now += 1_000_000
            self.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll_listener()
        self.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll_listener()
        def local():
            if self.obj._core.progress['wire_bootstrap_complete']:
                self.backend.now += 2_000_000_000
            return self.sock.local
        self.sock.getsockname = local
        with self.assertRaises(ValueError):
            self.obj.poll_listener()
        self.assertEqual(len(self.sock.sent), 500)
        self.assert_failed()

    def test_shared_remote_fault_refuses_before_send(self):
        self.ready()
        def invalidate():
            self.remote.map_odometry_sample(100_000_000)
            with self.assertRaises(ValueError):
                self.remote.map_odometry_sample(100_000_000)
        self.at_send_attempt(invalidate)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_wrong_phase_refused_before_read(self):
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertEqual(self.sock.reads, [])
        self.assert_failed()

    def test_packet_before_first_clock_refuses(self):
        self.ready()
        self.enqueue()
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def at_send_attempt(self, action):
        def hook(event):
            if (event['source'] == 'core' and event['event'].get('source') == 'wire'
                    and event['event']['event']['kind'] == 'send_attempt'):
                action()
        self.journal_hook = hook

    def test_source_fails_between_selection_and_send(self):
        self.ready()
        self.at_send_attempt(lambda: setattr(self, 'source_hook', lambda: False))
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_selected_stale_even_when_source_keeps_up(self):
        self.ready()
        def age():
            self.backend.now = 1_500_000_010
            self.clock_to(101_000_000)
            self.backend.now = 2_000_000_010
        self.at_send_attempt(age)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_descriptor_changed_after_selection_refused(self):
        self.ready()
        self.at_send_attempt(lambda: setattr(self.sock, 'local', ('127.0.0.1', 123)))
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_owner_changed_after_selection_refused(self):
        self.ready()
        self.at_send_attempt(lambda: self.backend.owner.update(start_ticks=8))
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_clock_origin_changed_after_selection_refused(self):
        self.ready()
        self.at_send_attempt(lambda: setattr(self.remote, 'remote_origin_ns', 2_000_000))
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_selection_journal_failure_stops_before_send(self):
        self.ready()
        def fail(event):
            if event['source'] == 'selection':
                raise OSError('journal full')
        self.journal_hook = fail
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assertEqual(len(self.obj.evidence['selections']), 1)
        self.assert_failed()

    def test_short_write_retained_without_retry(self):
        self.ready()
        self.sock.hook = lambda _: 1
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(len(self.sock.sent), 1)
        returns = [e for e in self.obj.evidence['core']['wire']['events'] if e['kind'] == 'send_return']
        self.assertEqual(returns[0]['count'], 1)
        self.assert_failed()

    def test_failure_during_send_preserves_actual_count(self):
        self.ready()
        def send(raw):
            self.source_hook = lambda: False
            return len(raw)
        self.sock.hook = send
        with self.assertRaises(ValueError):
            self.receive()
        returns = [e for e in self.obj.evidence['core']['wire']['events'] if e['kind'] == 'send_return']
        self.assertEqual(returns[0]['count'], len(self.sock.sent[0][0]))
        self.assert_failed()

    def test_send_eagain_does_not_retry(self):
        self.ready()
        def send(_):
            raise BlockingIOError()
        self.sock.hook = send
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(len(self.sock.sent), 1)
        self.assert_failed()

    def test_reentry_refusal_prevents_outer_send(self):
        self.ready()
        def reenter():
            with self.assertRaises(ValueError):
                self.obj.poll_datagram()
        self.at_send_attempt(reenter)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_close_in_callback_prevents_send(self):
        self.ready()
        self.at_send_attempt(self.obj.close)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_global8s_not_extended(self):
        self.backend.now += 8_000_000_000
        with self.assertRaises(ValueError):
            self.obj.poll_listener()
        self.assert_failed()

    def test_preexisting_source_failure_closes_active_owned_listener(self):
        # First snapshot command is still active after this first poll.
        self.obj.poll_listener()
        connection = self.backend.used[0]
        self.assertEqual(connection.closed, 0)
        with self.assertRaises(ValueError):
            self.lane.post_update(SimpleNamespace(iterations=1, sim_time=timedelta(milliseconds=1),
                                                  dt=timedelta(milliseconds=1), paused=True))
        with self.assertRaises(ValueError):
            self.obj.poll_listener()
        self.assertEqual(connection.closed, 1)
        self.assert_failed()

    def test_explicit_remote_session_replacement_refuses(self):
        self.ready()
        self.remote.replace_session('replacement', sim_origin_ns=0, remote_origin_ns=1_000_000)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.sent, [])
        self.assert_failed()

    def test_descriptor_guard_failure_refuses_before_read(self):
        self.ready()
        self.descriptor_hook = lambda: False
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sock.reads, [])
        self.assert_failed()

    def test_completed_count_not_committed_after_post_send_failure(self):
        self.ready()
        self.sock.hook = lambda raw: (setattr(self.backend, 'now', 8_000_000_010), len(raw))[1]
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.obj.progress['completed_reply_attempts'], 0)
        returns = [e for e in self.obj.evidence['core']['wire']['events'] if e['kind'] == 'send_return']
        self.assertEqual(returns[0]['count'], len(self.sock.sent[0][0]))
        self.assert_failed()


if __name__ == '__main__':
    unittest.main()
