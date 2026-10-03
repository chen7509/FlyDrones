"""Offline diagnostic of OpenVINS feature tracks on a development episode."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np


def _fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"([a-z_][a-z0-9_]*)=([^ ]+)", line))


def parse_trace(text: str) -> list[dict]:
    """Read logging-only post-clean camera tracks, preserving each attempt."""
    attempts: list[dict] = []
    current: dict | None = None
    expected_count = 0
    last_window = -math.inf
    seen_windows: set[tuple[float, int]] = set()

    def finish() -> None:
        if current is not None and len(current["observations"]) != expected_count:
            raise ValueError("track observation count differs from trace header")

    for line in text.splitlines():
        if line.startswith("FD_TRACK_START "):
            finish()
            values = _fields(line)
            if set(values) != {"t", "id", "n"}:
                raise ValueError("malformed track start")
            window = float(values["t"])
            feature_id = int(values["id"])
            expected_count = int(values["n"])
            if (not math.isfinite(window) or window < last_window
                    or feature_id < 0 or expected_count < 2
                    or (window, feature_id) in seen_windows):
                raise ValueError("invalid track start")
            current = {"window_s": window, "feature_id": feature_id,
                       "observations": []}
            attempts.append(current)
            seen_windows.add((window, feature_id))
            last_window = window
        elif line.startswith("FD_TRACK_OBS "):
            values = _fields(line)
            if current is None or set(values) != {"t", "id", "cam", "obs_t", "u", "v"}:
                raise ValueError("orphan or malformed track observation")
            window = float(values["t"])
            feature_id = int(values["id"])
            camera_id = int(values["cam"])
            time = float(values["obs_t"])
            u = float(values["u"])
            v = float(values["v"])
            if (window != current["window_s"] or feature_id != current["feature_id"]
                    or camera_id < 0 or not all(map(math.isfinite, (time, u, v)))
                    or time > window or time < 0):
                raise ValueError("invalid track observation")
            earlier = [item["time_s"] for item in current["observations"]
                       if item["camera_id"] == camera_id]
            if earlier and time <= earlier[-1]:
                raise ValueError("unordered or repeated track observation time")
            current["observations"].append({
                "camera_id": camera_id, "time_s": time,
                "u_norm": u, "v_norm": v,
            })
    finish()
    return attempts


def _unit_quaternion(quaternion: np.ndarray) -> np.ndarray:
    q = np.asarray(quaternion, dtype=float)
    if q.shape != (4,) or not np.all(np.isfinite(q)) or np.linalg.norm(q) < 1e-12:
        raise ValueError("invalid attitude quaternion")
    return q / np.linalg.norm(q)


def _rotation_from_quaternion(quaternion: np.ndarray) -> np.ndarray:
    w, x, y, z = _unit_quaternion(quaternion)
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - w*z), 2 * (x*z + w*y)],
        [2 * (x*y + w*z), 1 - 2 * (x*x + z*z), 2 * (y*z - w*x)],
        [2 * (x*z - w*y), 2 * (y*z + w*x), 1 - 2 * (x*x + y*y)],
    ])


def camera_pose_ned(
    position_ned: np.ndarray, attitude_body_to_ned: np.ndarray,
    rotation_camera_to_body: np.ndarray, translation_camera_in_body: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Camera center and optical-to-NED rotation from EKF2 body pose and fixed extrinsic."""
    p = np.asarray(position_ned, dtype=float)
    r_ci = np.asarray(rotation_camera_to_body, dtype=float)
    t_ci = np.asarray(translation_camera_in_body, dtype=float)
    if (p.shape != (3,) or t_ci.shape != (3,) or r_ci.shape != (3, 3)
            or not all(np.all(np.isfinite(a)) for a in (p, t_ci, r_ci))
            or not np.allclose(r_ci.T @ r_ci, np.eye(3), atol=1e-6)
            or np.linalg.det(r_ci) < 0.999):
        raise ValueError("invalid camera extrinsic or body position")
    r_ni = _rotation_from_quaternion(attitude_body_to_ned)
    return p + r_ni @ t_ci, r_ni @ r_ci


