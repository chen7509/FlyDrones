import math
import time
import warnings

import numpy as np
import torch

from flydrones.multitask_contract import (
    LocalObservation,
    PolicyIntent,
    SafetySnapshot,
    Skill,
)
from flydrones.multitask_policy import (
    CentralizedCritic,
    PolicyState,
    SafePolicy,
    SafetyArbiter,
    SafetyProjector,
    SharedRecurrentPolicy,
)


class StubActor:
    def __init__(self, motion=(0.5, 0.0, 0.0, 0.0), latency_s=0.0):
        self.motion = motion
        self.latency_s = latency_s

    def act(self, observation, state):
        time.sleep(self.latency_s)
        return Skill.SEARCH_COVER, self.motion, 0.9, PolicyState.zeros(64)


def observation():
    return LocalObservation.from_arrays(
        np.zeros(32),
        np.zeros(8),
        np.zeros(8),
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )


def healthy_snapshot():
    return SafetySnapshot(80.0, True, True, 2.0, False)


class FixedIntentActor:
    def __init__(self, intent):
        self.intent = intent

    def act(self, observation, state):
        return (
            self.intent.skill,
            self.intent.motion,
            self.intent.confidence,
            PolicyState.zeros(64),
        )


def test_arbiter_preflight_skips_actor_for_reflex_and_emergency():
    arbiter = SafetyArbiter(SafetyProjector())
    reflex = PolicyIntent(
        Skill.YIELD_RETURN_LAND, (0.0, 1.0, 0.0, 1.0), 1.0, 0.2
    )

    reflex_result = arbiter.preflight(healthy_snapshot(), reflex_override=reflex)
    emergency_result = arbiter.preflight(
        SafetySnapshot(80.0, True, True, 2.0, True)
    )

    assert reflex_result is not None and reflex_result.intent == reflex
    assert reflex_result.reason == "malecns-reflex"
    assert emergency_result is not None
    assert emergency_result.reason == "unhealthy"


def test_hard_clearance_preempts_reflex_motion():
    reflex = PolicyIntent(
        Skill.YIELD_RETURN_LAND, (1.0, 0.0, 0.0, 0.0), 1.0, 0.2
    )

    result = SafetyArbiter(SafetyProjector()).preflight(
        SafetySnapshot(80.0, True, True, 0.8, False),
        reflex_override=reflex,
    )

    assert result is not None
    assert result.reason == "low-clearance"
    assert result.intent.motion == (0.0, 0.0, 0.0, 0.0)


def test_safe_policy_and_training_path_resolve_identically():
    proposed = PolicyIntent(
        Skill.SEARCH_COVER, (0.3, 0.0, 0.0, 0.0), 0.9, 0.2
    )
    direct = SafetyArbiter(SafetyProjector()).resolve(
        proposed, healthy_snapshot(), now=1.0
    )
    wrapped = SafePolicy(FixedIntentActor(proposed), SafetyProjector()).act(
        observation(), PolicyState.zeros(64), healthy_snapshot(), now=1.0
    )

    assert direct.intent == wrapped.intent
    assert direct.overrode == wrapped.safety_overrode
    assert direct.reason == wrapped.reason


def test_safe_policy_accepts_valid_intent_and_projects_low_clearance():
    policy = SafePolicy(StubActor(), SafetyProjector(), maximum_latency_ms=35.0)
    healthy = SafetySnapshot(80.0, True, True, 2.0, False)
    accepted = policy.act(observation(), PolicyState.zeros(64), healthy)
    assert accepted.intent.skill is Skill.SEARCH_COVER
    close = policy.act(
        observation(),
        accepted.state,
        SafetySnapshot(80.0, True, True, 0.4, False),
    )
    assert close.intent.skill is Skill.YIELD_RETURN_LAND
    assert close.safety_overrode


def test_nan_and_late_actor_outputs_fall_back_deterministically():
    health = SafetySnapshot(80.0, True, True, 2.0, False)
    nan_result = SafePolicy(
        StubActor((math.nan, 0.0, 0.0, 0.0)), SafetyProjector()
    ).act(observation(), PolicyState.zeros(64), health)
    late_result = SafePolicy(
        StubActor(latency_s=0.01),
        SafetyProjector(),
        maximum_latency_ms=1.0,
    ).act(observation(), PolicyState.zeros(64), health)
    assert nan_result.intent.skill is Skill.YIELD_RETURN_LAND
    assert late_result.intent.motion == (0.0, 0.0, 0.0, 0.0)
    assert {nan_result.reason, late_result.reason} == {"invalid-output", "deadline"}


def test_frozen_malecns_reflex_preempts_learned_motion():
    policy = SafePolicy(StubActor(), SafetyProjector())
    reflex = PolicyIntent(
        Skill.YIELD_RETURN_LAND,
        (0.0, -1.0, 0.0, 0.0),
        1.0,
        0.2,
    )
    result = policy.act(
        observation(),
        PolicyState.zeros(64),
        SafetySnapshot(80.0, True, True, 2.0, False),
        reflex_override=reflex,
    )
    assert result.intent == reflex
    assert result.reason == "malecns-reflex"


def test_recurrent_actor_and_centralized_critic_have_training_shapes():
    torch.manual_seed(4)
    actor = SharedRecurrentPolicy()
    state = PolicyState.zeros(64)
    skill, motion, confidence, next_state = actor.act(observation(), state)
    assert skill in Skill
    assert len(motion) == 4
    assert 0.0 <= confidence <= 1.0
    assert next_state.hidden.shape == (64,)
    critic = CentralizedCritic(input_dimension=145)
    values = critic(torch.zeros((3, 145), dtype=torch.float32))
    assert values.shape == (3,)


def test_actor_accepts_immutable_contract_arrays_without_warning():
    actor = SharedRecurrentPolicy()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        actor.act(observation(), PolicyState.zeros(64))


def test_hard_safety_state_preempts_actor_execution():
    class ActorMustNotRun:
        def act(self, observation, state):
            raise AssertionError("unsafe state must bypass the learned actor")

    result = SafePolicy(ActorMustNotRun(), SafetyProjector()).act(
        observation(),
        PolicyState.zeros(64),
        SafetySnapshot(20.0, True, True, 2.0, False),
    )
    assert result.intent.skill is Skill.YIELD_RETURN_LAND
    assert result.reason == "low-battery"
    assert result.state.hidden.tolist() == [0.0] * 64
