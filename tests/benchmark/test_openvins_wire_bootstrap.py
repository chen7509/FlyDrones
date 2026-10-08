"""Pinned-codec composition with simulated socket reads, no running PX4."""

import copy
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

try:
    from pymavlink.dialects.v20 import common as mav
except ImportError as exc:
    raise unittest.SkipTest("pymavlink unavailable; execute this suite in WSL") from exc

from tests.benchmark.check_openvins_owned_bootstrap import body, frame
from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock

OWNER = dict(pid=321, pgrp=321, session=321, start_ticks=7, uid=1000, gid=1000,
             exe="/bin/fixture", exe_device=1, exe_inode=2, cwd="/tmp/run",
             cwd_device=1, cwd_inode=3, net="net:[4]", user="user:[5]")


class Connection:
    def __init__(self, reads):
        self.reads, self.sent, self.closed = deque(reads), b"", 0

    def setblocking(self, value):
        assert value is False

    def send(self, data):
        self.sent += data
        return len(data)

    def recv(self, limit):
        assert limit == 4096
        if not self.reads:
            raise BlockingIOError()
        return self.reads.popleft()


class Backend:
    def __init__(self):
        self.now, self.owner, self.used = 10, copy.deepcopy(OWNER), []
        self.connections = [Connection([b"never published\n\0\0", b""]),
                            Connection([b"\nTOPIC: timesync_status\n" + body(0)[2] + b"\0\0", b""]),
                            Connection([frame(0)])]

    def clock(self):
        return self.now

    def observe(self, process):
        return copy.deepcopy(self.owner)

    def peer(self, connection):
        return {key: self.owner[key] for key in ("pid", "uid", "gid")}

    def connect(self, path, timeout):
        assert path == "/tmp/private/socket"
        connection = self.connections[len(self.used)]
        self.used.append(connection)
        return connection

    def close(self, connection):
        connection.closed += 1


