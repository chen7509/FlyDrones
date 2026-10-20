"""Analytic binary ULogs parsed by installed pyulog; no simulator or network."""

import hashlib
import importlib.util
import struct
import unittest
from unittest.mock import patch

try:
    from pyulog import ULog
except ImportError as exc:
    raise unittest.SkipTest("use existing WSL pyulog for binary evidence tests") from exc

from tests.benchmark.receiver_ulog_fixture import record


def raw_log(*, armed=0, state=1, reverse=False, missing=None):
    definitions = b"ULog\x01\x12\x35\x01" + struct.pack("<Q", 1) + record("B", bytes(40))
    definitions += record("F", b"vehicle_status:uint64_t timestamp;uint8_t arming_state;")
    definitions += record("F", b"actuator_armed:uint64_t timestamp;bool armed;")
    data = b""
    for msg_id, name, value in ((0, "vehicle_status", state), (1, "actuator_armed", armed)):
        if name == missing:
            continue
        data += record("A", struct.pack("<BH", 0, msg_id) + name.encode())
        for stamp in [2_000_000, 1_000_000] if reverse else [1_000_000, 2_000_000]:
            data += record("D", struct.pack("<HQB", msg_id, stamp, value))
    return definitions + data


class ULogAuditTests(unittest.TestCase):
    def audit(self, raw, **entry_changes):
        self.assertIsNotNone(importlib.util.find_spec("tools.benchmark.audit_live_wire_ulog"), "unarmed ULog audit missing")
        from tools.benchmark.audit_live_wire_ulog import audit_unarmed_ulog

        entry = dict(path="px4-ulog/log/example.ulg", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), valid_header=True)
        entry.update(entry_changes)
        return audit_unarmed_ulog(raw, entry)

    def test_same_complete_bytes_decode_to_unarmed_observations(self):
        result = self.audit(raw_log())
        self.assertTrue(result["unarmed_log_observations"])
        self.assertEqual(result["status_samples"], 2)
        self.assertEqual(result["actuator_samples"], 2)
        self.assertEqual(result["status_span_us"], 1_000_000)
        self.assertFalse(result["full_capture_coverage_qualified"])
        self.assertFalse(result["live_qualified"])
        self.assertFalse(result["fusion_qualified"])

    def test_binary_faults_refuse_even_with_matching_manifest_hash(self):
        normal = raw_log()
        for name, raw in {
            "armed": raw_log(armed=1),
            "armed_state": raw_log(state=2),
            "timestamp_regression": raw_log(reverse=True),
            "missing_status": raw_log(missing="vehicle_status"),
            "missing_actuator": raw_log(missing="actuator_armed"),
            "truncated_header": normal + b"\x01",
            "truncated_data": normal[:-1],
            "dropout": normal + record("O", b"\x01\0"),
            "short_data": normal + record("D", b"\x00\x00\x01"),
            "duplicate_subscription": normal + record("A", b"\x00\x00\x00vehicle_status"),
        }.items():
            with self.subTest(fault=name), self.assertRaises(ValueError):
                self.audit(raw)

    def test_entry_identity_and_path_must_match(self):
        for change in (
            {"sha256": "0" * 64},
            {"bytes": True},
            {"valid_header": False},
            {"path": "../outside.ulg"},
            {"path": "/absolute.ulg"},
            {"path": "px4-ulog/../other.ulg"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.audit(raw_log(), **change)

    def test_parser_cannot_hide_raw_samples(self):
        def partial(stream, **kwargs):
            parsed = ULog(stream, **kwargs)
            topic = next(row for row in parsed.data_list if row.name == "vehicle_status")
            topic.data = {key: values[:-1] for key, values in topic.data.items()}
            return parsed

        with patch("pyulog.ULog", partial), self.assertRaisesRegex(ValueError, "count"):
            self.audit(raw_log())
