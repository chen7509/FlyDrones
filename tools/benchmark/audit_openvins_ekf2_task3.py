"""Independent terminal audit for the no-network OpenVINS-to-EKF2 Task 3 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid JSON object: " + str(path))
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(physical: Path, file_shadow: Path, fast_file: Path, predecessor_v3: Path, predecessor_v4: Path) -> dict:
    physical = Path(physical).resolve(strict=True)
    file_shadow = Path(file_shadow).resolve(strict=True)
    fast_file = Path(fast_file).resolve(strict=True)
    failures = []

    cohort = _json(physical / "cohort-manifest.json")
    fast_manifest = _json(physical / "fast-cohort-manifest.json")
    fast_preflight = _json(physical / "fast-preflight.json")
    fast_audit = _json(physical / "fast-cohort-audit.json")
    expected_held = ["held-out-seed-27611", "held-out-seed-27612", "held-out-seed-27613"]
    if cohort.get("seed_set") != "propagated-ekf2-grid-v5" or cohort.get("test_set_tuning_allowed") is not False:
        failures.append("physical_cohort_preflight")
    if fast_manifest.get("held_out_run_ids") != expected_held:
        failures.append("fast_manifest_identity")
    if fast_preflight.get("held_out_run_ids") != expected_held or fast_preflight.get("development_run_id") != "development-seed-27601":
        failures.append("fast_preflight_identity")
    if fast_preflight.get("fast_manifest_sha256") != _sha256(physical / "fast-cohort-manifest.json"):
        failures.append("fast_manifest_hash")
    if (
        fast_audit.get("sample_count") != 3327
        or fast_audit.get("minimum_component_coverage", 0.0) < 0.99
        or fast_audit.get("maximum_consecutive_violations", 5) > 4
        or fast_audit.get("propagated_covariance_sim_domain_qualified") is not True
        or fast_audit.get("hardware_covariance_calibrated") is not False
        or fast_audit.get("fusion_eligible") is not False
    ):
        failures.append("fast_cohort_audit")
    run_ids = ["development-seed-27601", *expected_held]
    run_results = []
    for run_id in run_ids:
        root = physical / run_id
        completion = _json(root / "physical-completion.json")
        evidence = _json(root / "fast-run-evidence.json")
        trajectory = _json(root / "trajectory-audit.json")
        ulog = _json(root / "capture-v1" / "px4-ulog-manifest.json")
        passed = bool(
            completion.get("command_returncode") == 0
            and completion.get("launcher_returncode") == 0
            and evidence.get("status") == "capture_completed"
            and len(evidence.get("samples", [])) == 1109
            and evidence.get("source_health_qualified") is True
            and evidence.get("native_health_qualified") is True
            and evidence.get("trajectory_accuracy_qualified") is True
            and trajectory.get("diagnostic_screens_pass") is True
            and trajectory.get("capture_complete") is True
            and len(ulog.get("logs", [])) == 1
            and ulog["logs"][0].get("valid_header") is True
        )
        if not passed:
            failures.append("run:" + run_id)
        run_results.append({"run_id": run_id, "passed": passed, "retained": True})

    for root, reason in (
        (Path(predecessor_v3).resolve(strict=True), "fast_target_camera_freshness_violation"),
        (Path(predecessor_v4).resolve(strict=True), "hard_coded_prediction_count_rejected_causal_grid"),
    ):
        failure = _json(root / "fast-development-gate-failure.json")
        if failure.get("reason") != reason or failure.get("development_qualified") is not False:
            failures.append("predecessor_failure:" + root.name)

    replay_manifest = _json(file_shadow / "replay-manifest.json")
    for name, record in replay_manifest.get("files", {}).items():
        path = Path(record["path"])
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            failures.append("replay_input_drift:" + name)
    case_results = []
    for case in ("normal", "source-loss", "native-timeout", "session-replacement"):
        result = _json(file_shadow / case / "case-result.json")
        passed = bool(
            result.get("case") == case
            and result.get("expected_outcome_observed") is True
            and result.get("network_odometry") is False
            and result.get("fusion_eligible") is False
            and result.get("truth_used_online") is False
        )
        if not passed:
            failures.append("file_shadow_case:" + case)
        case_results.append({"case": case, "passed": passed, "retained": True})
    normal = _json(file_shadow / "normal" / "case-result.json")
    session = _json(file_shadow / "session-replacement" / "case-result.json")
    if normal["evidence"].get("candidate_count") != 222 or normal["evidence"].get("receiver_shadow_rate_qualified") is not True:
        failures.append("normal_receiver_rate")
    if session["evidence"].get("reset_counter") != 1 or session["evidence"].get("session_count") != 2:
        failures.append("session_reset")

    propagated = _json(fast_file / "result.json")
    if (
        propagated.get("candidate_count") != 1109
        or propagated.get("unique_candidate_samples") != 1109
        or propagated.get("propagated_shadow_rate_qualified") is not True
        or propagated.get("propagated_covariance_sim_domain_qualified") is not True
        or propagated.get("hardware_covariance_calibrated") is not False
        or propagated.get("network_odometry") is not False
        or propagated.get("fusion_eligible") is not False
        or propagated.get("truth_used_online") is not False
    ):
        failures.append("propagated_file_candidates")

    return {
        "schema": "openvins-ekf2-task3-terminal-audit-v1",
        "run_results": run_results,
        "case_results": case_results,
        "failures": failures,
        "task3_qualified": not failures,
        "network_odometry": False,
        "px4_parameter_access": False,
        "hardware_covariance_calibrated": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("physical", "file-shadow", "fast-file", "predecessor-v3", "predecessor-v4", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output
    if output.exists():
        raise FileExistsError(output)
    result = audit(args.physical, args.file_shadow, args.fast_file, args.predecessor_v3, args.predecessor_v4)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["task3_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
