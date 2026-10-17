"""Real producer failure journals, synthetic sockets only; no live qualification."""

import copy
import tempfile
import unittest
from pathlib import Path

from tests.benchmark import test_openvins_observed_restoration as restoration_fixture
from tests.benchmark.test_openvins_wire_bootstrap import mav
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tools.benchmark.audit_live_wire_study import (
    audit_wire_interval_records,
    read_segmented_wire_records,
)
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


class FailureAuditTests(unittest.TestCase):
    def test_failed_producer_capture_cannot_be_promoted_by_terminal_success(self):
        # If the normal auditor trusts final_us/terminal success instead of the
        # complete transaction, the restored and missing-ACK cases would pass.
        for fault, verified, final_us in (
            ("source_loss_restored", True, 100000),
            ("missing_restore_ack", False, 100000),
            ("short_restore_send", False, 100000),
            ("armed", False, None),
            ("cleanup_deadline", False, None),
            ("unknown_baseline", False, None),
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                store = SegmentedWireJournal(Path(directory) / "wire")
                case = restoration_fixture.RestorationTests("runTest")
                case.setUp(retention=store, configure=fault != "unknown_baseline")
                try:
                    case.fail_source()
                    case.obj.begin_restoration("offline failure audit fixture")
                    if fault == "source_loss_restored":
                        case.restore()
                    elif fault in ("missing_restore_ack", "short_restore_send"):
                        if fault == "short_restore_send":
                            case.f.sock.hook = lambda raw: len(raw) - 1
                        case.receive()
                        case.f.sock.hook = None
                        if fault == "missing_restore_ack":
                            case.f.backend.now += 2_000_000_000
                            case.receive()
                        case.obj.poll_restoration()
                        case.receive(case.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
                        case.obj.poll_restoration()
                        case.receive(case.case.ack(510), mav.MAVLink_message_interval_message(111, 100000))
                    elif fault == "armed":
                        case.f.sock.input.append(heartbeat(base=128))
                        with self.assertRaises(ValueError):
                            case.obj.poll_restoration()
                    elif fault == "cleanup_deadline":
                        case.f.backend.now = case.obj.evidence["restoration"]["deadline_ns"]
                        with self.assertRaises(ValueError):
                            case.obj.poll_restoration()
                    progress = case.obj.progress
                    interval = case.obj.evidence["core"]["wire"]["interval"]
                    self.assertTrue(progress["failure"])
                    self.assertEqual(progress["restoration_verified"], verified)
                    self.assertEqual(interval["final_us"], final_us)
                    self.assertFalse(progress["fusion_qualified"])
                finally:
                    case.obj.close()
                records = read_segmented_wire_records(Path(directory) / "wire", store.close())["records"]
                context = dict(start_ns=10, total_deadline_ns=300_000_000_010)
                with self.assertRaises(ValueError):
                    audit_wire_interval_records(records, context)

                altered = copy.deepcopy(records)
                terminal = next(
                    row["event"]["state"] for row in reversed(altered)
                    if row["source"] == "wire" and row["event"]["kind"] == "interval_state"
                )
                terminal.update(
                    phase="done", pending=None, primary_failure=None,
                    terminal_failure=None, terminal_pending=None,
                    restore_failures=[], cleanup_deadline_ns=None,
                    baseline_us=100000, final_us=100000,
                    modeled_transaction_pass=True,
                )
                with self.assertRaises(ValueError):
                    audit_wire_interval_records(altered, context)
