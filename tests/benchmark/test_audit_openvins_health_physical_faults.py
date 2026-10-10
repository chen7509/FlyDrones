import json

import pytest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(tmp_path):
    from tools.benchmark.declared_runtime_snapshot import file_record

    root = tmp_path / "faults"
    plans = [
        ("source-loss-retry-seed-27311", "source_loss", 27311, "imu-source-loss-after-8s-immediate-v2"),
        ("native-restart-retry-seed-27312", "native_restart", 27312, "native-restart-after-8s-failclosed-v2"),
    ]
    runs = []
    for run_id, role, seed, profile in plans:
        study = root / run_id
        manifest = {
            "schema": "openvins-health-physical-fault-preflight-v1",
            "run_id": run_id,
            "role": role,
            "seed": seed,
            "health_fault_profile": profile,
            "expected_capture_status": "capture_failed",
            "expected_command_returncode": 2,
            "fault_result_viewed": False,
            "test_set_tuning_allowed": False,
            "truth_used_online": False,
            "odometry_published": False,
            "armed": False,
            "fusion_eligible": False,
        }
        write(study / "study-manifest.json", manifest)
        runs.append({"run_id": run_id, "role": role, "seed": seed, "manifest": file_record(study / "study-manifest.json")})
        write(study / "physical-completion.json", {
            "capture_status": "capture_failed", "command_returncode": 2,
            "outcome_matches_expectation": True, "resources_after": [], "fusion_eligible": False,
        })
        capture = study / "capture-v1"
        readiness = {"session_id": "fault-session-0", "reset_total": 0, "session_replacements": 0,
                     "truth_used": False, "fusion_eligible": False}
        owned = {"px4": ["ready", "prestop"], "openvins": ["ready", "prestop"]}
        errors = ["shadow failure: source_loss:imu"]
        if role == "native_restart":
            readiness.update(session_id="fault-session-1", reset_total=1, session_replacements=1)
            owned["openvins-restart"] = ["ready", "prestop"]
            errors = ["readiness lost after anchor"]
        write(capture / "result.json", {
            "status": "capture_failed", "errors": errors,
            "simulation_seed": {"seed": seed, "applied_before_test_fixture": True, "fusion_eligible": False},
            "health_fault_profile": profile, "eligible_for_px4_fusion": False,
            "px4_exit_code": 0, "readiness": readiness,
            "runtime_binding": {"declared_files_stable": True, "runtime_mapping_coverage_verified": True,
                                "owned_phases": owned, "errors": [], "runtime_closure_qualified": False},
            "writer": {"written": {"imu": 2001, "rgb": 81, "info": 81, "heartbeat": 7}},
            "px4_ulogs": [{"valid_header": True, "bytes": 100, "sha256": "a" * 64}],
        })
        sessions = [{"session_id": "fault-session-0", "native": {"exit": 0, "accepted": 100},
                     "shadow": {"failure": None}}]
        fault = {"failure": "source_loss:imu", "restart_count": 0, "dropped_source_records": 1,
                 "health_last": {"quality": -1, "reasons": ["source_failure"], "reset_total": 0,
                                 "fusion_eligible": False}, "sessions": sessions, "fusion_eligible": False}
        health = {"session_count": 1, "reset_total": 0, "reset_counter": 0, "last_quality": -1,
                  "last_health": fault["health_last"], "fusion_eligible": False}
        events = [{"event": "source_loss_started"}, {"event": "source_loss_detected"}]
        if role == "native_restart":
            sessions.append({"session_id": "fault-session-1", "native": {"exit": 0, "accepted": 1},
                             "shadow": {"failure": None}})
            fault.update(failure=None, restart_count=1, dropped_source_records=0,
                         health_last={"quality": 0, "reset_total": 1, "reset_counter": 1,
                                      "session_id": "fault-session-1", "fusion_eligible": False})
            health.update(session_count=2, reset_total=1, reset_counter=1,
                          last_health={"quality": -1, "reasons": ["capture_failure"],
                                       "reset_total": 1, "fusion_eligible": False})
            events = [{"event": "native_session_replaced"}]
        write(capture / "shadow/health-fault-result.json", fault)
        write(capture / "shadow/health-result.json", health)
        (capture / "shadow/health-fault-events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))
        write(capture / "supervisor.json", {"worker_exit": 2, "capture_status": "capture_failed",
                                             "cleanup": {"group_absent": True, "no_executing_members": True,
                                                         "errors": []}})
        (capture / "events.jsonl").write_text(
            json.dumps({"kind": "heartbeat", "base_mode": 29}) + "\n"
        )
    write(root / "fault-cohort-manifest.json", {
        "schema": "openvins-health-physical-fault-cohort-preflight-v1",
        "created_before_any_fault_result": True, "fault_result_viewed": False,
        "test_set_tuning_allowed": False, "truth_used_online": False,
        "odometry_published": False, "fusion_eligible": False, "runs": runs,
    })
    return root


def test_fault_audit_qualifies_predeclared_fail_closed_source_loss_and_restart(tmp_path):
    from tools.benchmark.audit_openvins_health_physical_faults import audit

    result = audit(fixture(tmp_path))
    assert result["qualified"] is True
    assert result["source_loss_qualified"] is True
    assert result["native_restart_reset_qualified"] is True
    assert result["fusion_eligible"] is False
    assert result["odometry_published"] is False


def test_fault_audit_rejects_tampered_reset_and_armed_heartbeat(tmp_path):
    from tools.benchmark.audit_openvins_health_physical_faults import audit

    root = fixture(tmp_path)
    restart = root / "native-restart-retry-seed-27312/capture-v1"
    health = json.loads((restart / "shadow/health-result.json").read_text())
    health["reset_total"] = 0
    write(restart / "shadow/health-result.json", health)
    (restart / "events.jsonl").write_text(json.dumps({"kind": "heartbeat", "base_mode": 157}) + "\n")
    with pytest.raises(ValueError, match="fault evidence"):
        audit(root)
