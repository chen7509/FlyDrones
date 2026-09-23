from __future__ import annotations

import pytest

from flydrones.multitask_metrics import EpisodeTelemetry


def test_episode_telemetry_is_immutable_and_digest_is_deterministic():
    telemetry = EpisodeTelemetry(
        tracking_squared_error_sum=4.0,
        tracking_samples=2,
        tracking_lost_steps=1,
        union_coverage_cells=3,
        duplicate_coverage_visits=2,
        coverage_visits=5,
        formation_squared_error_sum=1.0,
        formation_samples=2,
        gate_crossings=1,
        gate_contacts=0,
        safety_failures=(),
        safety_overrides=1,
        completed_evidence=("exit:0",),
        central_control_commands=0,
        disturbance_injections={"wind": 5},
        disturbance_minimums={"wind": 0.2},
        disturbance_maximums={"wind": 0.4},
    )
    same = EpisodeTelemetry.from_dict(telemetry.to_dict())

    assert telemetry.digest == same.digest
    with pytest.raises(TypeError):
        telemetry.disturbance_injections["wind"] = 9


def test_episode_telemetry_rejects_nonfinite_or_inconsistent_counts():
    payload = EpisodeTelemetry.empty(("wind",)).to_dict()
    payload["tracking_squared_error_sum"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        EpisodeTelemetry.from_dict(payload)

    payload = EpisodeTelemetry.empty(("wind",)).to_dict()
    payload["duplicate_coverage_visits"] = 2
    payload["coverage_visits"] = 1
    with pytest.raises(ValueError, match="duplicate"):
        EpisodeTelemetry.from_dict(payload)
