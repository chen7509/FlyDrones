"""Audit the frozen PX4 IMU export and OpenVINS static initialization."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np

INPUTS = {
    "ulog": ("results/openvins-texture-dev/episode-v1/px4-ulog/log/2026-10-03/01_28_24.ulg",
             "5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55"),
    "imu_csv": ("results/openvins-texture-dev/input-v1/imu.csv",
                "108204af8f88e78ba6b7068f229a0d87bb1ec4039535742b5cd8c1c6ff1e9122"),
    "runner_source": ("results/openvins-offline-1701/runner-v3/offline_probe.cpp",
                      "ed966a7d15a345f85e814e8a0bdbd3f2cfbf0a0f10bcbf789de9cbba2b06e70a"),
    "imu_config": ("results/openvins-texture-dev/config-v2/kalibr_imu_chain.yaml",
                   "6accf2467907df4723419a8f82e772b537b699bbb67a9a9f69097286e1e8b114"),
    "estimator_config": ("results/openvins-texture-dev/config-v2/estimator_config.yaml",
                         "eaa40224f0de2f4c5b0f1d33504d215670544b9cc000252a0e92f404478360e6"),
    "replay_stdout": ("results/openvins-clone-motion/replay-v1/stdout.txt",
                      "13c4b3187d8ec32562e9a394f6db6328f8824d7243dbbfa250c9a12de6fdd6a9"),
    "states": ("results/openvins-clone-motion/replay-v1/states.csv",
               "f0f1966527c80bc49a5d219053a3e9c282aeb04eab7439dccd0fe3d265f8740f"),
}


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_imu_rows(ulog: dict, csv_rows: list[dict]) -> dict:
    """Check every PX4 sensor_combined sample against the offline CSV."""
    stamps = np.asarray(ulog["timestamp"], dtype=np.int64)
    if len(stamps) != len(csv_rows) or len(stamps) < 2:
        raise ValueError("IMU row count mismatch")
    if np.any(stamps <= 0) or np.any(np.diff(stamps) <= 0):
        raise ValueError("IMU timestamps invalid")
    exported = np.array([int(row["timestamp_us"]) for row in csv_rows], dtype=np.int64)
    if not np.array_equal(stamps, exported):
        raise ValueError("IMU timestamp mismatch")
    relative = np.asarray(ulog["accelerometer_timestamp_relative"], dtype=np.int64)
    if len(relative) != len(stamps) or np.any(relative != 0):
        raise ValueError("accelerometer relative timestamp not zero")
    for key in ("gyro_integral_dt", "accelerometer_integral_dt"):
        periods = np.asarray(ulog[key], dtype=np.int64)
        if len(periods) != len(stamps) or np.any(periods <= 0):
            raise ValueError(f"invalid {key}")
    clipped = np.asarray(ulog["gyro_clipping"], dtype=np.int64) | np.asarray(
        ulog["accelerometer_clipping"], dtype=np.int64)
    if len(clipped) != len(stamps):
        raise ValueError("IMU clipping array length mismatch")
    axes = []
    for source, field in (("gyro_rad", "g"), ("accelerometer_m_s2", "a")):
        for index, letter in enumerate("xyz"):
            raw = np.asarray(ulog[f"{source}[{index}]"], dtype=np.float64)
            saved = np.array([float(row[field + letter]) for row in csv_rows])
            if (len(raw) != len(stamps) or not np.all(np.isfinite(raw))
                    or not np.all(np.isfinite(saved)) or not np.array_equal(raw, saved)):
                raise ValueError(f"IMU value mismatch: {field}{letter}")
            axes.append(raw)
    gyro = np.stack(axes[:3], axis=1)
    accel = np.stack(axes[3:], axis=1)
    return {
        "sample_count": int(len(stamps)),
        "first_timestamp_us": int(stamps[0]), "last_timestamp_us": int(stamps[-1]),
        "median_interval_us": float(np.median(np.diff(stamps))),
        "max_interval_us": int(np.max(np.diff(stamps))),
        "accelerometer_relative_offset_nonzero": int(np.count_nonzero(relative)),
        "any_clipped_samples": int(np.count_nonzero(clipped)),
        "median_gyro_rad_s": [float(x) for x in np.median(gyro, axis=0)],
        "median_accel_m_s2": [float(x) for x in np.median(accel, axis=0)],
        "median_accel_norm_m_s2": float(np.median(np.linalg.norm(accel, axis=1))),
    }


def extract_static_init(log_text: str, states: list[dict]) -> dict:
    """Extract the single logged static initialization and first state time."""
    if log_text.count("USING STATIC INITIALIZER METHOD!") != 1:
        raise ValueError("expected one static initialization method record")
    if log_text.count("successful initialization in") != 1:
        raise ValueError("expected one successful initialization record")
    initialized = [row for row in states if row["initialized"] == "1"]
    if not initialized or not states or states[0]["initialized"] != "0":
        raise ValueError("missing pre-init or initialized state")
    first = initialized[0]
    if int(first["image_ns"]) <= 0 or any(
            row["initialized"] != "1" for row in states[states.index(first):]):
        raise ValueError("invalid initialized state sequence")

    def vector(label: str, size: int) -> list[float]:
        lines = re.findall(rf"\[init\]: {re.escape(label)} = ([^\r\n]+)", log_text)
        if len(lines) != 1:
            raise ValueError(f"missing or duplicated initialization {label}")
        values = [float(item.strip()) for item in lines[0].split(",")]
        if len(values) != size or not np.all(np.isfinite(values)):
            raise ValueError(f"invalid initialization {label}")
        return values

    return {
        "method": "static", "first_initialized_s": int(first["image_ns"]) * 1e-9,
        "initial_orientation_xyzw": vector("orientation", 4),
        "bias_gyro_rad_s": vector("bias gyro", 3),
        "initial_velocity_m_s": vector("velocity", 3),
        "bias_accel_m_s2": vector("bias accel", 3),
    }


def score_ekf_init_velocity(
    data: dict, start_s: float, init_s: float,
) -> tuple[list[dict], dict]:
    """Keep every valid EKF2 velocity sample in the pre-init interval."""
    times = np.asarray(data["timestamp"], dtype=np.int64) * 1e-6
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("EKF2 velocity timestamps invalid")
    mask = (times >= start_s - 1e-9) & (times <= init_s + 1e-9)
    selected = np.flatnonzero(mask)
    if (len(selected) < 2 or times[selected[0]] - start_s > .02
            or init_s - times[selected[-1]] > .02
            or np.max(np.diff(times[selected])) > .02):
        raise ValueError("EKF2 velocity window gap exceeds 20 ms")
    for key in ("v_xy_valid", "v_z_valid"):
        values = np.asarray(data[key])[selected]
        if len(values) != len(selected) or not np.all(values):
            raise ValueError("invalid EKF2 velocity in initialization window")
    for key in ("vxy_reset_counter", "vz_reset_counter"):
        values = np.asarray(data[key])[selected]
        if len(values) != len(selected) or np.any(values != values[0]):
            raise ValueError("EKF2 velocity reset in initialization window")
    velocity = np.column_stack([np.asarray(data[key], dtype=float)[selected]
                                for key in ("vx", "vy", "vz")])
    if not np.all(np.isfinite(velocity)):
        raise ValueError("invalid EKF2 velocity in initialization window")
    speeds = np.linalg.norm(velocity, axis=1)
    rows = [
        {"timestamp_us": int(data["timestamp"][index]),
         "vx_m_s": float(velocity[offset, 0]),
         "vy_m_s": float(velocity[offset, 1]),
         "vz_m_s": float(velocity[offset, 2]),
         "speed_m_s": float(speeds[offset])}
        for offset, index in enumerate(selected)
    ]
    return rows, {
        "sample_count": len(rows),
        "first_sample_s": float(times[selected[0]]),
        "last_sample_s": float(times[selected[-1]]),
        "max_sample_gap_ms": float(np.max(np.diff(times[selected])) * 1e3),
        "all_velocity_flags_valid": True,
        "vxy_reset_counter": int(data["vxy_reset_counter"][selected[0]]),
        "vz_reset_counter": int(data["vz_reset_counter"][selected[0]]),
        "median_speed_m_s": float(np.median(speeds)),
        "p90_speed_m_s": float(np.percentile(speeds, 90)),
        "max_speed_m_s": float(np.max(speeds)),
        "speed_at_first_initialized_sample_m_s": float(speeds[-1]),
        "reference_moving_over_0_1_mps": bool(np.median(speeds) > .1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit("output directory exists; preserve earlier evidence")
    root = Path(__file__).resolve().parents[2]
    paths = {name: root / rel for name, (rel, _) in INPUTS.items()}
    for name, (rel, expected) in INPUTS.items():
        if _sha256(root / rel) != expected:
            raise SystemExit(f"frozen {name} SHA-256 mismatch")
    from pyulog import ULog

    log = ULog(str(paths["ulog"]))
    with paths["imu_csv"].open(newline="", encoding="utf-8") as stream:
        imu_rows = list(csv.DictReader(stream))
    imu = compare_imu_rows(log.get_dataset("sensor_combined").data, imu_rows)
    with paths["states"].open(newline="", encoding="utf-8") as stream:
        states = list(csv.DictReader(stream))
    init = extract_static_init(paths["replay_stdout"].read_text(encoding="utf-8"), states)
    start_s = init["first_initialized_s"] - 2.0
    velocity_rows, velocity = score_ekf_init_velocity(
        log.get_dataset("vehicle_local_position").data, start_s,
        init["first_initialized_s"])
    summary = {
        "schema": "flydrones-openvins-imu-init-audit-v1",
        "scope": "frozen development PX4 IMU export and offline EKF2 reference; no VIO pass",
        "input_sha256": {name: expected for name, (_, expected) in INPUTS.items()},
        "imu_export": imu, "openvins_initialization": init,
        "ekf2_reference_window_start_s": start_s,
        "ekf2_reference_velocity": velocity,
    }
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "velocity_window.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(velocity_rows[0]))
        writer.writeheader()
        writer.writerows(velocity_rows)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
