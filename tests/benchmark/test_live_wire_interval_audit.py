"""Raw command/ACK/readback audit against an explicitly synthetic producer run."""

import copy
import tempfile
import unittest
from pathlib import Path

from tests.benchmark import test_live_wire_protocol_audit as fixtures
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.openvins_timesync_wire import PinnedCodec


class IntervalAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.evidence = fixtures.ProtocolAuditTests.build_records(Path(cls.directory.name) / "segments")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_audit(self, evidence):
        self.assertTrue(hasattr(audit, "audit_wire_interval_records"), "raw interval auditor missing")
        return audit.audit_wire_interval_records(evidence["records"], evidence["context"])

    def test_raw_apply_restore_sequence_and_readbacks(self):
        result = self.run_audit(self.evidence)
        self.assertTrue(result["interval_consistent"])
        self.assertEqual(result["baseline_us"], 100000)
        self.assertEqual(result["candidate_us"], 10000)
        self.assertEqual(result["command_count"], 6)
        self.assertEqual(result["ack_count"], 6)
        self.assertEqual(result["readback_count"], 4)
        self.assertFalse(result["live_qualified"])
        self.assertFalse(result["fusion_qualified"])

    def test_already_candidate_baseline_requires_no_set_and_final_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            e = fixtures.ProtocolAuditTests.build_records(Path(directory) / "segments", baseline_us=10000)
        result = self.run_audit(e)
        self.assertEqual(result["command_count"], 2)
        self.assertEqual(result["ack_count"], 2)
        self.assertEqual(result["readback_count"], 2)
        self.assertEqual(result["baseline_us"], 10000)
        self.assertTrue(result["interval_consistent"])
        self.assertFalse(result["live_qualified"])

    def test_missing_raw_evidence_cannot_be_replaced_by_successful_summaries(self):
        for fault in (
            "missing_restore_ack",
            "missing_final_readback",
            "short_command_send",
            "wrong_command_bytes",
            "wrong_command_sequence",
            "restore_before_body",
            "missing_state",
            "deadline_extension",
            "wrong_pending_command",
            "terminal_failure",
            "wrong_baseline",
            "missing_terminal_state",
        ):
            with self.subTest(fault=fault):
                e = copy.deepcopy(self.evidence)
                rows = e["records"]
                commands = [r for r in rows if r["source"] == "wire" and r["event"]["kind"] == "interval_send_attempt"]
                states = [r for r in rows if r["source"] == "wire" and r["event"]["kind"] == "interval_state"]
                if fault in ("missing_restore_ack", "missing_final_readback"):
                    start = commands[3 if fault == "missing_restore_ack" else 5]["index"]
                    receive = next(
                        r for r in rows if r["source"] == "wire" and r["event"]["kind"] == "receive" and r["index"] > start
                    )
                    event = receive["event"]
                    codec = PinnedCodec()
                    removed = "COMMAND_ACK" if fault == "missing_restore_ack" else "MESSAGE_INTERVAL"
                    messages = [m for m in codec.decode_datagram(bytes.fromhex(event["raw_hex"])) if m["type"] != removed]
                    raw = b"".join(bytes.fromhex(m["raw_hex"]) for m in messages)
                    event["raw_hex"] = raw.hex()
                    decoded = next(
                        r
                        for r in rows
                        if r["source"] == "wire" and r["event"]["kind"] == "decoded" and r["index"] > receive["index"]
                    )
                    decoded["event"]["messages"] = messages
                    receiver = next(
                        r
                        for r in reversed(rows[: receive["index"]])
                        if r["source"] == "receiver" and r["event"]["kind"] == "receive_return"
                    )
                    receiver["event"].update(data_hex=raw.hex(), data_length=len(raw))
                elif fault == "short_command_send":
                    next(r["event"] for r in rows if r["source"] == "wire" and r["event"]["kind"] == "interval_send_return")[
                        "count"
                    ] -= 1
                elif fault == "wrong_command_bytes":
                    commands[3]["event"]["raw_hex"] = commands[1]["event"]["raw_hex"]
                elif fault == "wrong_command_sequence":
                    commands[3]["event"]["sequence"] += 1
                elif fault == "restore_before_body":
                    commands[3]["index"] = commands[2]["index"] + 1
                elif fault == "missing_state":
                    rows.remove(next(r for r in states if r["event"]["state"]["pending"] is not None))
                elif fault == "deadline_extension":
                    next(r["event"]["state"]["pending"] for r in states if r["event"]["state"]["pending"])["deadline_ns"] += 1
                elif fault == "wrong_pending_command":
                    next(r["event"]["state"]["pending"] for r in states if r["event"]["state"]["pending"])["command"] = 511
                elif fault == "terminal_failure":
                    states[-1]["event"]["state"]["terminal_failure"] = "lost restore"
                elif fault == "wrong_baseline":
                    states[-1]["event"]["state"]["baseline_us"] = 10000
                elif fault == "missing_terminal_state":
                    rows.remove(states[-1])
                with self.assertRaises(ValueError):
                    self.run_audit(e)
