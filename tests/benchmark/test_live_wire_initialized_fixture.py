"""Initialized synthetic chain; not evidence that OpenVINS or physics ran."""

import copy
import tempfile
import unittest
from pathlib import Path

from tests.benchmark.live_wire_joined_fixture import DAEMON, add_joined_sources, build_joined_wire_physics, read_joined_fixture
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.audit_live_wire_workload import audit_source_native_records


class InitializedFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name) / "capture"
        generated = build_joined_wire_physics(directory)
        add_joined_sources(generated, initialized_at_ns=1_200_000_000)
        del generated
        cls.evidence = read_joined_fixture(directory)

    def test_initialized_ack_health_fast_share_native_order_and_disk_inputs(self):
        e = self.evidence
        source = audit_source_native_records(**e["source"])
        health = audit.audit_health_coverage_records(**e["health"])
        fast = audit.audit_fast_coverage_records(**e["fast"])
        self.assertEqual(source["native_sensor_acknowledgements"], 6501)
        self.assertEqual(source["public_camera_states"], 237)
        self.assertEqual(health["quality_values"], [0])
        self.assertEqual(fast["targets"], 1249)
        self.assertEqual(fast["unavailable_targets"], 60)
        self.assertEqual(fast["successful_targets"], 1189)
        self.assertFalse(fast["accuracy_qualified"])
        self.assertFalse(fast["covariance_calibrated"])
        for result in (source, health, fast):
            self.assertFalse(result["live_qualified"])
            self.assertFalse(result["fusion_qualified"])
        self.assertFalse(e["provenance"]["native_estimator_run"])
        self.assertFalse(e["provenance"]["whole_study_qualified"])

    def test_initialized_bundle_also_passes_original_clock_camera_and_source_checks(self):
        e = self.evidence
        results = [
            audit.audit_wire_protocol_records(
                records=e["records"], clock=e["clock"], clock_attempts=e["clock_attempts"], context=e["context"]
            ),
            audit.audit_wire_interval_records(e["records"], e["context"]),
            audit.audit_owned_listener_records(records=e["records"], context=e["context"], daemon_path=DAEMON),
            audit.audit_physical_coverage_records(**e["physical"]),
            audit.audit_camera_info_records(**e["camera"]),
            audit.audit_source_health_records(**e["source_health"]),
        ]
        for result in results:
            self.assertFalse(result["live_qualified"])
            self.assertFalse(result["fusion_qualified"])

    def test_prediction_cannot_claim_initialization_earlier_than_its_camera(self):
        evidence = copy.deepcopy(self.evidence["fast"])
        row = evidence["records"][58]
        self.assertFalse(row["internal_initialized"])
        row["internal_initialized"] = True
        with self.assertRaises(ValueError):
            audit.audit_fast_coverage_records(**evidence)

    def test_prediction_cannot_borrow_next_imu_or_move_processing_outside_ack(self):
        for field, value in (("available_imu_ns", 1_228_000_000), ("native_end_ns", 9_000_000_000)):
            with self.subTest(field=field):
                evidence = copy.deepcopy(self.evidence["fast"])
                evidence["records"][60][field] = value
                with self.assertRaises(ValueError):
                    audit.audit_fast_coverage_records(**evidence)

    def test_initialized_health_cannot_promote_unqualified_covariance(self):
        evidence = copy.deepcopy(self.evidence["health"])
        row = next(row for row in evidence["records"] if row["sample_ns"] >= 1_300_000_000)
        row["health"]["quality"] = 1
        with self.assertRaises(ValueError):
            audit.audit_health_coverage_records(**evidence)

    def test_native_motion_and_anchor_share_sources_without_granting_flight(self):
        e = self.evidence
        motion = audit.audit_motion_records(**e["motion"])
        anchor = audit.audit_anchor_records(**e["anchor"])
        gauge = audit.audit_gauge_records(**e["gauge"])
        self.assertEqual(motion["anchor_ns"], 1_405_000_000)
        self.assertEqual(motion["lateral_steps"], 1600)
        self.assertEqual(anchor["estimator_records"], 238)
        self.assertEqual(anchor["heartbeat_observations"], 24)
        self.assertTrue(gauge["diagnostic_screens_pass"])
        self.assertTrue(gauge["public_coverage_qualified"])
        self.assertEqual(gauge["origin"]["sample_ns"], 1_200_000_000)
        self.assertFalse(gauge["trajectory_qualified"])
        self.assertFalse(gauge["estimator_health_qualified"])
        for result in (motion, anchor, gauge):
            self.assertFalse(result["live_qualified"])
            self.assertFalse(result["fusion_qualified"])

    def test_motion_requires_original_native_ack_and_committed_anchor_source(self):
        evidence = copy.deepcopy(self.evidence["motion"])
        next(r for r in evidence["acknowledgements"] if r["kind"] == "M")["intent_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            audit.audit_motion_records(**evidence)
        evidence = copy.deepcopy(self.evidence["anchor"])
        evidence["anchor"]["proof"]["records"]["imu"]["source_sequence"] -= 1
        with self.assertRaises(ValueError):
            audit.audit_anchor_records(**evidence)

    def test_estimator_receipt_cannot_be_attributed_to_original_image_arrival(self):
        evidence = copy.deepcopy(self.evidence["anchor"])
        receipt = evidence["estimator_records"][0]
        image = next(row for row in evidence["sources"] if row["kind"] == "rgb" and row["sample_ns"] == receipt["sample_ns"])
        from tools.benchmark.ready_shadow_fanout import digest

        receipt.update(
            source_sequence=image["source_sequence"],
            source_sha256=digest(image),
            source_arrival_monotonic_ns=image["arrival_monotonic_ns"],
            observed_sim_ns=image["observed_sim_ns"],
        )
        with self.assertRaises(ValueError):
            audit.audit_anchor_records(**evidence)

    def test_gauge_does_not_treat_identity_flu_as_identity_frd(self):
        evidence = copy.deepcopy(self.evidence["gauge"])
        for row in evidence["states"]:
            if row["internal_initialized"]:
                row["imu_state"][:4] = [0.0, 0.0, 0.0, 1.0]
        result = audit.audit_gauge_records(**evidence)
        self.assertFalse(result["diagnostic_screens_pass"])
        self.assertFalse(result["fusion_qualified"])


if __name__ == "__main__":
    unittest.main()
