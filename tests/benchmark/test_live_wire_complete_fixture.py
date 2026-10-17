"""Full production file routing with synthetic records and no leaf doubles."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.benchmark.audit_live_wire_study import audit_live_wire_study


class CompleteFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module = "tests.benchmark.live_wire_complete_fixture"
        assert importlib.util.find_spec(module) is not None, "complete synthetic file producer not implemented"
        from tests.benchmark.live_wire_complete_fixture import build_complete_fixture

        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.manifest, cls.capture = build_complete_fixture(Path(cls.temp.name))

    def test_all_original_files_pass_production_entry_without_live_authority(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("offline audit attempted runtime activation")

        with patch("subprocess.Popen", forbidden), patch("socket.socket", forbidden):
            result = audit_live_wire_study(self.manifest)
        self.assertEqual(result["refusals"], [])
        self.assertEqual(len(result["checks"]), 21)
        self.assertIn("ulog", result["checks"])
        self.assertTrue(result["checks"]["runtime"]["runtime_records_consistent"])
        self.assertEqual(result["checks"]["source_native"]["native_sensor_acknowledgements"], 6501)
        self.assertFalse(result["record_chain_qualified"])
        self.assertFalse(result["live_qualified"])
        self.assertFalse(result["fusion_qualified"])
        self.assertTrue(result["unverified"])
        self.assertFalse(Path(json.loads(self.manifest.read_text())["outputs"]["audit"]).exists())

    def mutate(self, member, change, stage):
        path = self.capture / member
        raw = path.read_bytes()
        try:
            value = json.loads(raw)
            change(value)
            path.write_text(json.dumps(value))
            result = audit_live_wire_study(self.manifest)
            self.assertTrue(result["refusals"])
            self.assertEqual(result["refusals"][0]["stage"], stage, result["refusals"])
            self.assertFalse(result["live_qualified"])
        finally:
            path.write_bytes(raw)

    def test_runtime_owner_cannot_change_even_when_summary_claims_success(self):
        self.mutate("runtime-owner-openvins.json", lambda row: row.update(pid=999), "runtime")

    def test_native_process_must_match_declared_owned_runtime(self):
        self.mutate("shadow/native-session.json", lambda row: row.update(pid=999), "source_native")

    def test_resource_query_failure_cannot_hide_behind_graph_summary(self):
        self.mutate("resource-query-0000.json", lambda row: row.update(returncode=1), "resource_graph")

    def test_ulog_bytes_are_required_after_all_other_checks(self):
        entry = json.loads((self.capture / "px4-ulog-manifest.json").read_text())["logs"][0]
        path = self.capture / entry["path"]
        raw = path.read_bytes()
        try:
            path.write_bytes(raw[:-1])
            result = audit_live_wire_study(self.manifest)
            self.assertEqual(result["refusals"][0]["stage"], "ulog", result["refusals"])
            self.assertFalse(result["record_chain_qualified"])
        finally:
            path.write_bytes(raw)


if __name__ == "__main__":
    unittest.main()
