"""Derived health must exactly reproduce the existing native-ack projection."""

import json

import pytest

from tests.benchmark.test_openvins_online_health import camera_ack
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence


def fixture(tmp_path):
    producer = OnlineHealthEvidence(tmp_path, session_id="online-native-322")
    states = []
    for i in range(250):
        row = camera_ack(2_000_000 + i * 100_000_000)
        row["sequence"] = i * 26 + 1
        row["imu_state"][3] = 1.0
        producer.observe_camera(row)
        states.append(row)
    result = producer.finish()
    return dict(
        states=states,
        records=[json.loads(line) for line in (tmp_path / "health-evidence.jsonl").read_text().splitlines()],
        terminal=result,
        shadow_last=result["last_health"],
        session_id="online-native-322",
        profile_name="px4-d6f12ad-gate-floor-v1",
    )


def call(**kw):
    function = getattr(audit, "audit_health_coverage_records", None)
    assert callable(function), "missing deterministic health replay API"
    return function(**kw)


def test_replay_actual_health_producer_without_promoting_quality(tmp_path):
    result = call(**fixture(tmp_path))
    assert result["camera_health_records"] == 250
    assert result["quality_values"] == [0]
    assert result["source_watchdog_qualified"] is False
    assert result["fusion_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "reordered",
        "projection",
        "sequence",
        "quality",
        "covariance",
        "reset",
        "session",
        "qualification",
        "terminal_last",
        "shadow_last",
        "raw_quality",
        "failure",
        "profile",
        "extra",
    ],
)
def test_health_corruption_refused(tmp_path, fault):
    f = fixture(tmp_path)
    row = f["records"][10]
    if fault == "missing":
        f["records"].pop()
    elif fault == "duplicate":
        f["records"].insert(10, row)
    elif fault == "reordered":
        f["records"][9], f["records"][10] = f["records"][10], f["records"][9]
    elif fault == "projection":
        row["projected"]["sample_ns"] += 1
    elif fault == "sequence":
        row["native_sequence"] += 1
    elif fault == "quality":
        row["health"]["quality"] = 1
    elif fault == "covariance":
        row["health"]["bounded_covariance15"][0][0] += 0.1
    elif fault == "reset":
        f["terminal"]["reset_total"] = 1
    elif fault == "session":
        f["session_id"] = "online-native-323"
    elif fault == "qualification":
        f["terminal"]["covariance_sim_domain_qualified"] = True
    elif fault == "terminal_last":
        f["terminal"]["last_quality"] = 1
    elif fault == "shadow_last":
        f["shadow_last"] = None
    elif fault == "raw_quality":
        f["states"][10]["quality"] = 0
    elif fault == "failure":
        row["event"] = "health_failure"
    elif fault == "profile":
        f["profile_name"] = "unfrozen-profile"
    elif fault == "extra":
        row["source_was_healthy"] = True
    with pytest.raises(ValueError):
        call(**f)
