"""Diagnose ZUPT / accelerometer-bias timing from an immutable OpenVINS run."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from tools.benchmark.audit_heartbeat_commit_order_physical_attempt import native_reference_truth
from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.trajectory_gauge_contract import YawTranslationGauge

ACCEPTED = re.compile(r"\[ZUPT\]: accepted \|v_IinG\| = ([0-9.eE+-]+)")
REJECTED = re.compile(r"\[ZUPT\]: rejected \|v_IinG\| = ([0-9.eE+-]+)")
PASSED_DISPARITY = re.compile(r"\[ZUPT\]: passed disparity \(([0-9.eE+-]+) < ([0-9.eE+-]+), (\d+) features\)")
MSCKF = re.compile(r"MSCKF update \((\d+) feats\)")
SLAM = re.compile(r"SLAM update \((\d+) feats\)")
SLAM_INIT = re.compile(r"SLAM delayed init \((\d+) feats\)")


def _strict_int(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _finite_vector(value, size, name):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"invalid {name}")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError(f"invalid {name}")
        result.append(float(item))
    return result


def _norm(value):
    return math.sqrt(sum(item * item for item in value))


def _validate(states, truth_rows):
    if not isinstance(states, list) or not states:
        raise ValueError("missing states")
    if not isinstance(truth_rows, list) or not truth_rows:
        raise ValueError("missing truth")
    truth = {}
    previous = None
    for row in truth_rows:
        if not isinstance(row, dict) or row.get("truth_for_fixture_audit_only") is not True:
            raise ValueError("invalid truth scope")
        stamp = _strict_int(row.get("sim_ns"), "truth time")
        if previous is not None and stamp <= previous:
            raise ValueError("truth time regressed")
        previous = stamp
        _finite_vector(row.get("position"), 3, "truth position")
        _finite_vector(row.get("velocity_world"), 3, "truth velocity")
        _finite_vector(row.get("accel_world"), 3, "truth acceleration")
        _finite_vector(row.get("quaternion_xyzw"), 4, "truth orientation")
        truth[stamp] = row
    previous = None
    for row in states:
        if not isinstance(row, dict) or row.get("kind") != "C":
            raise ValueError("invalid state")
        stamp = _strict_int(row.get("sample_ns"), "state time")
        if previous is not None and stamp <= previous:
            raise ValueError("state time regressed")
        previous = stamp
        if type(row.get("zupt_flag_latched")) is not bool:
            raise ValueError("invalid ZUPT flag")
        internal = row.get("internal_initialized")
        if type(internal) is not bool:
            raise ValueError("invalid initialization flag")
        if internal:
            if stamp not in truth:
                raise ValueError(f"missing exact truth at {stamp}")
            _finite_vector(row.get("imu_state"), 16, "IMU state")
        elif row.get("imu_state") is not None:
            raise ValueError("uninitialized state has IMU state")
    return truth


def _feature_counts(native_log):
    accepted = [float(value) for value in ACCEPTED.findall(native_log)]
    rejected = [float(value) for value in REJECTED.findall(native_log)]
    passed = PASSED_DISPARITY.findall(native_log)
    msckf = [int(value) for value in MSCKF.findall(native_log)]
    slam = [int(value) for value in SLAM.findall(native_log)]
    delayed = [int(value) for value in SLAM_INIT.findall(native_log)]
    return {
        "accepted_zupt_count": len(accepted),
        "rejected_zupt_count": len(rejected),
        "passed_disparity_count": len(passed),
        "accepted_over_speed_count": sum(value > 0.10 for value in accepted),
        "accepted_estimated_speed_max_m_s": max(accepted) if accepted else None,
        "rejected_estimated_speed_min_m_s": min(rejected) if rejected else None,
        "msckf_update_count": len(msckf),
        "msckf_nonzero_update_count": sum(value > 0 for value in msckf),
        "msckf_feature_total": sum(msckf),
        "slam_update_count": len(slam),
        "slam_nonzero_update_count": sum(value > 0 for value in slam),
        "slam_feature_total": sum(slam),
        "slam_delayed_nonzero_count": sum(value > 0 for value in delayed),
        "slam_delayed_feature_total": sum(delayed),
    }


def diagnose(states, truth_rows, native_log, *, anchor_ns):
    """Return an offline diagnosis; truth is never used to change estimator state."""
    anchor = _strict_int(anchor_ns, "anchor")
    truth = _validate(states, truth_rows)
    if not isinstance(native_log, str):
        raise ValueError("invalid native log")
    initialized = [row for row in states if row["internal_initialized"]]
    if not initialized:
        raise ValueError("missing initialized state")
    zupt = [row for row in initialized if row["zupt_flag_latched"]]
    after_anchor = [row for row in zupt if row["sample_ns"] > anchor]
    before_anchor = [row for row in initialized if row["sample_ns"] <= anchor]
    if not before_anchor:
        raise ValueError("no state before motion anchor")

    first_state = initialized[0]
    gauge = YawTranslationGauge(first_state["imu_state"], truth[first_state["sample_ns"]])
    timeline = []
    for row in initialized:
        reference = truth[row["sample_ns"]]
        compared = gauge.compare(row["imu_state"], reference)
        timeline.append(
            {
                "sample_ns": row["sample_ns"],
                "zupt_flag_latched": row["zupt_flag_latched"],
                "public_initialized": row.get("public_initialized"),
                "position_error_m": compared["position_error_m"],
                "velocity_error_m_s": compared["velocity_error_m_s"],
                "attitude_error_deg": compared["attitude_error_deg"],
                "bias_accel": row["imu_state"][13:16],
                "truth_speed_m_s": _norm(reference["velocity_world"]),
                "truth_accel_m_s2": _norm(reference["accel_world"]),
            }
        )

    reference_before = max(before_anchor, key=lambda row: row["sample_ns"])
    motion_zupt = []
    reference_truth = truth[reference_before["sample_ns"]]
    for row in after_anchor:
        actual = truth[row["sample_ns"]]
        displacement = _norm(
            [a - b for a, b in zip(actual["position"], reference_truth["position"], strict=True)]
        )
        speed = _norm(actual["velocity_world"])
        if displacement > 1e-6 or speed > 1e-4:
            motion_zupt.append((row, displacement, speed))

    before_bias = reference_before["imu_state"][15]
    after_bias = motion_zupt[-1][0]["imu_state"][15] if motion_zupt else before_bias
    bias_change = after_bias - before_bias
    parsed = _feature_counts(native_log)
    conflict = bool(motion_zupt)
    bias_corruption = conflict and abs(bias_change) > 0.01
    classification = (
        "physical-motion-accepted-as-zupt-with-accelerometer-bias-corruption"
        if bias_corruption
        else "zupt-bias-causal-mechanism-not-established"
    )
    return {
        "schema": "openvins-zupt-bias-diagnosis-v1",
        "classification": classification,
        "anchor_ns": anchor,
        "state_count": len(states),
        "initialized_state_count": len(initialized),
        "zupt_state_count": len(zupt),
        "zupt_states_after_motion_anchor": len(after_anchor),
        "moving_zupt_state_count": len(motion_zupt),
        "first_motion_accepted_as_zupt_ns": motion_zupt[0][0]["sample_ns"] if motion_zupt else None,
        "last_motion_accepted_as_zupt_ns": motion_zupt[-1][0]["sample_ns"] if motion_zupt else None,
        "max_truth_speed_during_motion_zupt_m_s": max((row[2] for row in motion_zupt), default=None),
        "max_truth_displacement_during_motion_zupt_m": max((row[1] for row in motion_zupt), default=None),
        "bias_z_before_motion": before_bias,
        "bias_z_after_accepted_motion": after_bias,
        "bias_z_change_during_motion_zupt": bias_change,
        "zupt_motion_conflict": conflict,
        "accelerometer_bias_corruption_observed": bias_corruption,
        "native_log": parsed,
        "timeline": timeline,
        "truth_used_online": False,
        "eligible_for_px4_fusion": False,
        "entire_terminal_drift_single_cause_proven": False,
        "scope": "first demonstrated failure mechanism on fixed input; not a corrected estimator or flight qualification",
    }


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    capture = args.capture.resolve(strict=True)
    anchor = json.loads((capture / "readiness-anchor.json").read_text(encoding="utf-8"))
    result = diagnose(
        _jsonl(capture / "shadow" / "states.jsonl"),
        native_reference_truth(_jsonl(capture / "native-reference.jsonl")),
        (capture / "shadow" / "native.log").read_text(encoding="utf-8", errors="strict"),
        anchor_ns=anchor.get("anchor_ns"),
    )
    write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
