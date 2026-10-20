import json
import shutil
from pathlib import Path

import pytest

from tools.benchmark.audit_source_watchdog_startup_cohort import audit
from tools.benchmark.openvins_online_shadow import SourceWatchdog

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v18/capture-v1"
DISPATCH = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v9-dispatch.json"
COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v9-completion.json"


def test_fixed_attempt_is_early_operational_transition_before_fresh_cohort():
    result = audit(CAPTURE, DISPATCH, COMPLETION)
    assert result["failure_evidence_qualified"] is True
    assert result["classification"] == "startup-readiness-before-fresh-source-cohort"
    assert result["imu_age_at_failure_ns"] == 2_079_562_030
    assert result["failure_after_ready_ns"] == 254_629
    assert result["next_imu_after_failure_ns"] == 713_794
    assert result["next_fresh_cohort_span_ns"] == 265_527_095
    assert result["candidate_fresh_cohort_qualified"] is True
    assert result["fruit_fly_policy_failure"] is False


def test_terminal_cause_drift_is_rejected(tmp_path):
    capture = tmp_path / "capture"
    shutil.copytree(CAPTURE, capture)
    value = json.loads((capture / "result.json").read_text(encoding="utf-8"))
    value["source_fanout"]["failure"] = "other"
    (capture / "result.json").write_text(json.dumps(value), encoding="utf-8")
    assert audit(capture, DISPATCH, COMPLETION)["failure_evidence_qualified"] is False


def test_watchdog_waits_for_fresh_cohort_without_changing_limits():
    guard = SourceWatchdog(timeout_ns=2_000_000_000, startup_timeout_ns=10_000_000_000)
    guard.start(100_000_000_000)
    guard.observe("imu", 101_000_000_000)
    guard.observe("info", 102_814_748_729)
    guard.observe("rgb", 103_079_307_401)
    assert guard.snapshot()["ready_ns"] is None
    guard.check(103_079_562_030)
    guard.observe("imu", 103_080_275_824)
    assert guard.snapshot()["ready_ns"] == 103_080_275_824
    assert guard.snapshot()["operational_timeout_ns"] == 2_000_000_000
    assert guard.snapshot()["startup_timeout_ns"] == 10_000_000_000


def test_watchdog_rejects_when_no_fresh_cohort_forms_before_startup_deadline():
    guard = SourceWatchdog(timeout_ns=200, startup_timeout_ns=1000)
    guard.start(1000)
    guard.observe("imu", 1010)
    guard.observe("rgb", 1800)
    guard.observe("info", 1900)
    assert guard.snapshot()["ready_ns"] is None
    with pytest.raises(TimeoutError, match="startup.*imu"):
        guard.check(2001)