def _sample_bracket(t: float, times: np.ndarray, max_gap_s: float) -> tuple[int, int, float]:
    times = np.asarray(times, dtype=float)
    if (times.ndim != 1 or len(times) == 0 or not np.all(np.isfinite(times))
            or not np.all(np.diff(times) > 0) or not math.isfinite(t)):
        raise ValueError("invalid pose timestamps")
    right = int(np.searchsorted(times, t, side="left"))
    if right < len(times) and times[right] == t:
        return right, right, 0.0
    if right == 0 or right == len(times):
        raise ValueError("pose timestamp outside reference range")
    left = right - 1
    dt = times[right] - times[left]
    if dt > max_gap_s:
        raise ValueError("pose interpolation gap exceeds limit")
    return left, right, (t - times[left]) / dt


def sample_position(
    t: float, times: np.ndarray, positions: np.ndarray,
    xy_valid: np.ndarray, z_valid: np.ndarray,
    xy_reset: np.ndarray, z_reset: np.ndarray,
    max_gap_s: float = .02,
) -> np.ndarray:
    """Interpolate valid EKF2 NED position without crossing an estimator reset."""
    left, right, fraction = _sample_bracket(t, times, max_gap_s)
    pos = np.asarray(positions, dtype=float)
    valid_xy, valid_z = np.asarray(xy_valid), np.asarray(z_valid)
    reset_xy, reset_z = np.asarray(xy_reset), np.asarray(z_reset)
    n = len(times)
    if (pos.shape != (n, 3) or any(a.shape != (n,) for a in
                                 (valid_xy, valid_z, reset_xy, reset_z))):
        raise ValueError("invalid position reference shape")
    if (not np.all(np.isfinite(pos[[left, right]]))
            or not np.all(valid_xy[[left, right]])
            or not np.all(valid_z[[left, right]])):
        raise ValueError("invalid EKF2 position sample")
    if reset_xy[left] != reset_xy[right] or reset_z[left] != reset_z[right]:
        raise ValueError("EKF2 position reset across interpolation")
    return (1 - fraction) * pos[left] + fraction * pos[right]


def sample_attitude(
    t: float, times: np.ndarray, quaternions: np.ndarray,
    reset: np.ndarray, max_gap_s: float = .02,
) -> np.ndarray:
    """Shortest-path quaternion interpolation of PX4 FRD-to-NED attitude."""
    left, right, fraction = _sample_bracket(t, times, max_gap_s)
    quats, resets = np.asarray(quaternions), np.asarray(reset)
    if quats.shape != (len(times), 4) or resets.shape != (len(times),):
        raise ValueError("invalid attitude reference shape")
    if resets[left] != resets[right]:
        raise ValueError("EKF2 attitude reset across interpolation")
    q0, q1 = _unit_quaternion(quats[left]), _unit_quaternion(quats[right])
    dot = float(np.dot(q0, q1))
    if dot < 0:
        q1, dot = -q1, -dot
    if dot > .9995:
        return _unit_quaternion((1 - fraction) * q0 + fraction * q1)
    angle = math.acos(np.clip(dot, -1, 1))
    return (math.sin((1 - fraction) * angle) * q0
            + math.sin(fraction * angle) * q1) / math.sin(angle)


