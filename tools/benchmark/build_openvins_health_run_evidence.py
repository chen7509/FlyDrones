"""Build offline covariance-cohort evidence from one retained physical run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scipy.spatial.transform import Rotation

from tools.benchmark.capture_contract import read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record
from tools.benchmark.trajectory_gauge_contract import (
    YawTranslationGauge,
    _native_state,
    _truth_state,
    audit_trajectory,
    select_origin,
    trajectory_contract,
)


def _jsonl(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        raise ValueError("unterminated JSONL: " + str(path))
    return [json.loads(line) for line in text.splitlines() if line]


def _write_x(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def error_vectors(gauge, native, truth):
    rn, pn, vn = _native_state(native)
    rt, pt, vt = _truth_state(truth)
    aligned_position = gauge.rotation @ (pn - gauge.native_origin) + gauge.truth_origin
    aligned_rotation = gauge.rotation @ rn
    return {
        "position_error_xyz_m": (aligned_position - pt).tolist(),
        "velocity_error_xyz_m_s": (gauge.rotation @ vn - vt).tolist(),
        "attitude_error_tangent_xyz_rad": Rotation.from_matrix(rt.T @ aligned_rotation).as_rotvec().tolist(),
    }


def build(capture, completion):
    capture = Path(capture).resolve(strict=True)
    completion = read_declaration(completion)
    result = read_declaration(capture / "result.json")
    states = _jsonl(capture / "shadow" / "states.jsonl")
    health_rows = _jsonl(capture / "shadow" / "health-evidence.jsonl")
    truth_raw = _jsonl(capture / "native-reference.jsonl")
    anchor = read_declaration(capture / "readiness-anchor.json")
    motion = read_declaration(capture / "motion-profile.json")
    health_result = read_declaration(capture / "shadow" / "health-result.json")
    truth_rows = [
        {
            **row,
            "sim_ns": row["post_ns"],
            "truth_for_fixture_audit_only": row["truth_for_abort_audit_only"],
        }
        for row in truth_raw
    ]
    contract = trajectory_contract(
        anchor_ns=anchor["anchor_ns"],
        total_duration_ns=motion["total_duration_ns"],
        lateral_start_offset_ns=motion["lateral_start_after_anchor_ns"],
    )
    trajectory = audit_trajectory(
        states,
        truth_rows,
        {
            "session_id": health_result["session_id"],
            "reset_counter": health_result["reset_counter"],
            "reset_observed": health_result["reset_total"] != 0,
            "quality": health_result["last_quality"],
            "covariance_calibrated": False,
        },
        {"status": result["status"], "end_sim_ns": result["end_sim_ns"]},
        contract,
    )
    origin = select_origin(states, contract)
    if origin is None:
        raise ValueError("development run has no internal estimator origin")
    truth = {row["sim_ns"]: row for row in truth_rows}
    gauge = YawTranslationGauge(states[origin["index"]]["imu_state"], truth[origin["sample_ns"]])
    health = {
        (row["native_sequence"], row["sample_ns"]): row
        for row in health_rows
        if row.get("event") == "camera_health"
    }
    samples = []
    for state in states:
        if not state["public_initialized"]:
            continue
        identity = (state["sequence"], state["sample_ns"])
        evidence = health.get(identity)
        if evidence is None or evidence.get("projected", {}).get("public_initialized") is not True:
            raise ValueError("public state lacks matching health evidence")
        scored_truth = truth.get(state["sample_ns"])
        if scored_truth is None:
            raise ValueError("public state lacks exact offline truth")
        current = evidence["health"]
        samples.append(
            {
                "session_id": current["session_id"],
                "quality": current["quality"],
                "reset_counter": current["reset_counter"],
                "public_initialized": True,
                "health_reasons": current["reasons"],
                "failed_latched": current["failed_latched"],
                **error_vectors(gauge, state["imu_state"], scored_truth),
                "bounded_covariance15": current["bounded_covariance15"],
            }
        )
    source_health_qualified = bool(
        result["status"] == "capture_completed"
        and result["errors"] == []
        and result.get("readiness", {}).get("failure") is None
        and result.get("runtime_binding", {}).get("runtime_mapping_coverage_verified") is True
    )
    native_health_qualified = bool(
        result.get("native", {}).get("exit") == 0
        and result.get("native", {}).get("failure") is None
        and health_result["last_quality"] == 0
        and health_result["reset_total"] == 0
    )
    trajectory_accuracy_qualified = bool(
        trajectory["diagnostic_screens_pass"]
        and trajectory["public_coverage_qualified"]
        and trajectory["capture_complete"]
    )
    run = {
        "status": result["status"],
        "session_id": health_result["session_id"],
        "trajectory_accuracy_qualified": trajectory_accuracy_qualified,
        "source_health_qualified": source_health_qualified,
        "native_health_qualified": native_health_qualified,
        "samples": samples,
    }
    prequalification_ready = bool(
        samples
        and all(
            row["quality"] == 0
            and row["health_reasons"] == ["covariance_profile_unqualified"]
            and row["failed_latched"] is False
            and row["reset_counter"] == 0
            for row in samples
        )
    )
    development_qualified = bool(
        completion.get("command_returncode") == 0
        and completion.get("launcher_returncode") == 0
        and completion.get("resources_after") == []
        and trajectory_accuracy_qualified
        and source_health_qualified
        and native_health_qualified
        and prequalification_ready
        and bool(result.get("px4_ulogs"))
    )
    gate = {
        "schema": "openvins-health-development-gate-v1",
        "development_qualified": development_qualified,
        "profile_frozen_before_held_out": True,
        "sample_count": len(samples),
        "trajectory_metrics": trajectory["metrics"],
        "prequalification_health_ready": prequalification_ready,
        "truth_used_online": False,
        "covariance_sim_domain_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    return run, trajectory, gate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--completion", type=Path, required=True)
    parser.add_argument("--run-output", type=Path, required=True)
    parser.add_argument("--trajectory-output", type=Path, required=True)
    parser.add_argument("--development-gate", type=Path)
    args = parser.parse_args(argv)
    run, trajectory, gate = build(args.capture, args.completion)
    _write_x(args.run_output, run)
    _write_x(args.trajectory_output, trajectory)
    if args.development_gate is not None:
        gate["builder"] = file_record(__file__)
        gate["run_evidence"] = file_record(args.run_output)
        gate["trajectory_audit"] = file_record(args.trajectory_output)
        _write_x(args.development_gate, gate)
    print(json.dumps({"run": run, "trajectory": trajectory, "development_gate": gate}, indent=2))
    return 0 if gate["development_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
