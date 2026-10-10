"""Installed codec/composition with actual local segments and injected I/O."""
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.benchmark import test_openvins_observed_wire_session as fixtures
from tests.benchmark.test_openvins_wire_bootstrap import Connection, body, frame
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


class SegmentedCompositionTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('retention', inspect.signature(ObservedWireSession).parameters,
                      'observed segmented retention binding missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SegmentedWireJournal(Path(self.temp.name) / 'wire')
        self.f = fixtures.ObservedSessionTests()
        self.f.setUp()
        self.f.obj.close()
        self.delivered = []
        self.f.obj = ObservedWireSession(
            SimpleNamespace(pid=321), fixtures.OWNER, '/tmp/private/socket', self.f.remote,
            self.f.lane, self.f.sock, 10, lambda _: None, self.f.descriptor_guard,
            backend=self.f.backend, heartbeat_sink=self.delivered.append, retention=self.store)
        self.obj = self.f.obj

    def complete(self):
        self.f.ready()
        self.f.receive()
        for _ in range(3):
            self.obj.poll_listener()
        for index in range(1, 500):
            self.f.backend.now += 1_000_000
            self.f.receive(index)
            self.f.backend.connections[2].reads.append(frame(index))
            self.obj.poll_listener()
        self.f.backend.connections[2].reads.extend([b'\0\0', b''])
        self.obj.poll_listener()
        self.assertTrue(self.obj.poll_listener()['observed_bootstrap_complete'])
        self.obj.begin_maintenance(300_000_000_010)
        self.f.backend.connections.append(Connection([status(499, 1)]))
        self.obj.poll_listener()

    def rows(self):
        metadata = self.store.evidence
        index = 0
        source_counts = {}
        for member in metadata['segments']:
            path = Path(metadata['directory']) / member['name']
            with path.open('rb') as stream:
                self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(), member['sha256'])
            self.assertEqual(path.stat().st_size, member['bytes'])
            with path.open('r', encoding='ascii') as stream:
                for line in stream:
                    row = json.loads(line)
                    self.assertEqual(row['index'], index)
                    self.assertEqual(row['source_index'], source_counts.get(row['source'], 0))
                    source_counts[row['source']] = source_counts.get(row['source'], 0) + 1
                    index += 1
                    yield row
        self.assertEqual(index, metadata['records'])
        self.assertEqual(source_counts, {k: v for k, v in metadata['channels'].items() if v})

    def test_wire_crosses8192_without_dropping_any_layer_or_resetting_sequence(self):
        self.complete()
        for index in range(500, 1100):
            self.f.backend.now += 20_000_000
            self.f.receive(index)
            self.f.sock.input.append(heartbeat())
            self.obj.poll_datagram()
            self.f.backend.connections[3].reads.append(status(index, index - 498))
            self.obj.poll_listener()
        self.obj.close()
        evidence = self.obj.evidence
        self.assertIsNone(evidence['failure'])
        self.assertTrue(self.store.evidence['complete_retention'])
        self.assertGreater(evidence['core']['wire']['events']['records'], 8192)
        self.assertEqual(evidence['modeled_accepted_samples'], 1100)
        self.assertEqual(len(self.f.sock.sent), 1100)
        self.assertEqual(len(self.delivered), 600)
        self.assertEqual(len(self.f.sock.reads), 1700)
        self.assertFalse(self.f.sock.closed)
        self.assertEqual(self.f.backend.used[3].closed, 1)
        kinds, phases = {}, set()
        for row in self.rows():
            phases.add(row['phase'])
            if row['source'] == 'receiver' and row['event']['kind'] == 'receive_return':
                self.assertIsInstance(row['event']['received_ns'], int)
                self.assertTrue(row['event']['data_hex'])
            key = row['source'], row['event'].get('kind')
            kinds[key] = kinds.get(key, 0) + 1
        self.assertEqual(kinds['receiver', 'receive_return'], 1700)
        self.assertEqual(kinds['wire', 'send_return'], 1100)
        self.assertEqual(kinds['wire', 'heartbeat_dispatch_return'], 600)
        self.assertEqual(phases, {'bootstrap', 'maintenance', 'stopping'})

    def test4096_datagram_limit_remains_even_with_segmented_storage(self):
        self.complete()
        packet = heartbeat()
        for _ in range(3596):
            self.f.sock.input.append(packet)
            self.obj.poll_datagram()
        before = len(self.f.sock.reads)
        self.assertEqual(before, 4096)
        self.f.sock.input.append(packet)
        with self.assertRaisesRegex(ValueError, 'selection capacity'):
            self.obj.poll_datagram()
        self.assertEqual(len(self.f.sock.reads), before)
        self.assertTrue(self.obj.progress['failure'])
        self.assertEqual(self.f.backend.used[3].closed, 1)
        self.obj.close()
        self.assertTrue(self.store.evidence['closed'])
        self.assertEqual(sum(row['source'] == 'receiver' and row['event']['kind'] == 'receive_return'
                             for row in self.rows()), 4096)

    def test_shared_storage_failure_blocks_read_and_preserves_owned_cleanup(self):
        self.complete()
        before = len(self.f.sock.reads)
        self.store.MAX_BYTES = self.store.evidence['bytes'] + 1
        self.f.clock_to(body(500)[0])
        self.f.enqueue(500)
        with self.assertRaises(ValueError):
            self.obj.poll_datagram()
        self.obj.close()
        self.assertTrue(self.obj.progress['failure'])
        self.assertEqual(len(self.f.sock.reads), before)
        self.assertEqual(self.f.backend.used[3].closed, 1)
        self.assertTrue(self.store.evidence['closed'])
        self.assertFalse(self.store.evidence['complete_retention'])


if __name__ == '__main__':
    unittest.main()
