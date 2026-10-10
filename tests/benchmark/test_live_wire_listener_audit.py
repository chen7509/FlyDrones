"""Recorded producer chain with fake I/O; no socket or PX4 activation."""

import copy
import tempfile
import unittest
from pathlib import Path

from tests.benchmark import test_live_wire_protocol_audit as fixtures
from tools.benchmark import audit_live_wire_study as audit


class ListenerAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.evidence = fixtures.ProtocolAuditTests.build_records(Path(cls.directory.name) / "segments")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_audit(self, evidence):
        self.assertTrue(hasattr(audit, "audit_owned_listener_records"), "owned listener audit missing")
        return audit.audit_owned_listener_records(
            records=evidence["records"], context=evidence["context"], daemon_path="/tmp/private/socket"
        )

    def test_raw_owned_connections_commands_and_stdout_join(self):
        result = self.run_audit(self.evidence)
        self.assertTrue(result["listener_records_consistent"])
        self.assertEqual(result["connections"], 4)
        self.assertEqual(result["completed_commands"], 3)
        self.assertEqual(result["bootstrap_records"], 500)
        self.assertEqual(result["maintenance_records"], 3)
        self.assertFalse(result["owner_launch_qualified"])
        self.assertFalse(result["daemon_exit_proven"])
        self.assertFalse(result["live_qualified"])
        self.assertFalse(result["fusion_qualified"])

    def test_independent_owner_transport_and_parsing_corruptions(self):
        for fault in (
            "peer_pid",
            "owner_start",
            "socket_path",
            "missing_mirror",
            "mirror_command",
            "command_bytes",
            "short_send",
            "raw_status",
            "missing_eof",
            "exit_trailer",
            "parsed_terminal",
            "late_return",
            "cancel_failed",
            "cancel_partial",
            "missing_cold_mirror",
            "boolean_command_index",
        ):
            with self.subTest(fault=fault):
                evidence = copy.deepcopy(self.evidence)
                rows = evidence["records"]

                def find(source, kind, rows=rows):
                    return next(r for r in rows if r["source"] == source and r["event"].get("kind") == kind)

                if fault == "missing_mirror":
                    rows.remove(next(r for r in rows if r["source"] == "owned" and r["event"]["source"] == "transport"))
                elif fault == "mirror_command":
                    next(r for r in rows if r["source"] == "owned" and r["event"]["source"] == "transport")["event"][
                        "command_index"
                    ] = 1
                elif fault == "missing_cold_mirror":
                    rows.remove(next(r for r in rows if r["source"] == "owned" and r["event"]["source"] == "bootstrap"))
                elif fault == "boolean_command_index":
                    for row in rows:
                        if (
                            row["source"] == "owned"
                            and row["event"]["source"] == "transport"
                            and row["event"]["command_index"] == 1
                        ):
                            row["event"]["command_index"] = True
                else:
                    source = "listener-3" if fault.startswith("cancel") else "listener-2"
                    kind = {
                        "peer_pid": "connection",
                        "owner_start": "connection",
                        "socket_path": "connection",
                        "command_bytes": "send_attempt",
                        "short_send": "send_return",
                        "raw_status": "recv_return",
                        "exit_trailer": "recv_return",
                        "missing_eof": "recv_return",
                        "parsed_terminal": "parsed_eof",
                        "late_return": "recv_return",
                        "cancel_failed": "cancellation_result",
                        "cancel_partial": "cancellation_result",
                    }[fault]
                    row = find(source, kind)
                    if fault == "peer_pid":
                        row = next(
                            r
                            for r in rows
                            if r["source"] == source
                            and r["event"].get("kind") == kind
                            and r["event"]["observation"]["kind"] == "peer_observed"
                        )
                    if fault in ("missing_eof", "exit_trailer"):
                        row = next(
                            r
                            for r in rows
                            if r["source"] == source
                            and r["event"].get("kind") == kind
                            and (r["event"]["eof"] if fault == "missing_eof" else r["event"]["raw_hex"] == "0000")
                        )
                    old = copy.deepcopy(row["event"])
                    event = row["event"]
                    if fault == "peer_pid":
                        event["observation"]["peer"]["pid"] += 1
                    elif fault == "owner_start":
                        event["observation"]["owner"]["start_ticks"] += 1
                    elif fault == "socket_path":
                        event["observation"]["path"] = "/tmp/other/socket"
                    elif fault == "command_bytes":
                        event["raw_hex"] = b"commander arm\0".hex()
                    elif fault == "short_send":
                        event["count"] -= 1
                    elif fault == "raw_status":
                        event["raw_hex"] = event["raw_hex"].replace(b"estimated_offset: 0".hex(), b"estimated_offset: 1".hex())
                    elif fault == "exit_trailer":
                        event["raw_hex"] = "0001"
                    elif fault == "parsed_terminal":
                        event["terminal"]["records"] = 499
                    elif fault == "late_return":
                        event["returned_clock_ns"] += 2_000_000_000
                    elif fault == "cancel_failed":
                        event["socket_close_returned"] = False
                    elif fault == "cancel_partial":
                        event["incomplete_frame_bytes"] = 1
                    # Change both copies: these cases must fail on raw semantics,
                    # not just on the redundant journal mirror equality.
                    mirror = next(
                        r
                        for r in rows
                        if r["source"] == "owned"
                        and r["event"]["source"] == "transport"
                        and r["event"]["command_index"] == int(source[-1])
                        and r["event"]["event"] == old
                    )
                    if fault == "missing_eof":
                        rows.remove(row)
                        rows.remove(mirror)
                    else:
                        mirror["event"]["event"] = copy.deepcopy(event)
                counts = {}
                for index, row in enumerate(rows):
                    row["index"] = index
                    row["source_index"] = counts.get(row["source"], 0)
                    counts[row["source"]] = row["source_index"] + 1
                with self.assertRaises(ValueError):
                    self.run_audit(evidence)
