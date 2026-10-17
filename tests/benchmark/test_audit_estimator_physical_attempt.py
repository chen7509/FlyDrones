import json

import pytest


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def fixture(tmp_path):
    capture = tmp_path / "capture-v1"
    capture.mkdir()
    result = {
        "status": "capture_failed",
        "end_sim_ns": 10_000_000,
        "estimator_run": True,
        "source_fanout": {"failure": "pending input exceeded wall wait", "failure_latched_ns": 1_270_000_000,
                          "fusion_eligible": False},
        "shadow": {"failure": "ValueError('pending input exceeded wall wait')"},
        "motion": {"active_steps": 0, "support_steps": 0, "absolute_impulse_ns": 0.0, "anchor_ns": None},
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "px4_ulogs": [],
        "px4_exit_code": -9,
        "errors": ["owned PX4 required SIGKILL"],
        "runtime_binding": {
            "phases": ["postgraph", "bootstrap", "postimports", "postfinalize", "postfirststep"],
            "owned_phases": {"openvins": ["ready", "prestop"], "px4": []},
            "runtime_mapping_coverage_verified": False,
        },
    }
    write_json(capture / "result.json", result)
    write_json(capture / "px4-ulog-manifest.json", {"logs": []})
    write_json(capture / "supervisor.json", {
        "capture_status": "capture_failed", "worker_exit": 2,
        "cleanup": {"no_executing_members": True, "group_absent": True, "sigkill_dispatched": False,
                    "final_snapshot": {"members": []}},
    })
    (capture / "motion-force.jsonl").write_bytes(b"")
    events = [
        {"kind": "imu", "source_sequence": 0, "sample_ns": 1_000_000, "arrival_monotonic_ns": 1_000_000_000,
         "writer_begin_monotonic_ns": 1_000_000_001},
        {"kind": "info", "source_sequence": 1, "sample_ns": 2_000_000, "arrival_monotonic_ns": 1_000_000_000},
        {"kind": "depth", "source_sequence": 2, "sample_ns": 2_000_000, "arrival_monotonic_ns": 1_220_000_000},
        {"kind": "rgb", "source_sequence": 3, "sample_ns": 2_000_000, "arrival_monotonic_ns": 1_225_000_000},
        {"kind": "imu", "source_sequence": 4, "sample_ns": 4_000_000, "arrival_monotonic_ns": 1_226_000_000,
         "writer_begin_monotonic_ns": 1_271_000_000},
        {"kind": "imu", "source_sequence": 5, "sample_ns": 8_000_000, "arrival_monotonic_ns": 1_227_000_000,
         "writer_begin_monotonic_ns": 1_272_000_000},
    ]
    (capture / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    (capture / "source-fanout.jsonl").write_text(json.dumps({
        "event": "source_delivery", "source_sequence": 3, "begin_ns": 1_230_000_000,
        "failure": "pending input exceeded wall wait", "failure_latched_ns": 1_270_000_000,
    }) + "\n", encoding="utf-8")
    completion = tmp_path / "completion.json"
    write_json(completion, {"returncode": 2, "destination_exists": True, "resources_after": []})
    return capture, completion


@pytest.mark.parametrize("field", ["status", "motion", "fusion", "ulog", "px4", "cleanup", "resources", "timing"])
def test_attempt_audit_rejects_evidence_drift(tmp_path, field):
    from tools.benchmark.audit_estimator_physical_attempt import audit

    capture, completion = fixture(tmp_path)
    if field in {"status", "motion", "fusion", "px4"}:
        result = json.loads((capture / "result.json").read_text())
        if field == "status":
            result["status"] = "completed"
        elif field == "motion":
            result["motion"]["active_steps"] = 1
        elif field == "fusion":
            result["eligible_for_px4_fusion"] = True
        else:
            result["px4_exit_code"] = 0
        write_json(capture / "result.json", result)
    elif field == "ulog":
        write_json(capture / "px4-ulog-manifest.json", {"logs": [{"path": "bad.ulg"}]})
    elif field == "cleanup":
        supervisor = json.loads((capture / "supervisor.json").read_text())
        supervisor["cleanup"]["group_absent"] = False
        write_json(capture / "supervisor.json", supervisor)
    elif field == "resources":
        write_json(completion, {"returncode": 2, "destination_exists": True, "resources_after": ["px4"]})
    else:
        rows = [json.loads(line) for line in (capture / "events.jsonl").read_text().splitlines()]
        rows[4]["writer_begin_monotonic_ns"] = 1_269_000_000
        (capture / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert audit(capture, completion)["failure_evidence_qualified"] is False


def test_attempt_audit_reports_deadline_crossing_and_closed_qualifications(tmp_path):
    from tools.benchmark.audit_estimator_physical_attempt import FALSE_CLAIMS, audit

    capture, completion = fixture(tmp_path)
    result = audit(capture, completion)
    assert result["failure_evidence_qualified"] is True and not result["failures"]
    assert result["timing"]["info_to_rgb_arrival_ns"] == 225_000_000
    assert result["timing"]["info_to_failure_ns"] == 270_000_000
    assert result["timing"]["later_imu_writer_begin_after_failure_ns"] == 1_000_000
    assert all(result[key] is False for key in FALSE_CLAIMS)
