"""Shared-epoch integration, not a whole-study or live-run positive fixture."""

import copy
import tempfile
import unittest
from pathlib import Path

from tests.benchmark.live_wire_joined_fixture import (
    DAEMON,
    add_joined_sources,
    build_joined_wire_physics,
    read_joined_fixture,
)
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.audit_live_wire_workload import audit_source_native_records


class JoinedFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name) / "capture"
        generated = build_joined_wire_physics(directory)
        add_joined_sources(generated)
        del generated
        cls.evidence = read_joined_fixture(directory)
        cls.records = cls.evidence["records"]

    def test_original_shared_clock_passes_four_real_auditors(self):
        e = self.evidence
        protocol = audit.audit_wire_protocol_records(
            records=self.records, clock=e["clock"], clock_attempts=e["clock_attempts"], context=e["context"]
        )
        interval = audit.audit_wire_interval_records(self.records, e["context"])
        listener = audit.audit_owned_listener_records(records=self.records, context=e["context"], daemon_path=DAEMON)
        physical = audit.audit_physical_coverage_records(**e["physical"])
        self.assertEqual(e["context"]["clock_signature"], ["normal-v1.clock", 0, 0])
        self.assertEqual(protocol["bootstrap_accepted"], 500)
        self.assertEqual(protocol["maintenance_accepted"], 149)
        self.assertEqual(protocol["noncounting_boundaries"], 2)
        self.assertEqual(interval["command_count"], 6)
        self.assertEqual(physical["clock_steps"], 25000)
        self.assertEqual(physical["trace_records"], 50000)
        for result in (protocol, interval, listener, physical):
            self.assertFalse(result["live_qualified"])
            self.assertFalse(result["fusion_qualified"])
        self.assertFalse(e["physical_execution_qualified"])

    def test_unrelated_physics_clock_cannot_pass_shared_epoch_join(self):
        e = self.evidence
        physical = copy.deepcopy(e["physical"])
        physical["reference"][400]["wall_ns"] += 1_000_000
        with self.assertRaises(ValueError):
            audit.audit_physical_coverage_records(**physical)
        wrong = copy.deepcopy(e["context"])
        wrong["clock_signature"][2] = 1_000_000
        with self.assertRaises(ValueError):
            audit.audit_wire_protocol_records(
                records=self.records, clock=e["clock"], clock_attempts=e["clock_attempts"], context=wrong
            )

    def test_source_camera_health_and_watchdog_use_shared_clock(self):
        e = self.evidence
        source = audit_source_native_records(**e["source"])
        camera = audit.audit_camera_info_records(**e["camera"])
        health = audit.audit_health_coverage_records(**e["health"])
        watchdog = audit.audit_source_health_records(**e["source_health"])
        self.assertEqual(source["native_sensor_acknowledgements"], 6501)
        self.assertEqual(source["counts"]["imu"], 6251)
        self.assertEqual(source["counts"]["rgb"], 251)
        self.assertEqual(source["public_camera_states"], 0)
        self.assertEqual(health["camera_health_records"], 250)
        self.assertEqual(health["quality_values"], [0])
        self.assertEqual(watchdog["physical_presteps_checked"], 25000)
        for result in (source, camera, health, watchdog):
            self.assertFalse(result["live_qualified"])
            self.assertFalse(result["fusion_qualified"])
