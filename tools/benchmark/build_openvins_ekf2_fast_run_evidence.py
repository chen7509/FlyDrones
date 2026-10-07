"""Build one offline fast-prediction covariance run from retained physical evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_ekf2_fast_contract import transform_fast12
from tools.benchmark.trajectory_gauge_contract import YawTranslationGauge, _truth_state, select_origin, trajectory_contract


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid JSON object: " + str(path))
    return value


def _jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        raise ValueError("unterminated JSONL: " + str(path))
    rows = [json.loads(line) for line in text.splitlines() if line]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid JSONL row: " + str(path))
    return rows


def build_fast_run(capture: Path, completion: Path) -> dict:
    capture = Path(capture).resolve(strict=True)
    completed = _json(Path(completion).resolve(strict=True))
    result = _json(capture / "result.json")
    states = _jsonl(capture / "shadow" / "states.jsonl")
    fast = _jsonl(capture / "shadow" / "fast.jsonl")
    truth_rows = _jsonl(capture / "native-reference.jsonl")
    anchor = _json(capture / "readiness-anchor.json")
    motion = _json(capture / "motion-profile.json")
    contract = trajectory_contract(
        anchor_ns=anchor["anchor_ns"],
        total_duration_ns=motion["total_duration_ns"],
        lateral_start_offset_ns=motion["lateral_start_after_anchor_ns"],
    )
    origin = select_origin(states, contract)
    if origin is None:
        raise ValueError("fast run lacks estimator origin")
    truth = {
        row["post_ns"]: {
            **row,
            "sim_ns": row["post_ns"],
            "truth_for_fixture_audit_only": row["truth_for_abort_audit_only"],
        }
        for row in truth_rows
    }
    gauge = YawTranslationGauge(states[origin["index"]]["imu_state"], truth[origin["sample_ns"]])
    samples = []
    for row in fast:
        if not row.get("success") or not row.get("public_initialized") or row.get("target_ns", 0) < origin["sample_ns"]:
            continue
        target = row["target_ns"]
        scored_truth = truth.get(target)
        if scored_truth is None:
            raise ValueError("fast target lacks exact truth")
        transformed = transform_fast12(row["state13"], row["covariance12"])
        state = np.asarray(row["state13"], dtype=float)
        native_rotation = Rotation.from_quat(state[:4]).as_matrix()
        truth_rotation, truth_position, truth_velocity = _truth_state(scored_truth)
        aligned_position = gauge.rotation @ (state[4:7] - gauge.native_origin) + gauge.truth_origin
        aligned_rotation = gauge.rotation @ native_rotation
        attitude_error = Rotation.from_matrix(truth_rotation.T @ aligned_rotation).as_rotvec()
        position_error = aligned_position - truth_position
        velocity_body_error = state[7:10] - truth_rotation.T @ truth_velocity
        visual_age = target - row["last_camera_ns"] if row["last_camera_ns"] is not None else None
        boundary_age = row["available_imu_ns"] - target
        if visual_age is None:
            raise ValueError("public fast target lacks camera")
        samples.append(
            {
                "target_ns": target,
                "public_initialized": True,
                "visual_age_ns": visual_age,
                "imu_boundary_age_ns": boundary_age,
                "error_attitude_position_velocity": np.concatenate(
                    (attitude_error, position_error, velocity_body_error)
                ).tolist(),
                "bounded_covariance12": transformed["bounded_covariance12"],
                "fusion_eligible": False,
            }
        )
    trajectory = _json(Path(completion).parent / "trajectory-audit.json")
    source_health = bool(
        result.get("status") == "capture_completed"
        and result.get("errors") == []
        and result.get("readiness", {}).get("failure") is None
        and result.get("runtime_binding", {}).get("runtime_mapping_coverage_verified") is True
        and completed.get("command_returncode") == 0
        and completed.get("launcher_returncode") == 0
        and completed.get("resources_after") == []
    )
    native_health = bool(
        result.get("native", {}).get("exit") == 0
        and result.get("native", {}).get("failure") is None
        and samples
        and len(fast) == 1250
        and all(row.get("filter_unchanged") is True for row in fast)
    )
    trajectory_qualified = bool(
        trajectory.get("diagnostic_screens_pass")
        and trajectory.get("public_coverage_qualified")
        and trajectory.get("capture_complete")
    )
    return {
        "status": result.get("status"),
        "source_health_qualified": source_health,
        "native_health_qualified": native_health,
        "trajectory_accuracy_qualified": trajectory_qualified,
        "samples": samples,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--completion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError("refusing to overwrite fast run evidence")
    result = build_fast_run(args.capture, args.completion)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(result["samples"]), **{k: v for k, v in result.items() if k != "samples"}}, indent=2))
    return 0 if all(result[key] for key in ("source_health_qualified", "native_health_qualified", "trajectory_accuracy_qualified")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
