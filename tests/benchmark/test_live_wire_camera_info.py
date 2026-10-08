"""Real installed Gazebo protobuf tests. No transport or simulator objects."""

import copy
import hashlib
import importlib.util
import unittest

from tools.benchmark.openvins_causal_input import raw_profile

try:
    INSTALLED = importlib.util.find_spec("gz.msgs10.camera_info_pb2") is not None
except ModuleNotFoundError:
    INSTALLED = False


def fixture():
    from gz.msgs10.camera_info_pb2 import CameraInfo

    from flydrones.benchmark.camera_info_capture import camera_info_fields

    payloads, sources = {}, []
    fields = raw_profile()["camera_info"]
    for i, stamp in enumerate([2_000_000, *range(100_000_000, 25_000_000_001, 100_000_000)]):
        message = CameraInfo()
        message.header.stamp.sec, message.header.stamp.nsec = divmod(stamp, 1_000_000_000)
        entry = message.header.data.add()
        entry.key = "frame_id"
        entry.value.append("camera_link")
        message.width, message.height = 160, 120
        message.intrinsics.k.extend(fields["intrinsics_k"])
        message.projection.p.extend(fields["projection_p"])
        message.distortion.k.extend(fields["distortion_k"])
        message.rectification_matrix.extend([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])
        raw = message.SerializeToString()
        seq = i * 2
        payloads[seq] = raw
        sources.extend(
            [
                dict(
                    kind="info",
                    sample_ns=stamp,
                    source_sequence=seq,
                    camera_info=camera_info_fields(message),
                    payload_sha256=hashlib.sha256(raw).hexdigest(),
                    payload_path=f"camera-info-messages/{stamp}.pb",
                ),
                dict(kind="rgb", sample_ns=stamp, source_sequence=seq + 1),
            ]
        )
    first = payloads[0]
    manifest = dict(
        schema="flydrones-camera-info-v1",
        topic="/benchmark/rgbd/camera_info",
        message_count=251,
        changed_stable_fields=0,
        camera_info=fields,
        first_message_sha256=hashlib.sha256(first).hexdigest(),
    )
    return dict(sources=sources, payloads=payloads, manifest=manifest, first_payload=first)


def run_audit(value):
    from tools.benchmark import audit_live_wire_study

    function = getattr(audit_live_wire_study, "audit_camera_info_records", None)
    assert callable(function), "CameraInfo audit API missing"
    return function(**value)


@unittest.skipUnless(INSTALLED, "installed gz.msgs10 required; execute in WSL")
class CameraInfoAudit(unittest.TestCase):
    def test_full_real_protobuf_decode(self):
        result = run_audit(fixture())
        self.assertEqual(result["decoded_messages"], 251)
        self.assertTrue(result["raw_calibration_records_consistent"])
        self.assertFalse(result["hardware_calibrated"])
        self.assertFalse(result["fusion_qualified"])

    def test_raw_corruptions_even_with_recomputed_payload_hash(self):
        from gz.msgs10.camera_info_pb2 import CameraInfo

        for fault in ["truncated", "stamp", "invalid_nsec", "intrinsics", "distortion", "rectification", "frame", "unknown"]:
            with self.subTest(fault=fault):
                value = fixture()
                seq = 10
                message = CameraInfo()
                message.ParseFromString(value["payloads"][seq])
                if fault == "stamp":
                    message.header.stamp.nsec += 1
                elif fault == "invalid_nsec":
                    message.header.stamp.nsec = 1_000_000_000
                elif fault == "intrinsics":
                    message.intrinsics.k[0] += 1
                elif fault == "distortion":
                    message.distortion.k[4] = 1
                elif fault == "rectification":
                    message.rectification_matrix[0] = -1
                elif fault == "frame":
                    message.header.data[0].value.append("other")
                raw = message.SerializeToString()
                if fault == "truncated":
                    raw = raw[:-1]
                elif fault == "unknown":
                    raw += bytes([0xA0, 0x06, 1])  # Unknown field 100, varint.
                value["payloads"][seq] = raw
                value["sources"][seq]["payload_sha256"] = hashlib.sha256(raw).hexdigest()
                with self.assertRaises(ValueError):
                    run_audit(value)

    def test_manifest_and_identity_corruptions(self):
        for fault in ["count", "changed", "first", "topic", "fields", "missing", "rgb", "duplicate", "hash", "boolean", "path"]:
            with self.subTest(fault=fault):
                value = fixture()
                if fault == "count":
                    value["manifest"]["message_count"] = 250
                elif fault == "changed":
                    value["manifest"]["changed_stable_fields"] = 1
                elif fault == "first":
                    value["first_payload"] = value["payloads"][2]
                elif fault == "topic":
                    value["manifest"]["topic"] += "-other"
                elif fault == "fields":
                    value["manifest"]["camera_info"]["width"] = 161
                elif fault == "missing":
                    del value["payloads"][10]
                elif fault == "rgb":
                    value["sources"][11]["sample_ns"] += 1
                elif fault == "duplicate":
                    value["sources"][10] = copy.deepcopy(value["sources"][8])
                elif fault == "hash":
                    value["sources"][10]["payload_sha256"] = "0" * 64
                elif fault == "boolean":
                    value["sources"][0]["source_sequence"] = False
                elif fault == "path":
                    value["sources"][10]["payload_path"] = "../other.pb"
                with self.assertRaises(ValueError):
                    run_audit(value)


if __name__ == "__main__":
    unittest.main()
