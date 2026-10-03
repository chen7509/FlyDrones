#!/usr/bin/env python3
"""Verify read-only OpenVINS native IMU moments against the frozen state CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

STATE_COLUMNS = ["image_ns", "initialized", "state_timestamp_s", "qx", "qy", "qz", "qw", "px", "py", "pz"]
MOMENT_COLUMNS = (["image_ns", "state_timestamp_s", "vx", "vy", "vz"]
                  + [f"cov_{row}_{col}" for row in range(15) for col in range(15)])
ERROR_ORDER = ["dtheta", "dposition", "dvelocity", "gyro_bias", "accel_bias"]
EVENT_IMAGE_NS = (46_100_000_000, 46_200_000_000, 46_300_000_000)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read(path: Path, columns: list[str]) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            raise ValueError(f"unexpected columns in {path.name}")
        rows = list(reader)
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"empty or malformed CSV rows in {path.name}")
    return rows


def audit(states_csv: Path, moments_csv: Path) -> dict:
    all_states = _read(states_csv, STATE_COLUMNS)
    if any(row["initialized"] not in {"0", "1"} for row in all_states):
        raise ValueError("invalid initialization flag")
    states = [row for row in all_states if row["initialized"] == "1"]
    moments = _read(moments_csv, MOMENT_COLUMNS)
    if not states or len(states) != len(moments):
        raise ValueError("initialized frame count mismatch")
    previous_ns = -1
    pos_variances: list[float] = []
    vel_variances: list[float] = []
    velocity_norms: list[float] = []
    min_eigenvalues: list[float] = []
    event_rows = []
    for state, row in zip(states, moments, strict=True):
        image_ns = int(row["image_ns"])
        if image_ns <= previous_ns or image_ns != int(state["image_ns"]):
            raise ValueError("image timestamp mismatch or nonmonotonic")
        previous_ns = image_ns
        state_time = float(row["state_timestamp_s"])
        if (not math.isfinite(state_time)
                or abs(state_time - float(state["state_timestamp_s"])) > 1e-9
                or abs(state_time - image_ns * 1e-9) > 1e-5):
            raise ValueError("state timestamp mismatch")
        values = np.asarray([float(row[key]) for key in MOMENT_COLUMNS[2:]], dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("non-finite velocity or covariance")
        velocity = values[:3]
        covariance = values[3:].reshape(15, 15)
        scale = max(1.0, float(np.max(np.abs(covariance))))
        if not np.allclose(covariance, covariance.T, rtol=0, atol=1e-10 * scale):
            raise ValueError("covariance must be symmetric")
        eigenvalues = np.linalg.eigvalsh((covariance + covariance.T) * .5)
        if not np.all(np.isfinite(eigenvalues)):
            raise ValueError("non-finite covariance eigenvalues")
        minimum = float(eigenvalues[0])
        if minimum < -1e-8 * scale:
            raise ValueError("covariance must be positive semidefinite")
        position_diagonal = np.diag(covariance)[3:6]
        velocity_diagonal = np.diag(covariance)[6:9]
        if np.any(position_diagonal <= 0) or np.any(velocity_diagonal <= 0):
            raise ValueError("position and velocity variance must be positive")
        norm = float(np.linalg.norm(velocity))
        if not math.isfinite(norm):
            raise ValueError("non-finite velocity norm")
        pos_variances.extend(float(value) for value in position_diagonal)
        vel_variances.extend(float(value) for value in velocity_diagonal)
        velocity_norms.append(norm)
        min_eigenvalues.append(minimum)
        if image_ns in EVENT_IMAGE_NS:
            event_rows.append({
                "image_ns": image_ns,
                "native_velocity_xyz_mps": velocity.tolist(),
                "native_speed_mps": norm,
                "native_position_variance_xyz_m2": position_diagonal.tolist(),
                "native_velocity_variance_xyz_m2ps2": velocity_diagonal.tolist(),
                "covariance_min_eigenvalue": minimum,
            })
    return {
        "schema": "flydrones-openvins-native-moments-audit-v1",
        "scope": "offline OpenVINS native frame; not MAVLink or PX4 covariance",
        "truth_used": False,
        "states_sha256": _sha(states_csv),
        "moments_sha256": _sha(moments_csv),
        "initialized_frames": len(states),
        "native_error_order": ERROR_ORDER,
        "covariance_structure_valid": True,
        "minimum_covariance_eigenvalue": min(min_eigenvalues),
        "position_variance_m2_range": [min(pos_variances), max(pos_variances)],
        "velocity_variance_m2ps2_range": [min(vel_variances), max(vel_variances)],
        "native_speed_mps_range": [min(velocity_norms), max(velocity_norms)],
        "anomaly_window_rows": event_rows,
        "px4_fusion_eligible": False,
        "reason": "native moments still lack verified frame transform, capture/arrival timing, resets, quality and camera-IMU calibration",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite OpenVINS moments audit")
    report = audit(args.states, args.moments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
