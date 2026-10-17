"""Independently decode a synthetic status journal with ROS Python type support."""

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

from px4_msgs.msg import EstimatorStatus
from rclpy.serialization import deserialize_message

RATIOS = (
    "hdg_test_ratio", "vel_test_ratio", "pos_test_ratio", "hgt_test_ratio",
    "tas_test_ratio", "hagl_test_ratio", "beta_test_ratio",
)
RESETS = (
    "reset_count_vel_ne", "reset_count_vel_d", "reset_count_pos_ne",
    "reset_count_pod_d", "reset_count_quat",
)


def same_float32(written, decoded):
    return struct.pack("<f", written) == struct.pack("<f", decoded)


def check(path):
    samples = 0
    unavailable = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["kind"] != "sample":
            continue
        raw = bytes.fromhex(row["cdr_hex"])
        assert hashlib.sha256(raw).hexdigest() == row["cdr_sha256"]
        decoded = deserialize_message(raw, EstimatorStatus)
        for name, encoded in (
            ("px4_publication_us", decoded.timestamp),
            ("px4_sample_us", decoded.timestamp_sample),
            ("control_mode_flags", decoded.control_mode_flags),
            ("filter_fault_flags", decoded.filter_fault_flags),
            ("gps_check_fail_flags", decoded.gps_check_fail_flags),
            ("solution_status_flags", decoded.solution_status_flags),
        ):
            assert row[name] == encoded, (samples, name)
        for name in ("pos_horiz_accuracy", "pos_vert_accuracy"):
            assert same_float32(row[name], getattr(decoded, name)), (samples, name)
        for name in RATIOS:
            value = getattr(decoded, name)
            if math.isfinite(value):
                assert row["innovation_ratio_available"][name] is True
                assert same_float32(row["innovation_test_ratios"][name], value), (samples, name)
            else:
                assert row["innovation_ratio_available"][name] is False
                assert row["innovation_test_ratios"][name] is None
                unavailable.add(name)
        for name in RESETS:
            assert row["reset_counters"][name] == getattr(decoded, name)
        samples += 1
    assert samples > 0
    return {"independent_cdr_parity": True, "samples": samples,
            "unavailable_ratios": sorted(unavailable)}


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), sort_keys=True))