def triangulate_bearings(
    bearings: list[tuple[float, float]],
    poses: list[tuple[np.ndarray, np.ndarray]], focal_px: float,
) -> dict:
    """Unweighted ray least squares; report reprojection, never fit a scale."""
    if len(bearings) < 2 or len(bearings) != len(poses) or focal_px <= 0:
        raise ValueError("invalid triangulation inputs")
    matrix, vector = np.zeros((3, 3)), np.zeros(3)
    for (u, v), (center, rotation) in zip(bearings, poses, strict=True):
        center, rotation = np.asarray(center, float), np.asarray(rotation, float)
        if (center.shape != (3,) or rotation.shape != (3, 3)
                or not np.all(np.isfinite(center)) or not np.all(np.isfinite(rotation))
                or not np.isfinite([u, v]).all()):
            raise ValueError("invalid bearing or camera pose")
        direction = rotation @ np.array([u, v, 1.])
        direction /= np.linalg.norm(direction)
        projector = np.eye(3) - np.outer(direction, direction)
        matrix += projector
        vector += projector @ center
    condition = float(np.linalg.cond(matrix))
    if not math.isfinite(condition) or condition > 1e12:
        raise ValueError("degenerate track geometry")
    point = np.linalg.solve(matrix, vector)
    residual_sq = []
    depths = []
    for (u, v), (center, rotation) in zip(bearings, poses, strict=True):
        local = np.asarray(rotation).T @ (point - center)
        depths.append(float(local[2]))
        if abs(local[2]) < 1e-12:
            raise ValueError("zero reprojection depth")
        residual_sq.append(float(np.sum((focal_px * (local[:2] / local[2]
                                                      - np.array([u, v]))) ** 2)))
    centers = np.array([p[0] for p in poses])
    baseline = float(np.max(np.linalg.norm(centers - centers[-1], axis=1)))
    return {"point_ned_m": point.tolist(), "anchor_depth_m": depths[-1],
            "min_depth_m": min(depths), "condition": condition,
            "baseline_m": baseline,
            "reprojection_rmse_px": math.sqrt(np.mean(residual_sq))}


def _reference_arrays(ulog_path: Path) -> tuple[dict, dict]:
    from pyulog import ULog

    ulog = ULog(str(ulog_path))
    a = ulog.get_dataset("vehicle_attitude").data
    p = ulog.get_dataset("vehicle_local_position").data
    attitude = {
        "times": np.asarray(a["timestamp_sample"], dtype=float) / 1e6,
        "quaternions": np.column_stack([a[f"q[{i}]"] for i in range(4)]),
        "reset": np.asarray(a["quat_reset_counter"]),
    }
    position = {
        "times": np.asarray(p["timestamp_sample"], dtype=float) / 1e6,
        "positions": np.column_stack([p[key] for key in ("x", "y", "z")]),
        "xy_valid": np.asarray(p["xy_valid"]),
        "z_valid": np.asarray(p["z_valid"]),
        "xy_reset": np.asarray(p["xy_reset_counter"]),
        "z_reset": np.asarray(p["z_reset_counter"]),
    }
    return attitude, position