class CompositionTests(unittest.TestCase):
    def setUp(self):
        from tools.benchmark.openvins_wire_bootstrap import OwnedWireBootstrap
        self.backend, self.events, self.sent = Backend(), [], []
        self.journal_hook = self.sink_hook = None
        self.remote = RemoteMonotonicClock("composed", sim_origin_ns=0, remote_origin_ns=1_000_000)
        self.obj = OwnedWireBootstrap(SimpleNamespace(pid=321), OWNER, "/tmp/private/socket", self.remote, 10,
                                      self.journal, self.sink, backend=self.backend)

    def journal(self, event):
        self.events.append(copy.deepcopy(event))
        if self.journal_hook:
            return self.journal_hook(event)
        return None

    def sink(self, raw, peer):
        self.sent.append((raw, peer))
        return self.sink_hook(raw, peer) if self.sink_hook else len(raw)

    def receive(self, index=0, raw=None):
        request = body(index)[0]
        if raw is None:
            encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
            encoder.seq = index % 256
            raw = mav.MAVLink_timesync_message(0, request).pack(encoder)
        return self.obj.receive(raw, ("127.0.0.1", 14588), self.backend.now, request)

    def first_ready(self):
        self.obj.poll()
        self.assertEqual(self.obj.poll()["phase"], "first_ready")

    def stream_ready(self):
        self.first_ready()
        self.receive()
        self.obj.poll()
        self.assertEqual(self.obj.poll()["phase"], "first_confirmed")
        self.assertEqual(self.obj.poll()["phase"], "stream_ready")

    def assert_failed(self):
        result = self.obj.progress
        self.assertTrue(result["failure"])
        self.assertFalse(result["wire_bootstrap_complete"])
        self.assertFalse(result["modeled_bootstrap_ready"])
        count = len(self.sent)
        with self.assertRaises(ValueError):
            self.receive(2)
        self.assertEqual(count, len(self.sent))

    def test_real_codec_and_actual_reserve_composed500(self):
        self.stream_ready()
        for index in range(1, 500):
            self.backend.now += 1000000
            self.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll()
        self.assertFalse(self.obj.progress["wire_bootstrap_complete"])
        self.backend.connections[2].reads.extend([b"\0\0", b""])
        self.obj.poll()
        result = self.obj.poll()
        self.assertTrue(result["wire_bootstrap_complete"])
        self.assertEqual(result["completed_reply_attempts"], 500)
        self.assertEqual(result["modeled_accepted_samples"], 500)
        self.assertEqual(len(self.sent), 500)
        self.assertEqual(mav.MAVLink(None).decode(bytearray(self.sent[256][0])).get_seq(), 0)
        self.assertFalse(any(result[k] for k in ("network_authorized", "live_convergence_qualified", "fusion_qualified")))
        self.assertEqual([c.closed for c in self.backend.used], [1, 1, 1])
        self.obj.close()
        self.obj.close()
        self.assertTrue(self.obj.progress["wire_bootstrap_complete"])
        with self.assertRaises(ValueError):
            self.receive(500)

    def test_reply_before_empty_snapshot_refuses_without_send(self):
        with self.assertRaisesRegex(ValueError, "phase"):
            self.receive()
        self.assertEqual(self.sent, [])
        self.assert_failed()

    def test_second_reply_without_status_refuses(self):
        self.first_ready()
        self.receive()
        with self.assertRaises(ValueError):
            self.receive(1)
        self.assertEqual(len(self.sent), 1)
        self.assert_failed()

    def test_wire_crc_failure_closes_current_listener(self):
        self.stream_ready()
        with self.assertRaises(ValueError):
            self.receive(1, b"invalid")
        self.assertEqual(self.backend.connections[2].closed, 1)
        self.assert_failed()

    def test_status_failure_suppresses_both_sides(self):
        self.stream_ready()
        self.receive(1)
        self.backend.connections[2].reads.append(frame(2))
        with self.assertRaises(ValueError):
            self.obj.poll()
        self.assert_failed()

    def test_short_sink_preserves_return_and_closes_listener(self):
        self.stream_ready()
        self.sink_hook = lambda *_: 3
        with self.assertRaisesRegex(ValueError, "send count"):
            self.receive(1)
        self.assertTrue(any(e["kind"] == "send_return" and e["count"] == 3 for e in self.obj.evidence["wire"]["events"]))
        self.assertEqual(self.backend.connections[2].closed, 1)
        self.assertEqual(self.obj.progress["completed_reply_attempts"], 1)
        self.assert_failed()

    def test_owner_change_during_wire_journal_prevents_sink(self):
        self.first_ready()
        def hook(event):
            if event["source"] == "wire" and event["event"]["kind"] == "send_attempt":
                self.backend.owner["start_ticks"] += 1
        self.journal_hook = hook
        with self.assertRaisesRegex(ValueError, "owner"):
            self.receive()
        self.assertEqual(self.sent, [])
        self.assert_failed()

    def test_owner_change_after_sink_keeps_bytes_but_not_qualification(self):
        self.first_ready()
        def sink(raw, peer):
            self.backend.owner["start_ticks"] += 1
            return len(raw)
        self.sink_hook = sink
        with self.assertRaisesRegex(ValueError, "owner"):
            self.receive()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.obj.progress["completed_reply_attempts"], 0)
        self.assertTrue(any(e["kind"] == "send_return" for e in self.obj.evidence["wire"]["events"]))
        self.assert_failed()

    def test_reentrant_journal_cannot_resume_sink(self):
        self.first_ready()
        def hook(event):
            if event["source"] == "wire" and event["event"]["kind"] == "reserved":
                try:
                    self.obj.poll()
                except ValueError:
                    pass
        self.journal_hook = hook
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.sent, [])
        self.assert_failed()

    def test_journal_failure_after_send_retains_effect(self):
        self.first_ready()
        def hook(event):
            if event["source"] == "wire" and event["event"]["kind"] == "send_return":
                raise OSError("journal after write")
        self.journal_hook = hook
        with self.assertRaisesRegex(ValueError, "journal after write"):
            self.receive()
        self.assertEqual(len(self.sent), 1)
        self.assert_failed()

    def test_session_change_detected_on_idle_poll(self):
        self.stream_ready()
        self.remote.replace_session("replacement", sim_origin_ns=0, remote_origin_ns=0)
        with self.assertRaisesRegex(ValueError, "session"):
            self.obj.poll()
        self.assertEqual(self.backend.connections[2].closed, 1)
        self.assert_failed()

    def test_idle_pending_deadline(self):
        self.stream_ready()
        self.receive(1)
        self.backend.now += 2000000000
        with self.assertRaisesRegex(ValueError, "timeout|deadline"):
            self.obj.poll()
        self.assert_failed()

    def test_global_deadline_not_reset_by_wire(self):
        self.first_ready()
        self.backend.now = 8000000010
        with self.assertRaisesRegex(ValueError, "deadline|readiness"):
            self.receive()
        self.assertEqual(self.sent, [])

    def test_early_close_and_repeat_close_do_not_reopen(self):
        self.obj.poll()
        self.obj.close()
        self.obj.close()
        self.assertEqual(len(self.backend.used), 1)
        self.assertEqual(self.backend.connections[0].closed, 1)
        self.assert_failed()

    def prepare_last_reply(self):
        self.stream_ready()
        for index in range(1, 499):
            self.backend.now += 1000000
            self.receive(index)
            self.backend.connections[2].reads.append(frame(index))
            self.obj.poll()

    def release_hook(self, callback):
        class HookedLock:
            def __init__(self):
                self.lock = Lock()
                self.callback = callback

            def acquire(self, blocking=False):
                return self.lock.acquire(blocking=blocking)

            def release(self):
                self.lock.release()
                once, self.callback = self.callback, None
                if once is not None:
                    once()
        self.obj._lock = HookedLock()

    def test_final_reply_count_commits_before_another_poll_can_enter(self):
        self.prepare_last_reply()
        self.backend.connections[2].reads.extend([frame(499) + b"\0\0", b""])
        errors = []
        def other_thread_step():
            try:
                self.obj.poll()
                self.obj.poll()
            except ValueError as exc:
                errors.append(str(exc))
        self.release_hook(other_thread_step)
        self.receive(499)
        self.assertEqual(errors, [])
        self.assertTrue(self.obj.progress["wire_bootstrap_complete"])

    def test_final_completion_commits_before_new_receive_can_enter(self):
        self.prepare_last_reply()
        self.receive(499)
        self.backend.connections[2].reads.extend([frame(499) + b"\0\0", b""])
        self.obj.poll()
        refusals = []
        def late_request():
            try:
                self.receive(500)
            except ValueError as exc:
                refusals.append(str(exc))
        self.release_hook(late_request)
        self.obj.poll()
        self.assertEqual(len(refusals), 1)
        self.assertTrue(self.obj.progress["wire_bootstrap_complete"])
        self.assertIsNone(self.obj.progress["failure"])

    def test_terminal_owner_and_frame_deadline_remain_checked(self):
        self.prepare_last_reply()
        self.receive(499)
        self.backend.connections[2].reads.extend([frame(499) + b"\0\0", b""])
        self.obj.poll()
        old_clock = self.backend.clock
        def clock():
            if self.obj._owned.progress["transport_bootstrap_complete"]:
                self.backend.now = self.obj._owned._stream_frame_ns + 2000000000
            return old_clock()
        self.backend.clock = clock
        with self.assertRaisesRegex(ValueError, "complete-frame timeout"):
            self.obj.poll()
        self.assert_failed()

    def test_close_during_final_health_prevents_reply_commit(self):
        self.first_ready()
        old_healthy = self.obj._healthy
        calls = []
        def healthy():
            old_healthy()
            calls.append(True)
            if len(calls) == 2:
                self.obj.close()
        self.obj._healthy = healthy
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.obj.progress["completed_reply_attempts"], 0)
        self.assertEqual(len(self.sent), 1)
        self.assert_failed()


