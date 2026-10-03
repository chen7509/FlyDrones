"""Compare pinned OpenVINS camera clone motion to offline PX4 EKF2 motion."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from tools.benchmark.audit_openvins_track_geometry import (
    _fields,
    _reference_arrays,
    _sha256,
    assert_config_digest,
    camera_pose_ned,
    parse_trace,
    sample_attitude,
    sample_position,
    triangulate_bearings,
    validate_trace_stages,
)


def parse_clone_trace(text: str) -> list[dict]:
    """Parse one logged clone pose per post-clean observation, preserving attempts."""
    records = []
    seen: set[tuple[float, int, int, float]] = set()
    required = {"t", "id", "cam", "obs_t"}
    required.update(f"r{i}{j}" for i in range(3) for j in range(3))
    required.update(f"p{i}" for i in range(3))
    for line in text.splitlines():
        if not line.startswith("FD_CLONE_POSE "):
            continue
        values = _fields(line)
        if set(values) != required:
            raise ValueError("malformed clone pose record")
        window = float(values["t"])
        feature_id = int(values["id"])
        camera_id = int(values["cam"])
        obs_time = float(values["obs_t"])
        key = (window, feature_id, camera_id, obs_time)
        if key in seen:
            raise ValueError("duplicate clone pose observation")
        if (not all(math.isfinite(x) for x in (window, obs_time))
                or feature_id < 0 or camera_id < 0 or obs_time < 0
                or obs_time > window):
            raise ValueError("invalid clone pose key")
        r_global_to_cam = np.array([[float(values[f"r{i}{j}"]) for j in range(3)]
                                    for i in range(3)])
        center = np.array([float(values[f"p{i}"]) for i in range(3)])
        if not np.all(np.isfinite(center)) or not np.all(np.isfinite(r_global_to_cam)):
            raise ValueError("nonfinite clone pose")
        if (not np.allclose(r_global_to_cam @ r_global_to_cam.T, np.eye(3), atol=1e-5)
                or not np.isclose(np.linalg.det(r_global_to_cam), 1.0, atol=1e-5)):
            raise ValueError("invalid clone rotation")
        records.append({"window_s": window, "feature_id": feature_id,
                        "camera_id": camera_id, "time_s": obs_time,
                        "center_global_m": center,
                        "rotation_cam_to_global": r_global_to_cam.T})
        seen.add(key)
    return records


def match_clone_poses(
    attempts: list[dict], records: list[dict],
) -> list[list[tuple[np.ndarray, np.ndarray]]]:
    """Require an exact one-to-one mapping from tracks to clone pose logs."""
    by_key = {(r["window_s"], r["feature_id"], r["camera_id"], r["time_s"]): r
              for r in records}
    if len(by_key) != len(records):
        raise ValueError("duplicate clone pose key")
    matched = []
    for attempt in attempts:
        group = []
        for obs in attempt["observations"]:
            key = (attempt["window_s"], attempt["feature_id"],
                   obs["camera_id"], obs["time_s"])
            if key not in by_key:
                raise ValueError("missing clone pose for track observation")
            record = by_key.pop(key)
            group.append((record["center_global_m"], record["rotation_cam_to_global"]))
        matched.append(group)
    if by_key:
        raise ValueError("unexpected clone pose record")
    return matched


def compare_relative_motion(
    clone_poses: list[tuple[np.ndarray, np.ndarray]],
    reference_poses: list[tuple[np.ndarray, np.ndarray]],
) -> dict:
    """Compare first-to-last camera motion in the first camera frame, no alignment."""
    if len(clone_poses) < 2 or len(clone_poses) != len(reference_poses):
        raise ValueError("relative motion requires matching tracks of at least two poses")
    c0, rc0 = clone_poses[0]
    c1, rc1 = clone_poses[-1]
    e0, re0 = reference_poses[0]
    e1, re1 = reference_poses[-1]
    clone_relative_rotation = rc0.T @ rc1
    ekf_relative_rotation = re0.T @ re1
    residual_rotation = clone_relative_rotation @ ekf_relative_rotation.T
    rotation_deg = math.degrees(math.acos(float(np.clip(
        (np.trace(residual_rotation) - 1) / 2, -1, 1))))
    clone_displacement = rc0.T @ (c1 - c0)
    ekf_displacement = re0.T @ (e1 - e0)
    clone_baseline = float(np.linalg.norm(clone_displacement))
    ekf_baseline = float(np.linalg.norm(ekf_displacement))
    direction_error = None
    ratio = None
    if clone_baseline > 1e-6 and ekf_baseline > 1e-6:
        cosine = float(np.clip(np.dot(clone_displacement, ekf_displacement)
                               / (clone_baseline * ekf_baseline), -1, 1))
        direction_error = math.degrees(math.acos(cosine))
        ratio = clone_baseline / ekf_baseline
    return {"rotation_error_deg": rotation_deg,
            "translation_direction_error_deg": direction_error,
            "baseline_ratio": ratio, "clone_baseline_m": clone_baseline,
            "ekf_baseline_m": ekf_baseline}


def score_attempt_geometry(
    attempt: dict,
    clone_poses: list[tuple[np.ndarray, np.ndarray]],
    reference_poses: list[tuple[np.ndarray, np.ndarray]],
    focal_px: float,
) -> dict:
    """Score the same bearings under two pose sources without dropping failures."""
    bearings = [(o["u_norm"], o["v_norm"]) for o in attempt["observations"]]
    if len(bearings) != len(clone_poses) or len(bearings) != len(reference_poses):
        raise ValueError("pose/observation count mismatch")
    row = compare_relative_motion(clone_poses, reference_poses)
    for label, poses in (("clone", clone_poses), ("reference", reference_poses)):
        try:
            result = triangulate_bearings(bearings, poses, focal_px)
            row[f"{label}_status"] = (
                "positive_depth" if result["min_depth_m"] > 0 else "nonpositive_depth")
            row[f"{label}_reason"] = "" if result["min_depth_m"] > 0 else "nonpositive_camera_depth"
            for key in ("anchor_depth_m", "min_depth_m", "condition",
                        "baseline_m", "reprojection_rmse_px"):
                row[f"{label}_{key}"] = result[key]
        except ValueError as exc:
            row[f"{label}_status"] = "geometry_rejected"
            row[f"{label}_reason"] = str(exc)
            for key in ("anchor_depth_m", "min_depth_m", "condition",
                        "baseline_m", "reprojection_rmse_px"):
                row[f"{label}_{key}"] = None
    return row


def _reference_poses(attempt: dict, attitude: dict, position: dict) -> list:
    rotation = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    translation = np.array([.12, 0., -.002])
    poses = []
    for obs in attempt["observations"]:
        if obs["camera_id"] != 0:
            raise ValueError("unsupported camera id")
        t = obs["time_s"]
        p = sample_position(t, position["times"], position["positions"],
                            position["xy_valid"], position["z_valid"],
                            position["xy_reset"], position["z_reset"])
        q = sample_attitude(t, attitude["times"], attitude["quaternions"],
                            attitude["reset"])
        poses.append(camera_pose_ned(p, q, rotation, translation))
    return poses


def _percentiles(values: list[float]) -> dict | None:
    if not values:
        return None
    return {key: float(value) for key, value in zip(
        ("min", "p10", "median", "p90", "max"),
        np.percentile(values, (0, 10, 50, 90, 100)), strict=True)}


def _distribution(rows: list[dict]) -> dict:
    fields = ("rotation_error_deg", "translation_direction_error_deg",
              "baseline_ratio", "clone_baseline_m", "ekf_baseline_m",
              "clone_anchor_depth_m", "clone_reprojection_rmse_px")
    return {field: _percentiles([float(row[field]) for row in rows
                                 if row.get(field) is not None]) for field in fields}


def validate_frozen_trace_digest(path: Path) -> None:
    """Reject a changed replay, including changed numeric clone poses."""
    if _sha256(path) != "d330736bc6c4f9236edc33389584cea01452af3c524ac331aa144fae6699bf8f":
        raise SystemExit("OpenVINS clone trace differs from frozen replay")


def validate_prior_reference(scored: dict, old: dict) -> None:
    """Require the independently recomputed reference geometry to match every prior metric."""
    expected_status = ("positive_depth" if old["status"] == "scored" else
                       "nonpositive_depth" if old["reason"] == "nonpositive_camera_depth"
                       else "geometry_rejected")
    if scored["reference_status"] != expected_status:
        raise RuntimeError("EKF2 geometry no longer matches the frozen prior CSV")
    if scored["reference_reason"] != old["reason"]:
        raise RuntimeError("EKF2 geometry no longer matches the frozen prior CSV")
    for key in ("baseline_m", "anchor_depth_m", "min_depth_m", "condition",
                "reprojection_rmse_px"):
        prior = old[key]
        current = scored[f"reference_{key}"]
        if not prior:
            if current is not None:
                raise RuntimeError("EKF2 geometry no longer matches the frozen prior CSV")
        elif current is None or not np.isclose(current, float(prior), rtol=1e-9, atol=1e-9):
            raise RuntimeError("EKF2 geometry no longer matches the frozen prior CSV")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--ulog", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-csv", type=Path, required=True)
    parser.add_argument("--original-state-csv", type=Path, required=True)
    parser.add_argument("--prior-attempts-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit("output directory exists; preserve earlier evidence")
    expected_state = "f0f1966527c80bc49a5d219053a3e9c282aeb04eab7439dccd0fe3d265f8740f"
    if _sha256(args.state_csv) != expected_state or _sha256(args.original_state_csv) != expected_state:
        raise SystemExit("OpenVINS state CSV changed after logging-only instrumentation")
    assert_config_digest(args.config.read_bytes(),
                         "120fb34ae45fec5d0c3cf838d053e7b0b79808c64b3fdb89923c4df09ec1a0cf")
    if _sha256(args.ulog) != "5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55":
        raise SystemExit("PX4 ULog differs from frozen development capture")
    if _sha256(args.prior_attempts_csv) != "0b41d03bb64fbf2100aa31012ec42308fc452be746e26062412ed0782397d980":
        raise SystemExit("prior EKF2 geometry CSV differs from frozen audit")
    validate_frozen_trace_digest(args.trace)
    trace = args.trace.read_text(encoding="utf-8")
    attempts = parse_trace(trace)
    clean = validate_trace_stages(trace, attempts)
    records = parse_clone_trace(trace)
    clone_groups = match_clone_poses(attempts, records)
    if clean != 183 or len(records) != 1001:
        raise SystemExit("unexpected frozen candidate or clone observation count")
    with args.prior_attempts_csv.open(newline="", encoding="utf-8") as stream:
        prior = list(csv.DictReader(stream))
    if len(prior) != len(attempts):
        raise SystemExit("prior geometry row count mismatch")
    attitude, position = _reference_arrays(args.ulog)
    rows = []
    for index, (attempt, clones, old) in enumerate(zip(attempts, clone_groups, prior, strict=True)):
        if (int(old["attempt_index"]) != index
                or int(old["feature_id"]) != attempt["feature_id"]
                or float(old["window_s"]) != attempt["window_s"]
                or int(old["observation_count"]) != len(attempt["observations"])):
            raise SystemExit("prior EKF2 geometry attempt order differs")
        row = {"attempt_index": index, "window_s": attempt["window_s"],
               "feature_id": attempt["feature_id"],
               "observation_count": len(attempt["observations"])}
        try:
            reference = _reference_poses(attempt, attitude, position)
        except ValueError as exc:
            row.update(reference_status="unscored", reference_reason=str(exc),
                       clone_status="unscored", clone_reason="reference unavailable")
        else:
            scored = score_attempt_geometry(
                attempt, clones, reference, focal_px=108.12401050876075)
            validate_prior_reference(scored, old)
            row.update(scored)
        rows.append(row)
    keys = list(dict.fromkeys(key for row in rows for key in row))
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    windows = [a["window_s"] for a in attempts]
    midpoint = (min(windows) + max(windows)) / 2
    summary = {
        "schema": "flydrones-openvins-clone-motion-audit-v1",
        "scope": "development data, logging-only OpenVINS clones vs offline PX4 EKF2 reference",
        "attempt_count": len(attempts), "observation_count": len(records),
        "clone_status_counts": dict(Counter(row["clone_status"] for row in rows)),
        "reference_status_counts": dict(Counter(row["reference_status"] for row in rows)),
        "unscored_reasons": dict(Counter(row.get("reference_reason") for row in rows
                                        if row["reference_status"] == "unscored")),
        "distribution_all": _distribution(rows),
        "temporal_split_s": midpoint,
        "distribution_early": _distribution([r for r in rows if r["window_s"] < midpoint]),
        "distribution_late": _distribution([r for r in rows if r["window_s"] >= midpoint]),
        "input_sha256": {name: _sha256(path) for name, path in {
            "trace": args.trace, "ulog": args.ulog, "camera_config": args.config,
            "states": args.state_csv, "prior_attempts": args.prior_attempts_csv,
        }.items()},
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