def audit_attempts(
    attempts: list[dict], attitude: dict, position: dict,
    rotation_camera_to_body: np.ndarray,
    translation_camera_in_body: np.ndarray, focal_px: float,
) -> list[dict]:
    """Score every diagnostic candidate; leave reference failures visible."""
    rows = []
    for index, attempt in enumerate(attempts):
        observations = attempt["observations"]
        row = {"attempt_index": index, "window_s": attempt["window_s"],
               "feature_id": attempt["feature_id"], "observation_count": len(observations),
               "first_observation_s": observations[0]["time_s"],
               "last_observation_s": observations[-1]["time_s"],
               "status": "", "reason": "", "baseline_m": "", "anchor_depth_m": "",
               "min_depth_m": "", "condition": "", "reprojection_rmse_px": "",
               "point_n_m": "", "point_e_m": "", "point_d_m": ""}
        poses = []
        for obs in observations:
            if obs["camera_id"] != 0:
                row.update(status="unscored", reason="unsupported_camera_id")
                break
            try:
                t = obs["time_s"]
                p = sample_position(t, position["times"], position["positions"],
                                    position["xy_valid"], position["z_valid"],
                                    position["xy_reset"], position["z_reset"])
                q = sample_attitude(t, attitude["times"], attitude["quaternions"],
                                    attitude["reset"])
                poses.append(camera_pose_ned(p, q, rotation_camera_to_body,
                                            translation_camera_in_body))
            except ValueError as exc:
                row.update(status="unscored", reason=str(exc))
                break
        if not row["status"]:
            try:
                result = triangulate_bearings(
                    [(o["u_norm"], o["v_norm"]) for o in observations], poses, focal_px)
                row.update({key: result[key] for key in
                            ("baseline_m", "anchor_depth_m", "min_depth_m", "condition",
                             "reprojection_rmse_px")})
                row.update(zip(("point_n_m", "point_e_m", "point_d_m"),
                               result["point_ned_m"], strict=True))
                if result["min_depth_m"] <= 0:
                    row.update(status="geometry_rejected", reason="nonpositive_camera_depth")
                else:
                    row.update(status="scored", reason="")
            except ValueError as exc:
                row.update(status="geometry_rejected", reason=str(exc))
        rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _percentiles(rows: list[dict], key: str) -> dict[str, float] | None:
    values = np.array([float(row[key]) for row in rows if row[key] != ""], dtype=float)
    if len(values) == 0:
        return None
    return {"min": float(np.min(values)), "p10": float(np.percentile(values, 10)),
            "median": float(np.median(values)), "p90": float(np.percentile(values, 90)),
            "max": float(np.max(values))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--ulog", type=Path, required=True)
    parser.add_argument("--state-csv", type=Path, required=True)
    parser.add_argument("--original-state-csv", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit("output directory exists; preserve earlier evidence")
    state_hash = _sha256(args.state_csv)
    if state_hash != _sha256(args.original_state_csv):
        raise SystemExit("diagnostic replay changed estimator state CSV")
    config = args.config.read_text(encoding="utf-8")
    if not all(token in config for token in (
        "- [0.0, 0.0, 1.0, 0.12]", "- [1.0, 0.0, 0.0, 0.0]",
        "- [0.0, 1.0, 0.0, -0.002]", "intrinsics: [108.12401050876075",
        "timeshift_cam_imu: 0.0",
    )):
        raise SystemExit("unexpected camera extrinsic/intrinsic/time-offset config")
    trace = args.trace.read_text(encoding="utf-8")
    attempts = parse_trace(trace)
    stage_clean = sum(int(v) for v in re.findall(r"^FD_MSCKF_STAGE .*?\bclean=(\d+)",
                                                       trace, re.MULTILINE))
    if stage_clean != len(attempts) or not attempts:
        raise SystemExit(f"trace count {len(attempts)} != post-clean count {stage_clean}")
    attitude, position = _reference_arrays(args.ulog)
    rotation = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    translation = np.array([.12, 0., -.002])
    rows = audit_attempts(attempts, attitude, position, rotation, translation,
                          focal_px=108.12401050876075)
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(row["status"] for row in rows)
    reasons = Counter(row["reason"] for row in rows if row["reason"])
    scored = [row for row in rows if row["status"] == "scored"]
    scored_three_or_more = [r for r in scored if r["observation_count"] >= 3]
    summary = {
        "schema": "flydrones-openvins-ekf2-track-geometry-audit-v1",
        "reference": "PX4 EKF2 NED pose, offline diagnostic, not ground truth or VIO",
        "input_sha256": {key: _sha256(path) for key, path in {
            "trace": args.trace, "ulog": args.ulog, "state_csv": args.state_csv,
            "camera_config": args.config,
        }.items()},
        "attempt_count": len(attempts), "observation_count": sum(
            len(a["observations"]) for a in attempts), "stage_clean_count": stage_clean,
        "unique_feature_ids": len({a["feature_id"] for a in attempts}),
        "status_counts": dict(counts), "reason_counts": dict(reasons),
        "two_observation_attempts": sum(r["observation_count"] == 2 for r in rows),
        "attitude_sample_count": len(attitude["times"]),
        "position_sample_count": len(position["times"]),
        "scored_depth_m": _percentiles(scored, "anchor_depth_m"),
        "scored_baseline_m": _percentiles(scored, "baseline_m"),
        "scored_condition": _percentiles(scored, "condition"),
        "scored_reprojection_rmse_px": _percentiles(scored, "reprojection_rmse_px"),
        "scored_3plus_reprojection_rmse_px": _percentiles(
            scored_three_or_more, "reprojection_rmse_px"),
        "scored_3plus_count": len(scored_three_or_more),
        "descriptive_threshold_counts_not_equivalent_to_openvins": {
            "condition_le_10000": sum(r["condition"] <= 10000 for r in scored),
            "depth_over_baseline_le_40": sum(
                r["baseline_m"] > 0 and r["anchor_depth_m"] / r["baseline_m"] <= 40
                for r in scored),
            "reprojection_rmse_le_1px": sum(
                r["reprojection_rmse_px"] <= 1 for r in scored),
        },
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