class HarnessEvidenceTests(unittest.TestCase):
    def test_post_cleanup_journal_and_copy_failure_mark_case(self):
        from tests.benchmark import check_openvins_wire_bootstrap as harness
        for mode in ("journal", "copy", "copy-hash"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                run, destination = Path(root) / "run", Path(root) / "copy"
                run.mkdir()
                (run / "journal.jsonl").write_text("")
                result = dict(harness_error=None, evidence={"wire": {"events": []}, "owned": {"events": []}})
                original_copy = harness.shutil.copytree
                def copy(source, dest, mode=mode, original_copy=original_copy):
                    if mode == "copy":
                        raise OSError("copy refused")
                    original_copy(source, dest)
                    if mode == "copy-hash":
                        (dest / "journal.jsonl").write_text("changed")
                if mode == "journal":
                    result["evidence"]["wire"]["events"].append({"missing": True})
                with patch.object(harness.shutil, "copytree", copy), self.assertRaises((AssertionError, OSError)):
                    harness.audit_copy(run, destination, result)
                self.assertIsNotNone(result["harness_error"])

    def test_post_hash_drift_cannot_report_complete(self):
        from tests.benchmark import check_openvins_wire_bootstrap as harness
        original_read = Path.read_bytes
        original_save = harness.save
        after_pre = []
        def read(path):
            data = original_read(path)
            return data + b"drift" if after_pre and path == Path(harness.__file__) else data
        def save(path, value):
            original_save(path, value)
            if path.name == "prospective.json":
                after_pre.append(True)
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            with patch.object(harness, "CASES", []), patch.object(harness, "save", save), patch.object(Path, "read_bytes", read):
                with self.assertRaises(AssertionError):
                    harness.main(SimpleNamespace(output=output, producer="unit-no-process"))
            summary = json.loads((output / "summary.json").read_text())
            self.assertFalse(summary["source_stable"])
            self.assertFalse(summary["complete"])


if __name__ == "__main__":
    unittest.main()
