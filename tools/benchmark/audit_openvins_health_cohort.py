"""Audit a frozen held-out OpenVINS covariance-envelope cohort.

Gazebo truth is consumed only as precomputed offline error vectors.  This tool
does not start OpenVINS, PX4, Gazebo, a transport publisher, or a controller.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.benchmark.openvins_health_contract import CovarianceProfile

COMPONENTS = (
    "attitude_x",
    "attitude_y",
    "attitude_z",
    "position_x",
    "position_y",
    "position_z",
    "velocity_x",
    "velocity_y",
    "velocity_z",
)
RUN_FIELDS = {
    "status",
    "session_id",
    "trajectory_accuracy_qualified",
    "source_health_qualified",
    "native_health_qualified",
    "samples",
}
SAMPLE_FIELDS = {
    "session_id",
    "quality",
    "reset_counter",
    "position_error_xyz_m",
    "velocity_error_xyz_m_s",
    "attitude_error_tangent_xyz_rad",
    "bounded_covariance15",
}


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _profile_document(profile: CovarianceProfile) -> dict:
    return {
        "name": profile.name,
        "position_variance_floor": profile.position_variance_floor,
        "velocity_variance_floor": profile.velocity_variance_floor,
        "attitude_variance_floor": profile.attitude_variance_floor,
        "profile_selected_before_held_out_runs": True,
        "hardware_calibrated": False,
    }


def build_manifest(profile: CovarianceProfile, held_out_run_ids: list[str]) -> dict:
    if not isinstance(profile, CovarianceProfile) or profile.sim_domain_qualified:
        raise ValueError("manifest requires unqualified pre-validation profile")
    if (
        not isinstance(held_out_run_ids, list)
        or not held_out_run_ids
        or any(not isinstance(item, str) or not item.strip() or any(c.isspace() for c in item) for item in held_out_run_ids)
        or len(set(held_out_run_ids)) != len(held_out_run_ids)
    ):
        raise ValueError("invalid held-out run identities")
    document = _profile_document(profile)
    return {
        "schema": "openvins-health-cohort-manifest-v1",
        "profile": document,
        "profile_sha256": _canonical_sha(document),
        "held_out_run_ids": list(held_out_run_ids),
        "minimum_component_coverage": 0.99,
        "maximum_consecutive_violations": 4,
        "truth_scope": "offline_scoring_only",
        "fusion_eligible": False,
    }


def _typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _vector(value: object, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError(f"invalid {name}")
    return result


def _covariance(value: object) -> np.ndarray:
    try:
        matrix = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid covariance") from exc
    if matrix.shape != (15, 15) or not np.all(np.isfinite(matrix)):
        raise ValueError("invalid covariance")
    scale = max(1.0, float(np.max(np.abs(matrix))))
    if not np.allclose(matrix, matrix.T, rtol=0, atol=1e-10 * scale):
        raise ValueError("invalid covariance")
    symmetric = (matrix + matrix.T) * 0.5
    if float(np.linalg.eigvalsh(symmetric)[0]) < -1e-12 * scale:
        raise ValueError("invalid covariance")
    return symmetric


def _sample_flags(row: object, session_id: str) -> np.ndarray:
    if not isinstance(row, dict) or set(row) != SAMPLE_FIELDS:
        raise ValueError("invalid covariance sample schema")
    if row["session_id"] != session_id:
        raise ValueError("sample session mismatch")
    if type(row["quality"]) is not int or not -1 <= row["quality"] <= 100:
        raise ValueError("invalid sample quality")
    if type(row["reset_counter"]) is not int or not 0 <= row["reset_counter"] <= 255:
        raise ValueError("invalid sample reset counter")
    attitude = np.abs(_vector(row["attitude_error_tangent_xyz_rad"], "attitude error"))
    position = np.abs(_vector(row["position_error_xyz_m"], "position error"))
    velocity = np.abs(_vector(row["velocity_error_xyz_m_s"], "velocity error"))
    covariance = _covariance(row["bounded_covariance15"])
    error = np.concatenate((attitude, position, velocity))
    bound = 3.0 * np.sqrt(np.maximum(np.diag(covariance)[:9], 0.0))
    return error <= bound


def audit_cohort(manifest: object, run_evidence: object) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("invalid cohort manifest")
    run_ids = manifest.get("held_out_run_ids")
    expected = build_manifest(CovarianceProfile(), run_ids) if isinstance(run_ids, list) else None
    if expected is None or manifest.get("profile_sha256") != _canonical_sha(manifest.get("profile")):
        raise ValueError("profile digest mismatch")
    if not _typed_equal(manifest, expected):
        if manifest.get("profile_sha256") != expected["profile_sha256"]:
            raise ValueError("profile digest mismatch")
        raise ValueError("invalid frozen cohort manifest")
    if not isinstance(run_evidence, dict) or set(run_evidence) != set(run_ids):
        raise ValueError("declared run evidence mismatch")

    reasons: list[str] = []
    passed = np.zeros(len(COMPONENTS), dtype=np.int64)
    total = np.zeros(len(COMPONENTS), dtype=np.int64)
    maximum_consecutive = 0
    run_results = []
    for run_id in run_ids:
        evidence = run_evidence[run_id]
        if not isinstance(evidence, dict) or set(evidence) != RUN_FIELDS:
            raise ValueError("invalid run evidence schema")
        session_id = evidence["session_id"]
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("invalid run session")
        for key in ("trajectory_accuracy_qualified", "source_health_qualified", "native_health_qualified"):
            if type(evidence[key]) is not bool:
                raise ValueError("invalid run qualification flag")
        samples = evidence["samples"]
        if not isinstance(samples, list):
            raise ValueError("invalid run samples")
        run_reasons = []
        completed = evidence["status"] == "capture_completed" and bool(samples)
        if not completed:
            run_reasons.append("run_failed")
            reasons.append(f"run_failed:{run_id}")
        if not evidence["trajectory_accuracy_qualified"]:
            run_reasons.append("trajectory_accuracy_failed")
        if not evidence["source_health_qualified"]:
            run_reasons.append("source_health_failed")
        if not evidence["native_health_qualified"]:
            run_reasons.append("native_health_failed")

        run_flags = []
        qualities = []
        reset_counters = []
        for row in samples:
            flags = _sample_flags(row, session_id)
            run_flags.append(flags)
            qualities.append(row["quality"])
            reset_counters.append(row["reset_counter"])
            passed += flags.astype(np.int64)
            total += 1
        if qualities and any(value != 1 for value in qualities):
            run_reasons.append("health_not_positive")
            reasons.append(f"health_not_positive:{run_id}")
        if reset_counters and len(set(reset_counters)) != 1:
            run_reasons.append("reset_changed")
            reasons.append(f"reset_changed:{run_id}")
        if run_flags:
            consecutive = np.zeros(len(COMPONENTS), dtype=np.int64)
            for flags in run_flags:
                consecutive = np.where(flags, 0, consecutive + 1)
                maximum_consecutive = max(maximum_consecutive, int(np.max(consecutive)))
        run_results.append(
            {
                "run_id": run_id,
                "status": evidence["status"],
                "sample_count": len(samples),
                "reasons": run_reasons,
                "retained": True,
            }
        )

    coverage = np.divide(passed, total, out=np.zeros_like(passed, dtype=float), where=total > 0)
    minimum_coverage = float(np.min(coverage)) if np.all(total > 0) else 0.0
    if minimum_coverage < manifest["minimum_component_coverage"]:
        reasons.append("coverage_below_0.99")
    if maximum_consecutive > manifest["maximum_consecutive_violations"]:
        reasons.append("consecutive_violations")
    for item in run_results:
        if any(reason.endswith("_failed") for reason in item["reasons"]):
            reasons.append(f"run_health_or_accuracy_failed:{item['run_id']}")
    reasons = list(dict.fromkeys(reasons))
    qualified = not reasons and bool(run_results) and int(total[0]) > 0
    return {
        "schema": "openvins-health-cohort-audit-v1",
        "manifest": copy.deepcopy(manifest),
        "sample_count": int(total[0]),
        "component_coverage": dict(zip(COMPONENTS, (float(value) for value in coverage), strict=True)),
        "minimum_component_coverage": minimum_coverage,
        "maximum_consecutive_violations": maximum_consecutive,
        "run_results": run_results,
        "reasons": reasons,
        "covariance_sim_domain_qualified": qualified,
        "hardware_covariance_calibrated": False,
        "truth_used_online": False,
        "fusion_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite health cohort audit")
    manifest = json.loads(args.manifest.read_text())
    evidence = {
        run_id: json.loads((args.runs_dir / f"{run_id}.json").read_text())
        for run_id in manifest.get("held_out_run_ids", [])
    }
    result = audit_cohort(manifest, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

