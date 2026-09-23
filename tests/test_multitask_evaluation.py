from __future__ import annotations

import json
import math

import pytest

from flydrones.multitask_contract import PolicyIntent, ScenarioManifest, Skill
from flydrones.multitask_evaluation import evaluate_manifests
from flydrones.multitask_policy import PolicyState
from flydrones.multitask_reflex import ReflexDecision, ReflexEvidence


class TrackingActor:
    def __init__(self) -> None:
        self.calls = 0

    def act(self, observation, state):
        self.calls += 1
        return Skill.TRACK_TARGET, (0.0, 0.0, 0.0, 0.0), 0.9, PolicyState.zeros(64)


class RecordingNoopReflex:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, observation):
        self.calls += 1
        return ReflexDecision(
            None,
            ReflexEvidence(
                "malecns-v1.0-live", 166_700, 25_582_837, self.calls, 0, 1.0
            ),
        )


def manifest(*skills: Skill) -> ScenarioManifest:
    return ScenarioManifest.from_dict(
        {
            "schema_version": 1,
            "seed": 41,
            "world": "forest",
            "fleet_size": 1,
            "active_skills": [skill.value for skill in skills],
            "disturbances": [],
            "failure_vehicle_ids": [],
            "minimum_active_factors": len(skills),
        }
    )


def test_evaluator_uses_final_actions_and_measured_metrics():
    actor = TrackingActor()
    bridges: list[RecordingNoopReflex] = []

    def reflex_factory(vehicle_id, scenario):
        bridge = RecordingNoopReflex()
        bridges.append(bridge)
        return bridge

    result = evaluate_manifests(
        actor,
        [manifest(Skill.TRACK_TARGET)],
        reflex_factory=reflex_factory,
        max_steps=4,
    )

    assert result.reflex_calls == result.local_decisions == sum(
        bridge.calls for bridge in bridges
    )
    assert result.metrics["tracking_rmse_m"] == pytest.approx(
        math.sqrt(
            result.telemetry.tracking_squared_error_sum
            / result.telemetry.tracking_samples
        )
    )
    assert "999" not in json.dumps(result.to_dict())


def test_missing_evidence_is_structured_and_cannot_pass():
    result = evaluate_manifests(
        TrackingActor(),
        [manifest(Skill.NAVIGATE_EXIT)],
        reflex_factory=lambda vehicle_id, scenario: RecordingNoopReflex(),
        max_steps=2,
    )

    assert "formation_rmse_m" in result.missing_evidence
    assert "formation_rmse_m" not in result.metrics
    assert not result.admission.passed


def test_reflex_override_bypasses_actor_and_is_counted_as_final_action():
    actor = TrackingActor()

    class BrakeReflex(RecordingNoopReflex):
        def evaluate(self, observation):
            decision = super().evaluate(observation)
            return ReflexDecision(
                PolicyIntent(
                    Skill.YIELD_RETURN_LAND,
                    (0.0, 0.0, 0.0, 0.0),
                    1.0,
                    0.2,
                ),
                decision.evidence,
            )

    result = evaluate_manifests(
        actor,
        [manifest(Skill.TRACK_TARGET)],
        reflex_factory=lambda vehicle_id, scenario: BrakeReflex(),
        max_steps=3,
    )

    assert actor.calls == 0
    assert result.telemetry.safety_overrides == result.local_decisions
    assert "tracking_rmse_m" not in result.metrics
    assert "tracking_rmse_m" in result.missing_evidence


def test_cumulative_reflex_fallback_counter_is_not_added_each_step():
    class OneFallbackReflex(RecordingNoopReflex):
        def evaluate(self, observation):
            self.calls += 1
            return ReflexDecision(
                None,
                ReflexEvidence(
                    "malecns-v1.0-live", 166_700, 25_582_837, self.calls, 1, 1.0
                ),
            )

    result = evaluate_manifests(
        TrackingActor(),
        [manifest(Skill.NAVIGATE_EXIT)],
        reflex_factory=lambda vehicle_id, scenario: OneFallbackReflex(),
        max_steps=4,
    )

    assert result.reflex_calls == 4
    assert result.male_cns_fallbacks == 1
