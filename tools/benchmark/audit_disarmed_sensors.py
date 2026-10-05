#!/usr/bin/env python3
"""Audit one captured disarmed sensor stream and corresponding PX4 ULog."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from flydrones.benchmark.camera_info_capture import verify_camera_info_capture  # noqa: E402
from flydrones.benchmark.rgb_capture import verify_rgb_manifest  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import audit_event_records, compare_imu  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--legacy-first-info", action="store_true", help="Audit v1 evidence without reconstructing missing CameraInfo stamps"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    capture = args.capture.resolve()
    result = json.loads((capture / "result.json").read_text())
    rows = [json.loads(line) for line in (capture / "events.jsonl").read_text().splitlines()]
    groups = {kind: [r for r in rows if r["kind"] == kind] for kind in ["imu", "rgb", "depth", "info", "heartbeat"]}
    counts = audit_event_records(rows, required_kinds=set(groups), allow_legacy_info=args.legacy_first_info)
    if counts != result["writer"]["written"]:
        raise ValueError("record counts differ from producer summary")
    if result["status"] != "capture_completed" or result["errors"] or result["estimator_run"]:
        raise ValueError("capture incomplete or wrong scope")
    rgb = verify_rgb_manifest(capture)
    camera = verify_camera_info_capture(capture)
    stamps = [r["sample_ns"] for r in groups["rgb"]]
    if stamps != [r["sample_ns"] for r in groups["depth"]] or stamps != [r["frame_ns"] for r in rgb["frames"]]:
        raise ValueError("RGB/depth/file timestamps disagree")
    complete_info = all("sample_ns" in r for r in groups["info"])
    if complete_info:
        from gz.msgs10.camera_info_pb2 import CameraInfo

        from flydrones.benchmark.camera_info_capture import camera_info_fields

        for row in groups["info"]:
            payload = (capture / row["payload_path"]).read_bytes()
            message = CameraInfo()
            message.ParseFromString(payload)
            stamp = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
            if (
                hashlib.sha256(payload).hexdigest() != row["payload_sha256"]
                or stamp != row["sample_ns"]
                or camera_info_fields(message) != row["camera_info"]
            ):
                raise ValueError("camera-info payload changed or disagrees with event")
        if stamps != [r["sample_ns"] for r in groups["info"]]:
            raise ValueError("camera-info/RGB timestamps disagree")
    from pyulog import ULog

    if len(result["px4_ulogs"]) != 1:
        raise ValueError("expected one captured ULog")
    log = result["px4_ulogs"][0]
    path = (capture / log["path"]).resolve()
    if not path.is_relative_to(capture / "px4-ulog"):
        raise ValueError("ULog path escaped evidence directory")
    if hashlib.sha256(path.read_bytes()).hexdigest() != log["sha256"] or path.stat().st_size != log["bytes"]:
        raise ValueError("ULog changed")
    ulog = ULog(str(path))
    imu = ulog.get_dataset("sensor_combined").data
    armed = ulog.get_dataset("actuator_armed").data
    statuses = ulog.get_dataset("vehicle_status").data

    def vector(key):
        return np.column_stack([imu[f"{key}[{i}]"] for i in range(3)])

    comparison = compare_imu(groups["imu"], imu["timestamp"], vector("gyro_rad"), vector("accelerometer_m_s2"))
    cadences = {}
    for kind in ["imu", "rgb", "depth"]:
        stamps = np.array([r["sample_ns"] for r in groups[kind]], dtype=np.int64)
        delta = np.diff(stamps)
        expected = 4_000_000 if kind == "imu" else 100_000_000
        cadences[kind] = {
            "count": len(stamps),
            "first_ns": int(stamps[0]),
            "last_ns": int(stamps[-1]),
            "delta_min_ns": int(delta.min()),
            "delta_max_ns": int(delta.max()),
            "nonmonotonic": int(np.sum(delta <= 0)),
            "non_nominal_intervals": int(np.sum(delta != expected)),
        }
    times = {}
    for kind, items in groups.items():
        queue_ms = [(r["writer_begin_monotonic_ns"] - r["arrival_monotonic_ns"]) / 1e6 for r in items]
        preparation_ms = [(r["recorded_monotonic_ns"] - r["arrival_monotonic_ns"]) / 1e6 for r in items]
        times[kind] = {
            "callback_to_writer_median_ms": float(np.median(queue_ms)),
            "callback_to_writer_p95_ms": float(np.percentile(queue_ms, 95)),
            "callback_to_record_preparation_max_ms": float(max(preparation_ms)),
        }
    hb = groups["heartbeat"]
    safety = {
        "heartbeat_count": len(hb),
        "any_heartbeat_armed": any(r["base_mode"] & 128 for r in hb),
        "ulog_actuator_armed_count": len(armed["armed"]),
        "ulog_any_armed": bool(np.any(armed["armed"])),
        "ulog_arming_states": sorted(set(int(v) for v in statuses["arming_state"])),
    }
    flags = {
        key: sorted(set(int(v) for v in imu[key]))
        for key in [
            "gyro_integral_dt",
            "accelerometer_integral_dt",
            "accelerometer_timestamp_relative",
            "accelerometer_clipping",
            "gyro_clipping",
            "accel_calibration_count",
            "gyro_calibration_count",
        ]
    }
    summary = {
        "schema": "flydrones-disarmed-sensor-audit-v1",
        "capture_status": result["status"],
        "cadence": cadences,
        "safety": safety,
        "imu_comparison": comparison,
        "sensor_combined_fields": flags,
        "ulog_imu_count": len(imu["timestamp"]),
        "camera_info_messages": camera["message_count"],
        "camera_info_all_sample_payloads_retained": complete_info,
        "legacy_camera_info_limitation": not complete_info,
        "rgb_verified_frames": len(rgb["frames"]),
        "timings": times,
        "timing_scope": "callback arrival to writer/preparation; not generation-to-estimate latency",
        "input_hashes": {
            name: hashlib.sha256((capture / name).read_bytes()).hexdigest()
            for name in ["result.json", "events.jsonl", "launch.json"]
        },
        "source_equivalence_qualified": False,
        "online_vio_validated": False,
        "eligible_for_px4_fusion": False,
    }
    with args.output.open("x") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
