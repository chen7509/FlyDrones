import math

import pytest

from flydrones.continual_learning import (
    CanaryController,
    CandidateMetrics,
    ContinualLearningGate,
    ResidualAdapter,
    SignedCheckpoint,
)
from flydrones.multitask_contract import SafetySnapshot


def checkpoint(version: str, payload: bytes = b"adapter"):
    return SignedCheckpoint.create(
        version,
        payload,
        key=b"test-secret",
        frozen_hash="f" * 64,
    )


def test_unsigned_wrong_base_and_unhealthy_candidates_never_promote():
    gate = ContinualLearningGate(
        key=b"test-secret",
        maximum_skill_drop=0.02,
        maximum_kl=0.05,
    )
    base = checkpoint("base")
    candidate = checkpoint("candidate")
    healthy = SafetySnapshot(80.0, True, True, 2.0, False)
    metrics = CandidateMetrics(
        True,
        0,
        0.01,
        {"search_cover": 0.96},
        {"search_cover": 0.95},
    )
    assert not gate.evaluate(base, candidate.tampered(), metrics, healthy).promote
    assert not gate.evaluate(
        base,
        candidate,
        metrics,
        SafetySnapshot(20.0, True, True, 2.0, False),
    ).promote
    wrong_base = SignedCheckpoint.create(
        "candidate",
        b"adapter",
        key=b"test-secret",
        frozen_hash="e" * 64,
    )
    assert not gate.evaluate(base, wrong_base, metrics, healthy).promote


def test_skill_regression_and_collision_block_promotion():
    gate = ContinualLearningGate(
        key=b"test-secret",
        maximum_skill_drop=0.02,
        maximum_kl=0.05,
    )
    base, candidate = checkpoint("base"), checkpoint("candidate")
    health = SafetySnapshot(80.0, True, True, 2.0, False)
    regression = CandidateMetrics(
        True,
        0,
        0.01,
        {"gate_course": 0.89},
        {"gate_course": 0.92},
    )
    collision = CandidateMetrics(
        True,
        1,
        0.01,
        {"gate_course": 0.93},
        {"gate_course": 0.92},
    )
    assert not gate.evaluate(base, candidate, regression, health).promote
    assert not gate.evaluate(base, candidate, collision, health).promote


def test_valid_shadow_candidate_can_promote():
    gate = ContinualLearningGate(
        key=b"test-secret",
        maximum_skill_drop=0.02,
        maximum_kl=0.05,
    )
    metrics = CandidateMetrics(
        True,
        0,
        0.01,
        {"search_cover": 0.96},
        {"search_cover": 0.95},
    )
    decision = gate.evaluate(
        checkpoint("base"),
        checkpoint("candidate"),
        metrics,
        SafetySnapshot(80.0, True, True, 2.0, False),
    )
    assert decision.promote
    assert decision.reasons == ()


def test_canary_rolls_back_on_first_safety_failure():
    stable, candidate = checkpoint("stable"), checkpoint("candidate")
    controller = CanaryController(stable)
    controller.activate(candidate, vehicle_id=7)
    controller.observe(vehicle_id=7, safety_failure="collision", latency_ms=4.0)
    assert controller.active.version == "stable"
    assert controller.rollback_reason == "collision"
    assert "payload" not in controller.peer_announcement()


def test_online_update_changes_only_bounded_adapter_parameters():
    adapter = ResidualAdapter.zeros(frozen_hash="f" * 64)
    updated = adapter.update(
        skill_advantages={"search_cover": 10.0},
        bid_errors=(2.0, -1.0),
        health=SafetySnapshot(80.0, True, True, 2.0, False),
        learning_rate=0.1,
    )
    assert updated.frozen_hash == adapter.frozen_hash
    assert 0.0 < updated.skill_bias["search_cover"] <= 0.05
    assert all(abs(value) <= 0.05 for value in updated.skill_bias.values())
    with pytest.raises(ValueError, match="healthy"):
        updated.update(
            skill_advantages={},
            bid_errors=(0.0, 0.0),
            health=SafetySnapshot(20.0, True, True, 2.0, False),
            learning_rate=0.1,
        )


def test_canary_rolls_back_on_nonfinite_or_excessive_latency():
    for latency in (math.nan, 35.01):
        controller = CanaryController(checkpoint("stable"))
        controller.activate(checkpoint("candidate"), vehicle_id=2)
        controller.observe(vehicle_id=2, safety_failure=None, latency_ms=latency)
        assert controller.active.version == "stable"
