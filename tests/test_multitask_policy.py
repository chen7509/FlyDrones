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


def test_hard_clearance_uses_sensor_derived_recovery_motion():
    reflex = PolicyIntent(
        Skill.YIELD_RETURN_LAND, (1.0, 0.0, 0.0, 0.0), 1.0, 0.2
    )

    result = SafetyArbiter(SafetyProjector()).preflight(
        SafetySnapshot(
            80.0,
            True,
            True,
            0.8,
            False,
            recovery_motion=(0.0, 0.0, 1.0, 0.0),
        ),
        reflex_override=reflex,
    )

    assert result is not None
    assert result.reason == "low-clearance"
    assert result.intent.motion == (0.0, 0.0, 1.0, 0.0)


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


def test_actor_never_selects_a_skill_outside_the_active_task_mask():
    actor = SharedRecurrentPolicy()
    with torch.no_grad():
        actor.skill_head.weight.zero_()
        actor.skill_head.bias.copy_(torch.tensor((0.0, 9.0, 8.0, 7.0, 6.0, 5.0)))
    base = observation()
    task_state = base.task_state.copy()
    task_state[0] = 1.0
    masked = LocalObservation.from_arrays(
        base.visual_features,
        base.flight_state,
        task_state,
        base.local_map,
        base.peer_summary,
        base.previous_action,
        base.validity,
        maximum_age_s=base.maximum_age_s,
        age_s=base.age_s,
    )

    skill, _motion, _confidence, _state = actor.act(masked, PolicyState.zeros(64))

    assert skill is Skill.NAVIGATE_EXIT


def test_paired_tracking_and_search_use_local_roles_for_task_assignment():
    actor = SharedRecurrentPolicy()
    logits = torch.tensor(
        (
            (0.0, 9.0, 10.0, 0.0, 0.0, 0.0),
            (0.0, 10.0, 9.0, 0.0, 0.0, 0.0),
        )
    )
    observations = torch.zeros((2, SharedRecurrentPolicy.input_dimension))
    observations[:, SharedRecurrentPolicy.task_state_offset + 1] = 1.0
    observations[:, SharedRecurrentPolicy.task_state_offset + 2] = 1.0
    observations[0, SharedRecurrentPolicy.task_state_offset + 7] = 0.0
    observations[1, SharedRecurrentPolicy.task_state_offset + 7] = -1.0

    masked = actor.mask_skill_logits(logits, observations)

    assert torch.argmax(masked[0]).item() == 1
    assert torch.argmax(masked[1]).item() == 2


def test_four_task_compound_policy_assigns_roles_without_central_commands():
    actor = SharedRecurrentPolicy()
    logits = torch.zeros((5, SharedRecurrentPolicy.skill_dimension))
    observations = torch.zeros((5, SharedRecurrentPolicy.input_dimension))
    observations[:, SharedRecurrentPolicy.task_state_offset:
                 SharedRecurrentPolicy.task_state_offset + 4] = 1.0
    observations[:, SharedRecurrentPolicy.task_state_offset + 7] = torch.tensor(
        (-0.9, -0.7, 0.0, 0.8, 0.95)
    )

    masked = actor.mask_skill_logits(logits, observations)

    assert torch.argmax(masked, dim=-1).tolist() == [0, 1, 2, 2, 3]


def test_navigation_only_actor_starts_from_a_local_goal_motion_prior():
    actor = SharedRecurrentPolicy()
    visual = np.concatenate(
        (np.zeros(19), np.asarray((1.0, 0.0, 0.1)), np.zeros(10))
    )
    visual[25:27] = (0.1, -0.2)
    scenario = LocalObservation.from_arrays(
        visual,
        np.zeros(8),
        np.asarray((1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion, (0.895037, 0.2, 0.099504, 0.0), atol=1e-5)


def test_tracking_only_actor_approaches_a_five_metre_standoff():
    actor = SharedRecurrentPolicy()
    visual = np.zeros(32)
    visual[16:19] = (0.3, 0.0, 0.0)
    visual[25:27] = (0.1, -0.2)
    visual[30:32] = (0.0, 0.5)
    scenario = LocalObservation.from_arrays(
        visual,
        np.zeros(8),
        np.asarray((0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion, (0.1, 0.7, 0.0, 0.0), atol=1e-6)


def test_guided_task_residual_cannot_overpower_the_motion_prior():
    actor = SharedRecurrentPolicy()
    with torch.no_grad():
        actor.motion_head.bias.fill_(100.0)
    visual = np.zeros(32)
    visual[16:19] = (0.3, 0.0, 0.0)
    visual[30:32] = (0.0, 0.5)
    scenario = LocalObservation.from_arrays(
        visual,
        np.zeros(8),
        np.asarray((0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion, (0.21, 0.51, 0.01, 0.01), atol=1e-6)


def test_search_only_actor_targets_its_assigned_unvisited_lane_cell():
    actor = SharedRecurrentPolicy()
    flight = np.zeros(8)
    flight[2] = 8.0 / 30.0
    task = np.zeros(8)
    task[2] = 1.0
    task[-1] = -1.0
    coverage = np.zeros(16)
    coverage[0] = 1.0
    scenario = LocalObservation.from_arrays(
        np.zeros(32),
        flight,
        task,
        coverage,
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )
    expected = np.asarray((31.25, -45.0, 0.0))
    expected /= np.linalg.norm(expected)

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion[:3], expected, atol=1e-6)
    assert motion[3] == 0.0


def test_formation_only_actor_uses_a_role_separated_rally_slot():
    actor = SharedRecurrentPolicy()
    flight = np.zeros(8)
    flight[:3] = (0.0, 5.0 / 60.0, 8.0 / 30.0)
    task = np.zeros(8)
    task[3] = 1.0
    task[-1] = 0.0
    scenario = LocalObservation.from_arrays(
        np.zeros(32),
        flight,
        task,
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )
    expected = np.asarray((10.0, -5.0, 0.0))
    expected /= np.linalg.norm(expected)

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion[:3], expected, atol=1e-6)


def test_gate_only_actor_aims_beyond_the_gate_in_a_role_separated_slot():
    actor = SharedRecurrentPolicy()
    visual = np.zeros(32)
    visual[22:25] = (0.1, 0.0, 0.05)
    task = np.zeros(8)
    task[4] = 1.0
    task[-1] = 0.5
    scenario = LocalObservation.from_arrays(
        visual,
        np.zeros(8),
        task,
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )
    expected = np.asarray((0.35, 0.0375, 0.05))
    expected /= np.linalg.norm(expected)

    _skill, motion, _confidence, _state = actor.act(
        scenario, PolicyState.zeros(64)
    )

    np.testing.assert_allclose(motion[:3], expected, atol=1e-6)


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
