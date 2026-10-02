#!/usr/bin/env python3
"""Summarize first-sample IMU timing from a sensor-readiness campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summarize(path_text: str) -> dict[str, object]:
    from pyulog import ULog

    path = Path(path_text)
    ulog = ULog(str(path))
    sensor = next(item for item in ulog.data_list if item.name == "sensor_combined")
    timestamps = sensor.data["timestamp"]
    gyro_dt = sensor.data["gyro_integral_dt"]
    estimator = next(
        (item for item in ulog.data_list if item.name == "estimator_status"), None
    )
    estimator_delay_s = None
    if estimator is not None and len(estimator.data["timestamp"]):
        estimator_delay_s = (
            int(estimator.data["timestamp"][0]) - int(timestamps[0])
        ) / 1e6
    return {
        "run": path.parents[1].name,
        "vehicle_id": int(path.stem.split("-")[-1]),
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "sensor_combined_rows": len(timestamps),
        "first_sensor_timestamp_s": int(timestamps[0]) / 1e6,
        "first_gyro_integral_dt_us": int(gyro_dt[0]),
        "max_first_ten_gyro_integral_dt_us": int(max(gyro_dt[:10])),
        "first_estimator_status_delay_s": estimator_delay_s,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    paths = sorted(args.campaign_dir.glob("readiness-formal-*/px4-ulogs/agent-*.ulg"))
    if len(paths) != 50:
        raise SystemExit(f"expected 50 formal ULogs, found {len(paths)}")
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        records = list(executor.map(_summarize, (str(path) for path in paths)))
    first_dt = [int(record["first_gyro_integral_dt_us"]) for record in records]
    first_ten = [
        int(record["max_first_ten_gyro_integral_dt_us"]) for record in records
    ]
    payload = {
        "schema": "flydrones-px4-first-imu-dt-evidence-v1",
        "campaign": args.campaign_dir.name,
        "ulog_count": len(records),
        "vehicle_count_per_run": 5,
        "run_count": 10,
        "first_gyro_integral_dt_us": {
            "min": min(first_dt),
            "median": statistics.median(first_dt),
            "max": max(first_dt),
        },
        "max_first_ten_gyro_integral_dt_us": {
            "min": min(first_ten),
            "median": statistics.median(first_ten),
            "max": max(first_ten),
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload | {"records": "omitted"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
