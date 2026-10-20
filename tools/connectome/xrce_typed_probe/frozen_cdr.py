"""Extract only the test body of one sealed synthetic VehicleOdometry CDR."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ARCHIVE_SHA = "c651681d58013803c5ea7d15301a2ac39ca9526c275244c1839809fb3351ba4b"
MEMBER = "results/px4-ros2-full-synthetic-dev-1701-v6/synthetic-v2.jsonl"
FULL_CDR_SHA = "42107b9f3998414a86a2da8908a45bd13d4e91af4b51ae2625d90ea661a42ed8"
BODY_SHA = "fcd9a9219bb6b082906ba71a013132f500210367bf8737915e395270e530aa82"
MESSAGE_BLOB = "cf117ff82cdbf191bf576db91db900b7ce34f6a7"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract(archive: Path) -> tuple[bytes, dict]:
    if sha(archive.read_bytes()) != ARCHIVE_SHA:
        raise ValueError("frozen archive hash mismatch")
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:
            raise ValueError("frozen archive CRC mismatch")
        raw = source.read(MEMBER)
    rows = [json.loads(line) for line in raw.splitlines() if line]
    samples = [row for row in rows if row.get("kind") == "sample"]
    if len(samples) != 1 or len(rows) != 2 or rows[-1].get("kind") != "finish":
        raise ValueError("expected one complete synthetic sample and finish")
    row = samples[0]
    if (row.get("schema") != "flydrones.px4_ros2_odometry_cdr.v2"
            or row.get("run_id") != "synthetic-v2"
            or row.get("topic") != "/fmu/out/vehicle_odometry"
            or row.get("ros_type") != "px4_msgs/msg/VehicleOdometry"
            or row.get("message_blob_sha") != MESSAGE_BLOB
            or row.get("cdr_sha256") != FULL_CDR_SHA):
        raise ValueError("synthetic source identity mismatch")
    full = bytes.fromhex(row["cdr_hex"])
    if len(full) != 120 or full[:4] != b"\x00\x01\x00\x00" or sha(full) != FULL_CDR_SHA:
        raise ValueError("CDR encapsulation or hash mismatch")
    body = full[4:]
    if len(body) != 116 or sha(body) != BODY_SHA:
        raise ValueError("XRCE body mismatch")
    receipt = {"schema": "flydrones.xrce_synthetic_cdr_body.v1",
               "source_archive_sha256": ARCHIVE_SHA, "source_member": MEMBER,
               "synthetic_run_id": "synthetic-v2", "topic": row["topic"],
               "ros_type": row["ros_type"], "full_cdr_sha256": FULL_CDR_SHA,
               "body_sha256": BODY_SHA, "body_bytes": len(body),
               "synthetic_only": True, "px4_source_authenticated": False,
               "fusion_qualified": False, "eligible_for_live_capture": False}
    return body, receipt


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: frozen_cdr.py ARCHIVE OUTPUT_BODY")
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    sidecar = Path(str(target) + ".json")
    if target.exists() or sidecar.exists():
        raise FileExistsError("refuse to overwrite frozen output")
    body, receipt = extract(source)
    try:
        with target.open("xb") as file:
            file.write(body)
        with sidecar.open("x", encoding="utf-8") as file:
            json.dump(receipt, file, indent=2)
    except Exception:
        if target.exists() and not sidecar.exists():
            target.unlink()
        raise
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
