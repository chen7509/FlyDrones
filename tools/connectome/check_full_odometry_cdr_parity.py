"""Check one synthetic v2 journal row against independently decoded ROS CDR.

Run inside the pinned ROS 2 environment with the exact built px4_msgs type.
This is a codec check, never an owned-PX4 source authentication.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

from px4_msgs.msg import VehicleOdometry
from rclpy.serialization import deserialize_message

FIELDS = {
    "position_ned_m": "position",
    "q_body_to_ned_wxyz": "q",
    "velocity_ned_m_s": "velocity",
    "omega_body_frd_rad_s": "angular_velocity",
    "position_variance_m2": "position_variance",
    "orientation_variance_rad2": "orientation_variance",
    "velocity_variance_m2_s2": "velocity_variance",
}


def main(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        raise ValueError("synthetic journal path or size invalid")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if (len(rows) != 2 or rows[0].get("schema") != "flydrones.px4_ros2_odometry_cdr.v2"
            or rows[0].get("kind") != "sample" or rows[1].get("kind") != "finish"
            or rows[1].get("status") != "complete" or rows[1].get("samples") != 1):
        raise ValueError("one complete synthetic v2 sample required")
    row = rows[0]
    cdr = bytes.fromhex(row["cdr_hex"])
    if hashlib.sha256(cdr).hexdigest() != row["cdr_sha256"]:
        raise ValueError("CDR hash mismatch")
    decoded = deserialize_message(cdr, VehicleOdometry)
    for key, member in FIELDS.items():
        actual = getattr(decoded, member)
        recorded = row[key]
        if len(actual) != len(recorded):
            raise ValueError(f"{key} length mismatch")
        for expected_float32, journal_float in zip(actual, recorded):
            if journal_float is None or struct.pack("<f", journal_float) != struct.pack(
                    "<f", expected_float32):
                raise ValueError(f"{key} differs from independently decoded CDR")
    scalars = {
        "px4_publication_us": decoded.timestamp,
        "px4_sample_us": decoded.timestamp_sample,
        "pose_frame": decoded.pose_frame,
        "velocity_frame": decoded.velocity_frame,
        "reset_counter": decoded.reset_counter,
        "quality": decoded.quality,
    }
    for key, expected in scalars.items():
        if row[key] != expected:
            raise ValueError(f"{key} differs from independently decoded CDR")
    print(json.dumps({"schema": "flydrones.px4_ros2_cdr_parity.v1",
                      "journal_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "cdr_sha256": row["cdr_sha256"], "fields_checked": len(FIELDS),
                      "scalar_fields_checked": len(scalars),
                      "synthetic_only": True, "eligible_for_live_capture": False},
                     sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_full_odometry_cdr_parity.py JOURNAL.jsonl")
    main(Path(sys.argv[1]))
