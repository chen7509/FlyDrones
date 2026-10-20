import hashlib
import json

import pytest

from tools.benchmark.audit_estimator_heartbeat_routing import audit


def write_fixture(tmp_path):
    source = {
        "kind": "heartbeat",
        "arrival_monotonic_ns": 10,
        "observed_sim_ns": 20,
        "system_id": 9,
        "base_mode": 29,
        "custom_mode": 0,
        "source_sequence": 426,
        "writer_begin_monotonic_ns": 11,
        "recorded_monotonic_ns": 12,
    }
    source_hash = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    refusal = {
        "event": "source_delivery",
        "source_sequence": 426,
        "source_sha256": source_hash,
        "dispositions": {"shadow": "attempted", "readiness": "not_attempted"},
        "failure": "ValueError('invalid source sample')",
    }
    result = {
        "status": "capture_failed",
        "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
        "eligible_for_px4_fusion": False,
        "px4_exit_code": 0,
        "source_fanout": {
            "failure": "invalid source sample",
            "last_disposition": refusal,
            "heartbeat": {"observed": 1, "reconciled": 0},
        },
        "motion": {"anchor_ns": None, "active_steps": 0, "support_steps": 0, "recorded_commands": 0},
    }
    supervisor = {
        "cleanup": {
            "sigkill_dispatched": False,
            "no_executing_members": True,
            "group_absent": True,
            "all_descendant_cleanup_qualified": False,
        }
    }
    files = {
        "result.json": result,
        "supervisor.json": supervisor,
        "px4-ulog-manifest.json": {"logs": [{"valid_header": True, "bytes": 10}]},
    }
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "events.jsonl").write_text(json.dumps(source) + "\n")
    (tmp_path / "source-fanout.jsonl").write_text(json.dumps(refusal) + "\n")
    return tmp_path


def test_exact_routing_refusal_is_classified(tmp_path):
    out = audit(write_fixture(tmp_path))
    assert out["failure_classification_qualified"] is True
    assert out["classification"] == "estimator-ack-routing-heartbeat-without-sample-refusal"
    assert out["claims"]["fruit_fly_learning_failure"] is False


@pytest.mark.parametrize(
    "mutation",
    ["sample", "motion", "fusion", "readiness", "hash", "sigkill", "descendants"],
)
def test_incompatible_evidence_refuses_classification(tmp_path, mutation):
    capture = write_fixture(tmp_path)
    if mutation == "sample":
        rows = [json.loads(line) for line in (capture / "events.jsonl").read_text().splitlines()]
        rows[0]["sample_ns"] = 20
        (capture / "events.jsonl").write_text(json.dumps(rows[0]) + "\n")
    elif mutation in {"motion", "fusion", "readiness"}:
        value = json.loads((capture / "result.json").read_text())
        if mutation == "motion":
            value["motion"]["active_steps"] = 1
        elif mutation == "fusion":
            value["eligible_for_px4_fusion"] = True
        else:
            value["source_fanout"]["last_disposition"]["dispositions"]["readiness"] = "attempted"
            lines = [json.loads(x) for x in (capture / "source-fanout.jsonl").read_text().splitlines()]
            lines[0]["dispositions"]["readiness"] = "attempted"
            (capture / "source-fanout.jsonl").write_text(json.dumps(lines[0]) + "\n")
        (capture / "result.json").write_text(json.dumps(value))
    elif mutation == "hash":
        rows = [json.loads(x) for x in (capture / "source-fanout.jsonl").read_text().splitlines()]
        rows[0]["source_sha256"] = "0" * 64
        (capture / "source-fanout.jsonl").write_text(json.dumps(rows[0]) + "\n")
    else:
        value = json.loads((capture / "supervisor.json").read_text())
        if mutation == "sigkill":
            value["cleanup"]["sigkill_dispatched"] = True
        else:
            value["cleanup"]["all_descendant_cleanup_qualified"] = True
        (capture / "supervisor.json").write_text(json.dumps(value))
    assert audit(capture)["failure_classification_qualified"] is False
