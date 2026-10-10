"""Retained subset provenance tests, not a complete capture qualification."""

import hashlib
import json
from pathlib import Path

import pytest

from tools.benchmark import audit_live_wire_safety as audit

FIXTURE = Path(__file__).parent / "fixtures/live_wire/retained-anchor-subset.json"


def retained():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "421c15f47dc7ff9e91891369df69ccbc08a8c1f5bc25ce894899dba93e0117d5"
    return json.loads(raw)


def run(value):
    fn = getattr(audit, "audit_anchor_records", None)
    assert callable(fn), "anchor attribution API missing"
    return fn(**value)


def test_retained_anchor_subset_binds_sources_without_live_authority():
    result = run(retained())
    assert result["recorded_anchor_attribution_passed"] is True
    assert result["heartbeat_wall_age_ns"] > 2_000_000_000
    assert result["heartbeat_sim_age_ns"] == 975_000_000
    assert result["per_step_readiness_calls_observed"] is False
    assert result["live_qualified"] is False
    assert result["fusion_qualified"] is False


@pytest.mark.parametrize(
    "case",
    [
        "missing_source",
        "source_changed",
        "source_duplicate",
        "missing_delivery",
        "partial_delivery",
        "source_hash",
        "receipt_outside_call",
        "commit_after_anchor",
        "missing_heartbeat",
        "heartbeat_hash",
        "heartbeat_reconcile",
        "armed",
        "pending_heartbeat",
        "heartbeat_late",
        "missing_estimator",
        "native_changed",
        "estimator_source",
        "estimator_clock",
        "first_estimator",
        "freshness",
        "truth",
        "boolean_sequence",
        "unknown_proof",
    ],
)
def test_anchor_refuses_unbound_or_corrupted_record(case):
    value = retained()
    proof = value["anchor"]["proof"]
    if case == "missing_source":
        value["sources"].pop()
    elif case == "source_changed":
        value["sources"][-1]["arrival_monotonic_ns"] += 1
    elif case == "source_duplicate":
        value["sources"].append(value["sources"][-1])
    elif case == "missing_delivery":
        value["fanout"].pop()
    elif case == "partial_delivery":
        value["fanout"][-1]["dispositions"]["readiness"] = "not_attempted"
    elif case == "source_hash":
        value["fanout"][-1]["source_sha256"] = "0" * 64
    elif case == "receipt_outside_call":
        proof["records"]["rgb"]["journal_ack_monotonic_ns"] = 1
    elif case == "commit_after_anchor":
        value["fanout"][-1]["end_ns"] = proof["checked_wall_ns"] + 1
    elif case == "missing_heartbeat":
        value["heartbeat_records"] = []
    elif case == "heartbeat_hash":
        value["heartbeat_records"][0]["source_sha256"] = "0" * 64
    elif case == "heartbeat_reconcile":
        value["heartbeat_records"][1]["source_sequence"] += 1
    elif case == "armed":
        proof["records"]["heartbeat"]["base_mode"] = 128
    elif case == "pending_heartbeat":
        value["heartbeat_records"].pop()
    elif case == "heartbeat_late":
        value["heartbeat_records"][1]["reconciled_ns"] += 3_000_000_000
    elif case == "missing_estimator":
        value["estimator_records"] = []
    elif case == "native_changed":
        value["acknowledgements"][0]["public_initialized"] = True
    elif case == "estimator_source":
        value["estimator_records"][0]["source_sequence"] -= 1
    elif case == "estimator_clock":
        value["estimator_records"][0]["journal_ack_monotonic_ns"] = proof["checked_wall_ns"] + 1
    elif case == "first_estimator":
        proof["first_estimator_internal"]["sample_ns"] += 1
    elif case == "freshness":
        proof["freshness"]["heartbeat_sim_limit_ns"] += 1
    elif case == "truth":
        proof["truth_used"] = True
    elif case == "boolean_sequence":
        value["heartbeat_records"][0]["observation_sequence"] = False
    elif case == "unknown_proof":
        proof["qualified"] = True
    with pytest.raises(ValueError):
        run(value)
