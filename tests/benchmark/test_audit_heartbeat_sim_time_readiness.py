import json

from tools.benchmark.audit_heartbeat_sim_time_readiness import audit


def source(tmp_path, **changes):
    value = {
        "schema": "openvins-handoff-physical-attempt-audit-v1",
        "failure_evidence_qualified": True,
        "classification": "journaled-heartbeat-wall-age-slow-simulation-refusal",
        "heartbeat_wall_age_ns": 2_000_774_305,
        "heartbeat_sim_age_ns": 968_000_000,
    }
    value.update(changes)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(value))
    return path


def test_fixed_physical_refusal_is_ready_in_simulation_time(tmp_path):
    result = audit(source(tmp_path))
    assert result["qualified"]
    assert result["fixed_evidence_ready"]
    assert result["simulation_silence_refused"]
    assert result["timeout_increased"] is result["physical_rerun"] is False
    assert result["vio_accuracy_qualified"] is result["fusion_eligible"] is False


def test_source_drift_and_true_simulation_staleness_refuse(tmp_path):
    assert not audit(source(tmp_path, classification="other"))["qualified"]
    assert not audit(source(tmp_path, heartbeat_sim_age_ns=2_000_000_001))["qualified"]
    assert not audit(source(tmp_path, heartbeat_wall_age_ns=2_000_000_000))["qualified"]
