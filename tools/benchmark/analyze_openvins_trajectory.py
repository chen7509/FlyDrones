#!/usr/bin/env python3
"""Score offline VIO output against held-out Gazebo truth after estimation.

Truth is read only by this evaluator; the estimator never receives it.
Rigid alignment removes the arbitrary VIO world frame but never rescales a
metric visual-inertial trajectory. This is development evidence, not flight QA.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def analyze(states_csv: Path, episode_result: Path,
            upstream_log: Path | None = None) -> dict:
    with states_csv.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or set(rows[0]) != {"image_ns", "initialized", "state_timestamp_s",
                                   "qx", "qy", "qz", "qw", "px", "py", "pz"}:
        raise ValueError("invalid OpenVINS state CSV")
    episode = json.loads(episode_result.read_text(encoding="utf-8"))
    if episode.get("odometry_source") != "gazebo_model_truth":
        raise ValueError("expected explicitly labeled Gazebo scoring truth")
    path = episode["path"]
    truth_t = np.array([item["sim_ns"] * 1e-9 for item in path], dtype=float)
    truth_p = np.array([item["position"] for item in path], dtype=float)
    if len(truth_t) < 3 or np.any(np.diff(truth_t) <= 0) or not np.all(np.isfinite(truth_p)):
        raise ValueError("incomplete or unordered scoring truth")
    selected = [row for row in rows if row["initialized"] == "1"]
    result = {
        "schema": "flydrones-openvins-trajectory-audit-v1",
        "scope": "offline development scoring only; Gazebo truth is never VIO input",
        "states_sha256": _sha(states_csv),
        "episode_result_sha256": _sha(episode_result),
        "total_image_frames": len(rows),
        "initialized_frames": len(selected),
        "status": "no_initialization" if not selected else "trajectory_present",
        "alignment_scale": 1.0,
        "aligned_ate_rmse_m": None,
    }
    if upstream_log is not None:
        log = upstream_log.read_text(encoding="utf-8", errors="replace")
        msckf = [int(count) for count in re.findall(r"MSCKF update \((\d+) feats\)", log)]
        slam = [int(count) for count in re.findall(r"SLAM update \((\d+) feats\)", log)]
        result.update({
            "upstream_log_sha256": _sha(upstream_log),
            "msckf_logged_frames": len(msckf),
            "msckf_nonzero_update_frames": sum(count > 0 for count in msckf),
            "msckf_feature_total": sum(msckf),
            "slam_logged_frames": len(slam),
            "slam_landmark_max": max(slam, default=0),
        })
        if selected and len(msckf) == len(selected) and len(slam) == len(selected):
            if not any(msckf) and not any(slam):
                result["status"] = "inertial_only_after_init"
            elif any(msckf) or any(slam):
                result["status"] = "visual_updates_present_unvalidated"
    if not selected:
        return result
    time = np.array([float(row["state_timestamp_s"]) for row in selected])
    image_time = np.array([int(row["image_ns"]) * 1e-9 for row in selected])
    position = np.array([[float(row[key]) for key in ("px", "py", "pz")]
                         for row in selected])
    quaternion = np.array([[float(row[key]) for key in ("qx", "qy", "qz", "qw")]
                           for row in selected])
    if (np.any(np.diff(time) <= 0) or not np.all(np.isfinite(position))
            or not np.all(np.isfinite(quaternion))):
        raise ValueError("non-finite or unordered initialized state")
    speed = np.linalg.norm(np.diff(position, axis=0), axis=1) / np.diff(time)
    result.update({
        "first_state_s": float(time[0]),
        "last_state_s": float(time[-1]),
        "max_image_state_time_gap_s": float(np.max(np.abs(image_time - time))),
        "vio_displacement_m": float(np.linalg.norm(position[-1] - position[0])),
        "vio_speed_p95_mps": float(np.quantile(speed, .95)),
        "vio_speed_max_mps": float(np.max(speed)),
        "quaternion_norm_min": float(np.min(np.linalg.norm(quaternion, axis=1))),
        "quaternion_norm_max": float(np.max(np.linalg.norm(quaternion, axis=1))),
    })
    inside = (time >= truth_t[0]) & (time <= truth_t[-1])
    if int(np.sum(inside)) < 3:
        result["truth_overlap_frames"] = int(np.sum(inside))
        return result
    sample_time = time[inside]
    estimate = position[inside]
    truth = np.column_stack([np.interp(sample_time, truth_t, truth_p[:, axis])
                             for axis in range(3)])
    estimate_center = estimate.mean(axis=0)
    truth_center = truth.mean(axis=0)
    u, _, vt = np.linalg.svd((estimate - estimate_center).T @ (truth - truth_center))
    flip = np.eye(3)
    flip[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ flip @ vt
    translation = truth_center - estimate_center @ rotation
    aligned = estimate @ rotation + translation
    errors = np.linalg.norm(aligned - truth, axis=1)
    truth_speed = np.linalg.norm(np.diff(truth, axis=0), axis=1) / np.diff(sample_time)
    result.update({
        "truth_overlap_frames": len(sample_time),
        "truth_overlap_first_s": float(sample_time[0]),
        "truth_overlap_last_s": float(sample_time[-1]),
        "truth_displacement_m": float(np.linalg.norm(truth[-1] - truth[0])),
        "truth_speed_p95_mps": float(np.quantile(truth_speed, .95)),
        "aligned_ate_rmse_m": float(np.sqrt(np.mean(errors ** 2))),
        "aligned_ate_p95_m": float(np.quantile(errors, .95)),
        "aligned_endpoint_error_m": float(errors[-1]),
        "alignment_rotation_row_major": rotation.tolist(),
        "alignment_translation_m": translation.tolist(),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--episode-result", type=Path, required=True)
    parser.add_argument("--upstream-log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite VIO trajectory audit")
    report = analyze(args.states, args.episode_result, args.upstream_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
