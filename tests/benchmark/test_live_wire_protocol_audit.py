"""Pinned codec + real producer objects with synthetic I/O, never live delivery."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.benchmark import test_openvins_observed_interval as fixture
from tests.benchmark.test_openvins_wire_bootstrap import OWNER, Connection, body
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


class ProtocolAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.evidence = cls.build_records(Path(cls.directory.name) / "segments")

    @staticmethod
    def build_records(directory, *, rejected_first_maintenance=False, baseline_us=100000):
        store = SegmentedWireJournal(directory)
        case = fixture.ObservedIntervalTests("runTest")
        case.setUp(retention=store)
        if baseline_us == 10000:
            case.query(10000)
        elif baseline_us == 100000:
            case.configured()
        else:
            raise ValueError("fixture baseline unsupported")
        case.complete_listener()
        if baseline_us == 10000:
            case.query(10000)
        else:
            case.restored()
        case.obj.begin_maintenance(300_000_000_010)
        case.f.backend.connections.append(Connection([status(499, 1)]))
        case.obj.poll_listener()
        for index in (500, 501):
            case.f.backend.now += 10_000_000
            case.f.receive(index)
            raw = status(index, index - 498)
            if index == 500 and rejected_first_maintenance:
                request_us = body(index)[0] // 1000
                raw = raw.replace(f"timestamp: {request_us + 2000}".encode(), f"timestamp: {request_us + 20000}".encode())
                raw = raw.replace(b"round_trip_time: 2000", b"round_trip_time: 20000")
                raw = raw.replace(b"observed_offset: 0", b"observed_offset: 9000")
            case.f.backend.connections[3].reads.append(raw)
            case.obj.poll_listener()
        case.f.clock_to(25_000_000_000)
        case.obj.close()
        terminal = store.close()
        rows = audit.read_segmented_wire_records(directory, terminal)["records"]
        clock = case.f.lane.evidence
        # The original lane callback is a no-op fixture. These are reconstructed
        # synthetic disk-shaped attempts, never claimed as actual retained clock I/O.
        attempts = [{k: v for k, v in row.items() if k not in ("accepted", "journal_return_ns")} for row in clock["attempts"]]
        return json.loads(
            json.dumps(
                dict(
                    records=rows,
                    clock=clock,
                    clock_attempts=attempts,
                    context=dict(
                        owner=OWNER, start_ns=10, total_deadline_ns=300_000_000_010, clock_signature=["observed", 0, 1_000_000]
                    ),
                )
            )
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def audit(self, evidence):
        self.assertTrue(hasattr(audit, "audit_wire_protocol_records"), "protocol join missing")
        return audit.audit_wire_protocol_records(**evidence)

    def test_complete_synthetic_protocol_includes_noncounting_boundaries(self):
        result = self.audit(self.evidence)
        self.assertTrue(result["protocol_consistent"])
        self.assertEqual(result["bootstrap_accepted"], 500)
        self.assertEqual(result["maintenance_accepted"], 2)
        self.assertEqual(result["noncounting_boundaries"], 2)
        self.assertEqual(result["reply_chains"], 502)
        self.assertEqual(result["clock_observations"], 25000)
        self.assertFalse(result["live_qualified"])
        self.assertFalse(result["fusion_qualified"])

    def test_independent_corruptions_refuse(self):
        def find(e, source, kind):
            return next(r["event"] for r in e["records"] if r["source"] == source and r["event"].get("kind") == kind)

        for fault in (
            "request_bytes",
            "response_tc1",
            "short_send",
            "missing_send",
            "missing_status",
            "wrong_status",
            "cold_empty",
            "ordinal",
            "wrong_epoch",
            "clock_gap",
            "clock_return",
            "clock_session",
            "selection_foreign",
            "receive_bytes",
            "replay_count",
            "maintenance_boundary",
        ):
            with self.subTest(fault=fault):
                e = copy.deepcopy(self.evidence)
                if fault == "request_bytes":
                    find(e, "wire", "receive")["raw_hex"] = "00"
                elif fault == "response_tc1":
                    find(e, "wire", "reply_prepared")["response_ns"] += 1000
                elif fault == "short_send":
                    find(e, "wire", "send_return")["count"] -= 1
                elif fault == "missing_send":
                    e["records"].remove(
                        next(r for r in e["records"] if r["source"] == "wire" and r["event"]["kind"] == "send_return")
                    )
                elif fault == "missing_status":
                    e["records"].remove(
                        next(r for r in e["records"] if r["source"] == "cold" and r["event"]["kind"] == "stream_status")
                    )
                elif fault == "wrong_status":
                    find(e, "cold", "stream_status")["status"]["estimated_offset"] += 1
                elif fault == "cold_empty":
                    find(e, "cold", "empty_snapshot")["raw_hex"] = b"not empty\n".hex()
                elif fault == "ordinal":
                    find(e, "maintenance", "maintenance_status")["raw_status"]["ordinal"] += 1
                elif fault == "wrong_epoch":
                    e["context"]["owner"]["start_ticks"] += 1
                elif fault == "clock_gap":
                    e["clock_attempts"].pop(0)
                elif fault == "clock_return":
                    e["clock"]["observations"][0]["journal_return_ns"] += 1
                elif fault == "clock_session":
                    e["clock"]["session_id"] = "foreign"
                elif fault == "selection_foreign":
                    next(r["event"] for r in e["records"] if r["source"] == "selection")["observation"]["iteration"] += 1
                elif fault == "receive_bytes":
                    find(e, "receiver", "receive_return")["data_hex"] = "00"
                elif fault == "replay_count":
                    find(e, "cold", "latest_replay")["counts_as_new_sample"] = True
                elif fault == "maintenance_boundary":
                    find(e, "maintenance", "boundary_snapshot")["observer_input"]["remote_timestamp"] += 1
                # Deletion cases retain otherwise coherent indices so rejection
                # tests the missing causal record, not only the storage reader.
                if fault in ("missing_send", "missing_status"):
                    counts = {}
                    for index, row in enumerate(e["records"]):
                        row["index"] = index
                        row["source_index"] = counts.get(row["source"], 0)
                        counts[row["source"]] = row["source_index"] + 1
                with self.assertRaises(ValueError):
                    self.audit(e)

    def test_two_correlated_pairs_with_only_one_accepted_do_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = self.build_records(Path(directory) / "segments", rejected_first_maintenance=True)
        accepted = [
            r["event"]["observer"]["accepted"]
            for r in evidence["records"]
            if r["source"] == "maintenance" and r["event"]["kind"] == "maintenance_status"
        ]
        self.assertEqual(accepted, [False, True])
        with self.assertRaises(ValueError):
            self.audit(evidence)
