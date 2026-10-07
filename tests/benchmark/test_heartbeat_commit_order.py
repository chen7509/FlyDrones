import json
from pathlib import Path

from tools.benchmark.audit_heartbeat_commit_order import audit
from tools.benchmark.readiness_anchor import JournaledReadiness

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v19/capture-v1"
COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v10-completion.json"


def event(kind, *, arrival, sim):
    row = {
        "kind": kind,
        "arrival_monotonic_ns": arrival,
        "recorded_monotonic_ns": arrival,
        "observed_sim_ns": sim,
    }
    if kind == "heartbeat":
        row.update(system_id=9, base_mode=29, custom_mode=0)
    return row


def add_high_rate(gate, now, sim):
    for offset, kind in enumerate(("imu", "rgb", "info")):
        gate.on_record(event(kind, arrival=now - 3 + offset, sim=sim), None)


def test_fixed_physical_failure_is_commit_order_not_policy_failure():
    result = audit(CAPTURE, COMPLETION)
    assert result["failures"] == []
    assert result["classification"] == "heartbeat-observation-ahead-of-committed-imu"
    assert result["heartbeat_lead_ns"] == 10_000_000
    assert result["previous_heartbeat_age_ns"] == 988_000_000
    assert result["pre_arrived_imu_times_ns"] == [2_608_000_000, 2_612_000_000]
    assert result["fruit_fly_policy_failure"] is False


def test_newer_future_heartbeat_keeps_previous_causally_valid_heartbeat():
    now = [10_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    gate.on_record(event("heartbeat", arrival=9_990, sim=1_000), None)
    add_high_rate(gate, 9_999, 1_900)
    first = gate.proof()
    assert first["records"]["heartbeat"]["observed_sim_ns"] == 1_000

    gate.on_record(event("heartbeat", arrival=9_999, sim=2_100), None)
    proof = gate.proof()
    assert proof["records"]["heartbeat"]["observed_sim_ns"] == 1_000
    assert proof["freshness"]["heartbeat_sim_age_ns"] == 900
    assert proof["freshness"]["latest_heartbeat_ahead_ns"] == 200
    assert gate.snapshot()["failure"] is None

    now[0] += 10
    add_high_rate(gate, now[0], 2_100)
    caught_up = gate.proof()
    assert caught_up["records"]["heartbeat"]["observed_sim_ns"] == 2_100
    assert caught_up["freshness"]["latest_heartbeat_ahead_ns"] == 0


def test_no_causally_eligible_heartbeat_waits_without_granting_readiness():
    now = [10_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    gate.on_record(event("heartbeat", arrival=9_999, sim=2_100), None)
    add_high_rate(gate, 9_999, 1_900)
    assert gate.proof() is None
    assert gate.snapshot()["failure"] is None
    now[0] += 10
    add_high_rate(gate, now[0], 2_100)
    assert gate.proof()["records"]["heartbeat"]["observed_sim_ns"] == 2_100


def test_stale_previous_heartbeat_does_not_hide_future_candidate():
    now = [10_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    gate.on_record(event("heartbeat", arrival=9_990, sim=1_000), None)
    gate.on_record(event("heartbeat", arrival=9_999, sim=4_000_000_000), None)
    add_high_rate(gate, 9_999, 3_000_000_001)
    assert gate.proof() is None
    assert gate.snapshot()["failure"] is None


def test_heartbeat_history_is_bounded_and_monotonic():
    now = [100_000]
    gate = JournaledReadiness(clock=lambda: now[0])
    for index in range(40):
        gate.on_record(event("heartbeat", arrival=99_000 + index, sim=1_000 + index), None)
    snapshot = gate.snapshot()
    assert len(snapshot["heartbeat_history"]) == 32
    assert snapshot["heartbeat_history"][0]["observed_sim_ns"] == 1_008
    assert snapshot["heartbeat_history"][-1]["observed_sim_ns"] == 1_039


def test_fixed_capture_source_values_are_immutable():
    result = json.loads((CAPTURE / "result.json").read_text(encoding="utf-8"))
    assert result["end_sim_ns"] == 2_620_000_000
    assert result["motion"]["support_steps"] == 0
    assert result["readiness"]["first_internal"]["internal_initialized"] is True
    assert result["readiness"]["first_internal"]["public_initialized"] is False
