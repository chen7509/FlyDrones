#!/usr/bin/env python3
"""Fail-closed offline preflight of the current OpenVINS state-only CSV.

This does not publish MAVLink, use scoring truth, or qualify VIO for flight.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

STATE_COLUMNS = ["image_ns", "initialized", "state_timestamp_s", "qx", "qy",
                 "qz", "qw", "px", "py", "pz"]
FUSION_FIELDS_ABSENT_FROM_SOURCE = [
    "linear_velocity", "pose_covariance", "velocity_covariance",
    "reset_counter", "quality", "reference_frame", "body_frame",
    "arrival_time_ns", "camera_imu_calibration_validation",
]


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(states_csv: Path, *, speed_limit_mps: float) -> dict:
    """Screen state discontinuities; never equate a clean screen with fusion readiness."""
    if not math.isfinite(speed_limit_mps) or speed_limit_mps <= 0:
        raise ValueError("speed limit must be positive and finite")
    threshold = 2.0 * speed_limit_mps
    if not math.isfinite(threshold):
        raise ValueError("speed screen threshold overflow")
    with states_csv.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != STATE_COLUMNS:
            raise ValueError("unexpected OpenVINS state columns")
        rows = list(reader)
    if not rows:
        raise ValueError("empty OpenVINS state CSV")

    image_times: list[int] = []
    state_times: list[float] = []
    positions: list[list[float]] = []
    initialized_image_times: list[int] = []
    seen_initialized = False
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("unexpected CSV row width")
        image_ns = int(row["image_ns"])
        if image_ns < 0 or (image_times and image_ns <= image_times[-1]):
            raise ValueError("nonmonotonic image timestamp")
        image_times.append(image_ns)
        flag = row["initialized"]
        if flag not in {"0", "1"}:
            raise ValueError("invalid initialization flag")
        if flag == "0":
            if seen_initialized:
                raise ValueError("lost initialization without reset metadata")
            uninitialized_time = float(row["state_timestamp_s"])
            if (not math.isfinite(uninitialized_time)
                    or (uninitialized_time != -1.0
                        and not 0 <= uninitialized_time <= image_ns * 1e-9 + 1e-5)
                    or any(row[key] != "" for key in STATE_COLUMNS[3:])):
                raise ValueError("invalid uninitialized state sentinel")
            continue
        seen_initialized = True
        state_time = float(row["state_timestamp_s"])
        pose = [float(row[key]) for key in ("px", "py", "pz")]
        quaternion = [float(row[key]) for key in ("qx", "qy", "qz", "qw")]
        if not all(math.isfinite(value) for value in [state_time, *pose, *quaternion]):
            raise ValueError("non-finite initialized state")
        if state_times and state_time <= state_times[-1]:
            raise ValueError("nonmonotonic state timestamp")
        if abs(state_time - image_ns * 1e-9) > 1e-5:
            raise ValueError("image/state timestamp mismatch")
        if abs(float(np.linalg.norm(quaternion)) - 1.0) > 0.01:
            raise ValueError("invalid quaternion norm")
        state_times.append(state_time)
        positions.append(pose)
        initialized_image_times.append(image_ns)

    events = []
    max_apparent_speed = None
    max_state_gap = None
    if len(state_times) > 1:
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                dt = np.diff(np.asarray(state_times, dtype=float))
                displacement = np.linalg.norm(np.diff(np.asarray(positions, dtype=float), axis=0), axis=1)
                speeds = displacement / dt
        except FloatingPointError as error:
            raise ValueError("non-finite state displacement or speed overflow") from error
        if not np.all(np.isfinite(displacement)) or not np.all(np.isfinite(speeds)):
            raise ValueError("non-finite state displacement or speed")
        max_apparent_speed = float(np.max(speeds))
        max_state_gap = float(np.max(dt))
        for index in np.flatnonzero(speeds > threshold):
            i = int(index)
            events.append({
                "from_image_ns": initialized_image_times[i],
                "to_image_ns": initialized_image_times[i + 1],
                "dt_s": float(dt[i]),
                "displacement_m": float(displacement[i]),
                "apparent_speed_mps": float(speeds[i]),
            })

    return {
        "schema": "flydrones-vio-fusion-readiness-audit-v1",
        "scope": "offline state-only screening, never PX4 fusion acceptance",
        "states_sha256": _sha(states_csv),
        "truth_used": False,
        "total_image_frames": len(rows),
        "initialized_frames": len(state_times),
        "first_initialized_image_ns": initialized_image_times[0] if state_times else None,
        "last_initialized_image_ns": initialized_image_times[-1] if state_times else None,
        "max_state_gap_s": max_state_gap,
        "commanded_speed_limit_mps": speed_limit_mps,
        "speed_screen_threshold_mps": threshold,
        "speed_screen_is_flight_limit": False,
        "max_apparent_speed_mps": max_apparent_speed,
        "speed_screen_events": events,
        "missing_fusion_fields": FUSION_FIELDS_ABSENT_FROM_SOURCE,
        "eligible_for_px4_fusion": False,
        "reason": "current state-only offline CSV lacks measured covariance, reset, quality, frame, and arrival-time evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--speed-limit-mps", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite VIO readiness audit")
    result = audit(args.states, speed_limit_mps=args.speed_limit_mps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
