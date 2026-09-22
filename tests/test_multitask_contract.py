import math

import numpy as np
import pytest

from flydrones.multitask_contract import (
    LocalObservation,
    PolicyIntent,
    SafetySnapshot,
    ScenarioManifest,
    Skill,
)


def valid_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "seed": 17,
        "world": "mixed",
        "fleet_size": 20,
        "active_skills": ["navigate_exit", "search_cover", "formation_rally"],
        "disturbances": ["wind", "packet_loss"],
        "failure_vehicle_ids": [3],
        "minimum_active_factors": 5,
    }


def test_manifest_is_strict_deterministic_and_rejects_duplicate_members():
    first = ScenarioManifest.from_dict(valid_manifest())
    second = ScenarioManifest.from_dict(valid_manifest())
    assert first.digest == second.digest
    bad = valid_manifest()
    bad["active_skills"] = ["navigate_exit", "navigate_exit"]
    with pytest.raises(ValueError, match="duplicate"):
        ScenarioManifest.from_dict(bad)


def test_actor_observation_rejects_nonfinite_wrong_length_and_stale_data():
    with pytest.raises(ValueError, match="visual_features"):
        LocalObservation.from_arrays(
            visual_features=np.array([0.0, math.nan]),
            flight_state=np.zeros(8),
            task_state=np.zeros(8),
            local_map=np.zeros(16),
            peer_summary=np.zeros(16),
            previous_action=np.zeros(4),
            validity=np.ones(6),
            maximum_age_s=0.5,
            age_s=0.1,
        )
    with pytest.raises(ValueError, match="stale"):
        LocalObservation.from_arrays(
            visual_features=np.zeros(32),
            flight_state=np.zeros(8),
            task_state=np.zeros(8),
            local_map=np.zeros(16),
            peer_summary=np.zeros(16),
            previous_action=np.zeros(4),
            validity=np.ones(6),
            maximum_age_s=0.5,
            age_s=0.6,
        )


def test_policy_intent_and_learning_health_are_fail_closed():
    checked = PolicyIntent(
        Skill.SEARCH_COVER,
        (2.0, -2.0, 0.5, 0.0),
        0.8,
        0.5,
    ).checked()
    assert checked.motion == (1.0, -1.0, 0.5, 0.0)
    with pytest.raises(ValueError, match="finite"):
        PolicyIntent(
            Skill.SEARCH_COVER,
            (math.nan, 0.0, 0.0, 0.0),
            0.8,
            0.5,
        ).checked()
    assert SafetySnapshot(80.0, True, True, 2.0, False).can_learn
    assert not SafetySnapshot(80.0, True, True, 2.0, True).can_learn
