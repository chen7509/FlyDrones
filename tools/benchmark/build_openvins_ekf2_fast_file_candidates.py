"""Build qualified 50 Hz file-only EKF2 candidates from retained fast states."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.benchmark.openvins_ekf2_fast_contract import fast_sample_timing_qualified, transform_fast12
from tools.benchmark.openvins_ekf2_transform import PROFILE


def _json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid JSON object: " + str(path))
    return value


def _jsonl(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        raise ValueError("unterminated JSONL: " + str(path))
    rows = [json.loads(line) for line in text.splitlines() if line]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid JSONL row: " + str(path))
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _upper_triangle(matrix: np.ndarray) -> list[float]:
    return matrix[np.triu_indices(6)].tolist()


def _velocity_upper(matrix3: np.ndarray) -> list[float | None]:
    output: list[float | None] = [None] * 21
    for index, (row, column) in enumerate(zip(*np.triu_indices(6), strict=True)):
        if row < 3 and column < 3:
            output[index] = float(matrix3[row, column])
    return output


def compose_fast_file_candidate(fast_row: object, camera_record: object) -> dict:
    if not isinstance(fast_row, dict) or not isinstance(camera_record, dict):
        raise ValueError("invalid fast candidate inputs")
    composition = camera_record.get("composition")
    if not isinstance(composition, dict) or composition.get("status") != "candidate":
        raise ValueError("fast candidate lacks authoritative camera health")
    health = composition.get("health")
    candidate = composition.get("candidate")
    if (
        not isinstance(health, dict)
        or health.get("quality") != 1
        or health.get("failed_latched") is not False
        or health.get("covariance_sim_domain_qualified") is not True
        or health.get("fusion_eligible") is not False
        or not isinstance(candidate, dict)
        or candidate.get("fusion_eligible") is not False
    ):
        raise ValueError("fast candidate health is not authoritative and positive")
    target_ns = fast_row.get("target_ns")
    last_camera_ns = fast_row.get("last_camera_ns")
    available_imu_ns = fast_row.get("available_imu_ns")
    if (
        fast_row.get("success") is not True
        or fast_row.get("public_initialized") is not True
        or fast_row.get("fusion_eligible") is not False
        or fast_row.get("quality") is not None
        or fast_row.get("reset_counter") is not None
        or camera_record.get("timing", {}).get("capture_sample_ns") != last_camera_ns
        or not fast_sample_timing_qualified(target_ns, last_camera_ns, available_imu_ns)
    ):
        raise ValueError("invalid fast candidate timing/health")
    geometry = transform_fast12(fast_row.get("state13"), fast_row.get("covariance12"))
    covariance = np.asarray(geometry["covariance9x9"], dtype=float)
    fields = {
        "time_usec": target_ns // 1000,
        "frame_id": 20,
        "child_frame_id": 12,
        "x": geometry["position_local_frd"][0],
        "y": geometry["position_local_frd"][1],
        "z": geometry["position_local_frd"][2],
        "q": geometry["q_body_to_local_frd_wxyz"],
        "vx": geometry["velocity_body_frd"][0],
        "vy": geometry["velocity_body_frd"][1],
        "vz": geometry["velocity_body_frd"][2],
        "rollspeed": None,
        "pitchspeed": None,
        "yawspeed": None,
        "pose_covariance": _upper_triangle(covariance[:6, :6]),
        "velocity_covariance": _velocity_upper(covariance[6:9, 6:9]),
        "reset_counter": health["reset_counter"],
        "estimator_type": 3,
        "quality": 1,
    }
    return {
        "schema": "openvins-ekf2-fast-file-candidate-v1",
        "frame_profile": PROFILE,
        "native_covariance_profile": geometry["native_covariance_profile"],
        "target_ns": target_ns,
        "last_camera_ns": last_camera_ns,
        "available_imu_ns": available_imu_ns,
        "visual_age_ns": target_ns - last_camera_ns,
        "imu_boundary_age_ns": available_imu_ns - target_ns,
        "fields": fields,
        "covariance9x9": geometry["covariance9x9"],
        "identities": candidate["identities"],
        "authoritative_camera_health": health,
        "network_odometry": False,
        "fusion_eligible": False,
    }


def build(output: Path, *, fast_rows: Path, camera_candidates: Path, cohort_audit: Path) -> dict:
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    audit = _json(cohort_audit)
    if (
        audit.get("schema") != "openvins-ekf2-fast-cohort-audit-v1"
        or audit.get("propagated_covariance_sim_domain_qualified") is not True
        or audit.get("hardware_covariance_calibrated") is not False
        or audit.get("fusion_eligible") is not False
    ):
        raise ValueError("fast covariance cohort is not qualified")
    fast = _jsonl(fast_rows)
    camera = _jsonl(camera_candidates)
    health_by_sample = {
        row["timing"]["capture_sample_ns"]: row
        for row in camera
        if row.get("composition", {}).get("status") == "candidate"
    }
    selected = [row for row in fast if row.get("success") is True and row.get("public_initialized") is True]
    candidates = [compose_fast_file_candidate(row, health_by_sample.get(row.get("last_camera_ns"))) for row in selected]
    targets = [row["target_ns"] for row in candidates]
    rate_qualified = bool(
        len(targets) >= 2
        and len(set(targets)) == len(targets)
        and all(b - a == 20_000_000 for a, b in zip(targets, targets[1:]))
    )
    if not rate_qualified:
        raise ValueError("fast file candidates are not unique 50 Hz")
    output.mkdir(parents=True)
    declaration = {
        "schema": "openvins-ekf2-fast-file-declaration-v1",
        "inputs": {
            "fast_rows_sha256": _sha256(fast_rows),
            "camera_candidates_sha256": _sha256(camera_candidates),
            "cohort_audit_sha256": _sha256(cohort_audit),
            "builder_sha256": _sha256(Path(__file__)),
        },
        "candidate_count": len(candidates),
        "target_rate_hz": 50,
        "hardware_covariance_calibrated": False,
        "network_odometry": False,
        "fusion_eligible": False,
        "truth_used_online": False,
    }
    (output / "declaration.json").write_text(json.dumps(declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output / "propagated-candidates.jsonl").open("x", encoding="utf-8") as stream:
        for candidate in candidates:
            stream.write(json.dumps(candidate, allow_nan=False, sort_keys=True) + "\n")
    result = {
        "schema": "openvins-ekf2-fast-file-result-v1",
        "candidate_count": len(candidates),
        "unique_candidate_samples": len(set(targets)),
        "first_target_ns": targets[0],
        "last_target_ns": targets[-1],
        "propagated_shadow_rate_qualified": rate_qualified,
        "propagated_covariance_sim_domain_qualified": True,
        "hardware_covariance_calibrated": False,
        "network_odometry": False,
        "fusion_eligible": False,
        "truth_used_online": False,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fast-rows", type=Path, required=True)
    parser.add_argument("--camera-candidates", type=Path, required=True)
    parser.add_argument("--cohort-audit", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
