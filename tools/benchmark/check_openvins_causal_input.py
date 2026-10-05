"""Hash-verified fixed-input schedule audit; never runs the estimator or simulator."""

import argparse
import copy
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.benchmark.disarmed_sensor_provenance import audit_event_records  # noqa: E402
from tools.benchmark.openvins_causal_input import CausalInput, raw_profile  # noqa: E402

ARCHIVE_SHA = "7d747d0c841ce6e13bc9614cc9b23381c45b260170f98ac2fdad7ce8bc78313d"
PREFIX = "results/disarmed-sensor-provenance-dev-1701/"


def input_rows(archive):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError("source archive seal changed")
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("SHA256-MANIFEST.json"))
        for name, metadata in manifest.items():
            data = bundle.read(name)
            if len(data) != metadata["bytes"] or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise ValueError("source archive member changed: " + name)
        raw = bundle.read(PREFIX + "capture-v2/events.jsonl")
        rows = [json.loads(line) for line in raw.splitlines()]
        audit_event_records(rows, required_kinds={"imu", "rgb", "depth", "info", "heartbeat"})
        sdf = ET.fromstring(bundle.read(PREFIX + "producer-v2b-snapshot/10-model.sdf"))
        sensor = sdf.find(".//sensor[@name='imu_sensor']")
        if sensor is None or float(sensor.findtext("update_rate")) != 250:
            raise ValueError("source IMU rate mismatch")
        for field, name in [("angular_velocity", "gyro"), ("linear_acceleration", "accel")]:
            std = [float(sensor.findtext(f"imu/{field}/{axis}/noise/stddev")) for axis in "xyz"]
            if std != raw_profile()["noise"][name]["sample_stddev_xyz"]:
                raise ValueError("source noise profile mismatch")
    bases = []
    for i, row in enumerate(rows):
        kind = row["kind"]
        if kind not in {"imu", "rgb", "info"}:
            continue
        keys = {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns"}
        keys |= {"imu": {"gyro_flu", "accel_flu"}, "rgb": {"width", "height"}, "info": {"camera_info"}}[kind]
        bases.append((i, {key: row[key] for key in keys}))
    return bases, hashlib.sha256(raw).hexdigest()


def schedule(rows):
    consumer = CausalInput(session_id="sealed-capture-v2", clock_id="gazebo-sim+capture-monotonic-v2")
    actions = []
    for sequence, (_, row) in enumerate(rows):
        actions.extend(consumer.accept(row, sequence=sequence, session_id=consumer.session_id, clock_id=consumer.clock_id))
    return actions, consumer.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows, input_hash = input_rows(ROOT / "evidence/disarmed-sensor-provenance-dev-1701.zip")
    started = time.perf_counter()
    actions, pending = schedule(rows)
    elapsed = time.perf_counter() - started
    cameras = [a for a in actions if a["kind"] == "camera"]
    imus = [a for a in actions if a["kind"] == "imu"]
    assert len(imus) == sum(r[1]["kind"] == "imu" for r in rows)
    assert len(cameras) + sum(p["rgb_sequence"] is not None for p in pending) == sum(r[1]["kind"] == "rgb" for r in rows)
    for action in cameras:
        assert action["imu_boundary_ns"] > action["sample_ns"]
        assert max(action["rgb_sequence"], action["info_sequence"], action["imu_boundary_sequence"]) <= action["release_sequence"]
        assert rows[action["info_sequence"]][1]["sample_ns"] == action["sample_ns"]
        assert rows[action["imu_boundary_sequence"]][1]["sample_ns"] == action["imu_boundary_ns"]
    imu_index = next(i for i, r in enumerate(rows) if r[1]["kind"] == "imu" and r[1]["sample_ns"] == 8_000_000)
    info_index = next(i for i, r in enumerate(rows) if r[1]["kind"] == "info")
    fault_results = []
    for name in ["missing_imu", "duplicate_imu", "missing_info", "invalid_gyro", "changed_intrinsics", "truth_field"]:
        changed = copy.deepcopy(rows)
        if name == "missing_imu":
            del changed[imu_index]
        elif name == "duplicate_imu":
            changed.insert(imu_index + 1, copy.deepcopy(changed[imu_index]))
        elif name == "missing_info":
            del changed[info_index]
        elif name == "invalid_gyro":
            changed[imu_index][1]["gyro_flu"][0] = float("nan")
        elif name == "changed_intrinsics":
            changed[info_index][1]["camera_info"]["intrinsics_k"][0] += 1
        else:
            changed[imu_index][1]["pose_truth"] = [0, 0, 0]
        try:
            schedule(changed)
        except ValueError as exc:
            fault_results.append({"case": name, "rejected": True, "reason": str(exc), "synthetic_fault": True})
        else:
            raise AssertionError("fault not rejected: " + name)
    waits = [(a["release_wall_ns"] - a["source_arrival_ns"]) / 1e6 for a in cameras]
    summary = {
        "source_archive_sha256": ARCHIVE_SHA,
        "input_events_sha256": input_hash,
        "relevant_inputs": len(rows),
        "imu_deliveries": len(imus),
        "camera_deliveries": len(cameras),
        "pending": pending,
        "faults": fault_results,
        "causal_wait_ms": {"median": float(np.median(waits)), "p95": float(np.percentile(waits, 95)), "max": max(waits)},
        "timing_scope": "recorded callback-arrival watermark in submission order; no estimator or execution latency",
        "offline_schedule_compute_s": elapsed,
        "estimator_run": False,
        "eligible_for_px4_fusion": False,
    }
    for name, value in [
        ("profile.json", raw_profile()),
        ("summary.json", summary),
        ("pending.json", pending),
        ("faults.json", fault_results),
    ]:
        with (args.output / name).open("x") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
    with (args.output / "schedule.jsonl").open("x") as stream:
        for action in actions:
            stream.write(json.dumps(action, allow_nan=False) + "\n")
    with (args.output / "input-index.jsonl").open("x") as stream:
        for sequence, (source_index, row) in enumerate(rows):
            stream.write(json.dumps(dict(sequence=sequence, source_record_index=source_index, **row)) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
