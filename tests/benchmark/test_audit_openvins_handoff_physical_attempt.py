import hashlib
import json

import pytest


def dump(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def fixture(tmp_path):
    capture = tmp_path / "capture-v1"
    capture.mkdir()
    heartbeat = {
        "kind": "heartbeat",
        "arrival_monotonic_ns": 254_526_101_224,
        "observed_sim_ns": 3_679_000_000,
        "system_id": 9,
        "base_mode": 29,
        "custom_mode": 50_593_792,
    }
    ready = [
        {
            "event": "estimator_internal_ready",
            "sample_ns": 2_400_000_000,
            "internal_initialized": True,
            "public_initialized": False,
            "truth_used": False,
            "fusion_eligible": False,
        },
        {
            "event": "estimator_internal_ready",
            "sample_ns": 3_300_000_000,
            "internal_initialized": True,
            "public_initialized": True,
            "truth_used": False,
            "fusion_eligible": False,
        },
        {
            "event": "estimator_internal_ready",
            "sample_ns": 4_600_000_000,
            "internal_initialized": True,
            "public_initialized": True,
            "truth_used": False,
            "fusion_eligible": False,
        },
    ]
    result = {
        "status": "capture_failed",
        "end_sim_ns": 4_650_000_000,
        "capture_wall_s": 30.17713301599997,
        "errors": ["motion fixture: ValueError(\"ValueError('readiness lost after anchor')\")"],
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "estimator_run": True,
        "px4_exit_code": 0,
        "motion": {
            "failure": "ValueError('readiness lost after anchor')",
            "last_ns": 4_647_000_000,
            "active_steps": 0,
            "support_steps": 2027,
            "recorded_commands": 2027,
            "anchor_ns": 2_620_000_000,
            "full_profile_requested": False,
            "eligible_for_px4_fusion": False,
        },
        "readiness": {
            "source": {"clock_high_water_ns": 256_526_875_529, "failure": None},
            "first_internal": ready[0],
            "latest_internal": ready[-1],
            "failure": None,
            "truth_used": False,
            "fusion_eligible": False,
        },
        "source_fanout": {
            "failure": "RuntimeError('pre-step source failure')",
            "heartbeat": {"observed": 3, "reconciled": 3, "pending": [], "failure": None},
            "fusion_eligible": False,
            "quality": None,
            "reset_counter": None,
        },
        "shadow": {"failure": None, "fusion_eligible": False, "quality": None, "reset_counter": None},
        "native": {"exit": 0, "failure": None, "fusion_eligible": False},
        "runtime_binding": {
            "runtime_mapping_coverage_verified": True,
            "runtime_closure_qualified": False,
        },
        "px4_ulogs": [],
    }
    ulog = capture / "flight.ulg"
    ulog.write_bytes(b"ULog-handoff-heartbeat")
    item = {
        "path": "flight.ulg",
        "bytes": ulog.stat().st_size,
        "sha256": hashlib.sha256(ulog.read_bytes()).hexdigest(),
        "valid_header": True,
    }
    result["px4_ulogs"] = [item]
    dump(capture / "result.json", result)
    dump(capture / "readiness-anchor.json", {
        "anchor_ns": 2_620_000_000,
        "selected_sim_ns": 2_420_000_000,
        "profile": {"heartbeat_max_age_ns": 2_000_000_000},
        "eligible_for_px4_fusion": False,
    })
    (capture / "heartbeat-observations.jsonl").write_text("\n".join([
        json.dumps({"event": "heartbeat_observed", "observation_sequence": 0,
                    "original": {**heartbeat, "arrival_monotonic_ns": 250_561_338_632,
                                 "observed_sim_ns": 1_685_000_000}}),
        json.dumps({"event": "heartbeat_reconciled", "observation_sequence": 0}),
        json.dumps({"event": "heartbeat_observed", "observation_sequence": 1,
                    "original": {**heartbeat, "arrival_monotonic_ns": 252_542_415_865,
                                 "observed_sim_ns": 2_679_000_000}}),
        json.dumps({"event": "heartbeat_reconciled", "observation_sequence": 1}),
        json.dumps({"event": "heartbeat_observed", "observation_sequence": 2, "original": heartbeat}),
        json.dumps({"event": "heartbeat_reconciled", "observation_sequence": 2}),
    ]) + "\n", encoding="utf-8")
    (capture / "estimator-readiness.jsonl").write_text(
        "\n".join(json.dumps(row) for row in ready) + "\n", encoding="utf-8"
    )
    (capture / "events.jsonl").write_text(json.dumps({
        "kind": "imu", "source_sequence": 1306, "sample_ns": 4_648_000_000,
        "observed_sim_ns": 4_648_000_000,
    }) + "\n", encoding="utf-8")
    dump(capture / "px4-ulog-manifest.json", {
        "schema": "flydrones-px4-ulog-capture-v1", "logs": [item],
    })
    supervisor = {
        "capture_status": "capture_failed",
        "worker_exit": 2,
        "cleanup": {
            "events": [{"event": "ownership"}, {"event": "leader_reaped", "returncode": 2}],
            "errors": [],
            "no_executing_members": True,
            "group_absent": True,
            "sigkill_dispatched": False,
            "all_descendant_cleanup_qualified": False,
            "final_snapshot": {"members": []},
        },
    }
    dump(capture / "supervisor.json", supervisor)
    journal = capture.parent / "capture-v1.supervisor-events.jsonl"
    journal.write_text(
        "\n".join(json.dumps(row) for row in supervisor["cleanup"]["events"]) + "\n",
        encoding="utf-8",
    )
    completion = tmp_path / "completion.json"
    dump(completion, {
        "returncode": 2, "destination_exists": True, "physical_run": True, "resources_after": [],
    })
    return capture, completion


def test_handoff_physical_attempt_audit_classifies_wall_age_refusal(tmp_path):
    from tools.benchmark.audit_openvins_handoff_physical_attempt import FALSE_CLAIMS, audit

    capture, completion = fixture(tmp_path)
    result = audit(capture, completion)
    assert result["failure_evidence_qualified"] is True
    assert result["classification"] == "journaled-heartbeat-wall-age-slow-simulation-refusal"
    assert result["heartbeat_wall_age_ns"] == 2_000_774_305
    assert result["heartbeat_wall_excess_ns"] == 774_305
    assert result["heartbeat_sim_age_ns"] == 968_000_000
    assert result["public_initialization_physically_observed"] is True
    assert all(result[key] is False for key in FALSE_CLAIMS)


@pytest.mark.parametrize(
    "field",
    ["cause", "wall_age", "sim_age", "public", "motion", "heartbeat", "ulog", "cleanup", "resources", "runtime"],
)
def test_handoff_physical_attempt_audit_rejects_evidence_drift(tmp_path, field):
    from tools.benchmark.audit_openvins_handoff_physical_attempt import audit

    capture, completion = fixture(tmp_path)
    result_path = capture / "result.json"
    result = json.loads(result_path.read_text())
    if field == "cause":
        result["motion"]["failure"] = "other"
    elif field == "wall_age":
        result["readiness"]["source"]["clock_high_water_ns"] -= 1_000_000
    elif field == "sim_age":
        result["motion"]["last_ns"] += 1_100_000_000
    elif field == "public":
        rows = [json.loads(line) for line in (capture / "estimator-readiness.jsonl").read_text().splitlines()]
        for row in rows:
            row["public_initialized"] = False
        (capture / "estimator-readiness.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    elif field == "motion":
        result["motion"]["active_steps"] = 1
    elif field == "heartbeat":
        result["source_fanout"]["heartbeat"]["pending"] = [3]
    elif field == "ulog":
        (capture / "flight.ulg").write_bytes(b"changed")
    elif field == "cleanup":
        supervisor = json.loads((capture / "supervisor.json").read_text())
        supervisor["cleanup"]["group_absent"] = False
        dump(capture / "supervisor.json", supervisor)
    elif field == "resources":
        dump(completion, {"returncode": 2, "destination_exists": True,
                          "physical_run": True, "resources_after": ["px4"]})
    else:
        result["runtime_binding"]["runtime_mapping_coverage_verified"] = False
    if field not in {"public", "ulog", "cleanup", "resources"}:
        dump(result_path, result)
    assert audit(capture, completion)["failure_evidence_qualified"] is False
