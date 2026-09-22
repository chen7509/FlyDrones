# Multi-task Continual Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic multi-task simulation and training foundation that combines eight mission capabilities, preserves decentralized execution, and permits only gated high-level continual adaptation.

**Architecture:** Add strict immutable contracts first, then a seeded compound-scenario generator and Gymnasium environment. A shared recurrent actor selects a finite skill and proposes bounded local motion; a frozen safety projector and the existing `MissionAgent` remain authoritative. Continual learning updates only a signed residual adapter through shadow evaluation, regression gates, canary activation, and automatic rollback.

**Tech Stack:** Python 3.10+, dataclasses, NumPy, Gymnasium, PyTorch through the existing `learning` extra, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-multitask-continual-learning-design.md`

## Global Constraints

- Deployment actors receive only local observations and finite neighbor summaries; simulator global truth is confined to `critic_observation` during offline training.
- MaleCNS reflexes, deterministic safety limits, action projection, geofence, return threshold, and PX4 inner loops are frozen.
- Learning output is a local target or velocity intention and never motor thrust.
- Existing task leases, consensus, completion evidence, battery return, and failure reassignment remain authoritative.
- Deployed execution accepts no central per-aircraft waypoint, velocity, attitude, or collision-avoidance command.
- Online updates affect only high-level skill selection, bid estimates, and bounded skill parameters; executable weights are never accepted directly from peers.
- Every scenario, result, checkpoint, and promotion record carries seed, schema version, code/model identity, and deterministic hashes.
- A collision, geofence violation, depleted return reserve, or safety bypass is a hard evaluation failure.

## Review Focus

- Non-finite, wrong-length, stale, or missing observation fields must fail closed instead of reaching the policy; Task 1 pins this behavior.
- A compound scenario request that cannot satisfy required axes must raise a deterministic validation error instead of silently weakening the scenario; Task 2 pins this behavior.
- Simulator global truth must never be present in the actor observation even though the critic receives it; Task 3 pins this separation.
- NaN, late, out-of-range, or unsafe policy intentions must be replaced by a deterministic safe action; Task 4 pins this behavior.
- Unsigned, incompatible, degraded, or regression-causing online candidates must remain in shadow mode and trigger rollback if already canaried; Task 6 pins this behavior.

---

### Task 1: Immutable Multi-task Contracts

**Files:**
- Create: `src/flydrones/multitask_contract.py`
- Create: `tests/test_multitask_contract.py`

**Interfaces:**
- Consumes: no new project interface; uses standard-library dataclasses, enums, hashing, JSON, and finite-number validation patterns from `mission_contract.py`.
- Produces: `Skill`, `WorldKind`, `ScenarioManifest.from_dict()`, `ScenarioManifest.digest`, `LocalObservation.from_arrays()`, `PolicyIntent.checked()`, and `SafetySnapshot.can_learn`.

- [ ] **Step 1: Write failing contract tests**

```python
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
    assert PolicyIntent(Skill.SEARCH_COVER, (2.0, -2.0, 0.5, 0.0), 0.8, 0.5).checked().motion == (1.0, -1.0, 0.5, 0.0)
    with pytest.raises(ValueError, match="finite"):
        PolicyIntent(Skill.SEARCH_COVER, (math.nan, 0.0, 0.0, 0.0), 0.8, 0.5).checked()
    assert not SafetySnapshot(80.0, True, True, 2.0, False).can_learn
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `pytest tests/test_multitask_contract.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'flydrones.multitask_contract'`.

- [ ] **Step 3: Implement the strict contracts**

Create enums with exact serialized values:

```python
class Skill(str, Enum):
    NAVIGATE_EXIT = "navigate_exit"
    TRACK_TARGET = "track_target"
    SEARCH_COVER = "search_cover"
    FORMATION_RALLY = "formation_rally"
    GATE_COURSE = "gate_course"
    YIELD_RETURN_LAND = "yield_return_land"


class WorldKind(str, Enum):
    FOREST = "forest"
    BUILDING = "building"
    MIXED = "mixed"
```

Implement `ScenarioManifest` as a frozen dataclass with the keys exercised above, exact-key checking, fleet range `1..100`, unique skills/disturbances/failure IDs, failure IDs inside the fleet, `minimum_active_factors >= 1`, and a canonical SHA-256 digest. Count active factors as `len(active_skills) + len(disturbances) + bool(failure_vehicle_ids)` and reject manifests below their declared minimum.

Implement `LocalObservation` with exact component lengths `(32, 8, 8, 16, 16, 4, 6)`, float32 immutable arrays, finite checks, binary validity mask, non-negative age, positive maximum age, and stale rejection. Its `actor_vector()` concatenates only those seven local components and its `dimension` is `90`.

Implement `PolicyIntent.checked()` to require four finite motion values, clip them to `[-1, 1]`, require confidence in `[0, 1]`, and require positive finite hold time. Implement `SafetySnapshot.can_learn` as true only when battery is at least 35%, localization and sensors are healthy, clearance is at least 1 metre, and no emergency is active.

- [ ] **Step 4: Run contract tests and the existing contract suites**

Run: `pytest tests/test_multitask_contract.py tests/test_mission_contract.py tests/test_task_consensus.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/flydrones/multitask_contract.py tests/test_multitask_contract.py
git commit -m "feat: add multitask learning contracts"
```

### Task 2: Seeded Compound Scenario Generator

**Files:**
- Create: `src/flydrones/multitask_scenarios.py`
- Create: `tests/test_multitask_scenarios.py`

**Interfaces:**
- Consumes: `ScenarioManifest`, `Skill`, and `WorldKind` from Task 1.
- Produces: `ScenarioGenerator(seed: int)`, `ScenarioGenerator.generate(level: int, fleet_size: int) -> ScenarioManifest`, and `ScenarioGenerator.held_out(seeds: Iterable[int], level: int, fleet_size: int) -> tuple[ScenarioManifest, ...]`.

- [ ] **Step 1: Write failing deterministic and compound-stage tests**

```python
import pytest

from flydrones.multitask_contract import Skill
from flydrones.multitask_scenarios import ScenarioGenerator


def test_same_seed_produces_identical_manifest_and_different_seed_changes_it():
    a = ScenarioGenerator(41).generate(level=4, fleet_size=100)
    b = ScenarioGenerator(41).generate(level=4, fleet_size=100)
    c = ScenarioGenerator(42).generate(level=4, fleet_size=100)
    assert a == b
    assert a.digest == b.digest
    assert a.digest != c.digest


def test_level_four_contains_all_skills_and_required_failure_mix():
    manifest = ScenarioGenerator(8).generate(level=4, fleet_size=100)
    assert set(manifest.active_skills) == set(Skill)
    assert manifest.failure_vehicle_ids
    assert {"packet_loss", "battery_variation"} <= set(manifest.disturbances)
    assert len(manifest.active_skills) + len(manifest.disturbances) + 1 >= 8


def test_invalid_level_and_impossible_fleet_are_rejected():
    with pytest.raises(ValueError, match="level"):
        ScenarioGenerator(1).generate(level=9, fleet_size=20)
    with pytest.raises(ValueError, match="fleet"):
        ScenarioGenerator(1).generate(level=4, fleet_size=1)
```

- [ ] **Step 2: Run scenario tests and verify RED**

Run: `pytest tests/test_multitask_scenarios.py -q`

Expected: collection fails because `flydrones.multitask_scenarios` does not exist.

- [ ] **Step 3: Implement level-specific generation**

Use `numpy.random.default_rng(seed)` without module-global random state. Define exact level rules:

```python
LEVEL_SKILL_COUNTS = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}
LEVEL_MINIMUM_FACTORS = {0: 1, 1: 2, 2: 4, 3: 5, 4: 8}
```

Level 0 generates the navigation regression baseline. Level 1 samples one primary skill and one sensor/environment disturbance. Level 2 samples two skills and at least two disturbances. Level 3 samples four skills, three disturbances, and at least one failed node for fleets of five or more. Level 4 uses all six policy skills, includes `wind`, `packet_loss`, `battery_variation`, `sensor_noise`, and selects `max(1, round(fleet_size * 0.1))` unique failed vehicle IDs; reject level 4 for fleets smaller than five. Choose the world deterministically from forest, building, and mixed, with level 4 fixed to mixed.

`held_out()` must reject duplicate seeds and return manifests sorted by seed so report order never depends on input order.

- [ ] **Step 4: Run scenario and contract tests**

Run: `pytest tests/test_multitask_scenarios.py tests/test_multitask_contract.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/flydrones/multitask_scenarios.py tests/test_multitask_scenarios.py
git commit -m "feat: generate reproducible compound scenarios"
```

### Task 3: Local-observation Multi-agent Gym Environment

**Files:**
- Create: `src/flydrones/multitask_env.py`
- Create: `tests/test_multitask_env.py`

**Interfaces:**
- Consumes: `ScenarioManifest`, `LocalObservation`, `PolicyIntent`, and `Skill` from Task 1.
- Produces: `MultiTaskEnv(manifest: ScenarioManifest, max_steps: int = 400)`, multi-agent `reset()`/`step()`, `actor_observation(vehicle_id: int) -> np.ndarray`, and `critic_observation() -> np.ndarray`.

- [ ] **Step 1: Write failing environment boundary tests**

```python
import numpy as np
import pytest

from flydrones.multitask_contract import PolicyIntent, Skill
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_scenarios import ScenarioGenerator


def test_reset_is_seeded_and_actor_has_no_global_truth():
    manifest = ScenarioGenerator(13).generate(level=3, fleet_size=20)
    left = MultiTaskEnv(manifest)
    right = MultiTaskEnv(manifest)
    left_actors, left_info = left.reset(seed=13)
    right_actors, right_info = right.reset(seed=13)
    assert set(left_actors) == set(range(20))
    np.testing.assert_array_equal(left_actors[0], right_actors[0])
    assert left_actors[0].shape == (90,)
    assert left.single_observation_space.shape == (90,)
    assert left.critic_observation().shape[0] > left_actors[0].shape[0]
    assert "global_positions" not in left_info
    assert left_info["manifest_digest"] == right_info["manifest_digest"]


def test_collision_is_a_hard_failure_and_not_only_a_reward_penalty():
    env = MultiTaskEnv(ScenarioGenerator(2).generate(level=1, fleet_size=1))
    env.reset(seed=2)
    env._debug_set_clearance_m(0, -0.01)
    _, rewards, terminated, _, info = env.step({
        0: PolicyIntent(Skill.NAVIGATE_EXIT, (1.0, 0.0, 0.0, 0.0), 1.0, 0.5)
    })
    assert terminated
    assert rewards[0] <= -100.0
    assert info["safety_failure"] == "collision"


def test_step_rejects_central_or_wrong_action_types():
    env = MultiTaskEnv(ScenarioGenerator(2).generate(level=1, fleet_size=1))
    env.reset(seed=2)
    with pytest.raises(TypeError, match="PolicyIntent"):
        env.step({0: np.zeros(4)})
```

- [ ] **Step 2: Run environment tests and verify RED**

Run: `pytest tests/test_multitask_env.py -q`

Expected: collection fails because `flydrones.multitask_env` does not exist.

- [ ] **Step 3: Implement the environment core**

Implement a fast 2.5-D kinematic world with local depth rays, moving target, local coverage bitmap, gate plane, formation slot, battery drain, peer summaries, packet-loss masking, wind, sensor noise, and manifest-selected node failures. Keep simulator arrays private. `reset()` returns an observation mapping for every active vehicle. `step()` requires a mapping from every non-failed active vehicle ID to one `PolicyIntent` and returns per-vehicle observations and rewards plus joint termination flags. `actor_observation(vehicle_id)` must construct only `LocalObservation.actor_vector()`. `critic_observation()` may concatenate actor values with obstacle, target, gate, global fleet, failure, and full coverage truth.

`step()` accepts only the typed action mapping, calls `.checked()` on each intention, applies bounded kinematics, updates each active objective, and returns an auditable per-vehicle `reward_terms` mapping. Missing, extra, or failed vehicle IDs raise `ValueError`. Set `terminated=True`, the affected vehicle reward to at most `-100`, and a `safety_failure` reason on collision, geofence violation, or return-reserve violation. Successful task evidence is exposed as immutable IDs, never inferred from reward alone. `_debug_set_clearance_m(vehicle_id, clearance_m)` is a test-only state injection method whose name and docstring make that boundary explicit.

- [ ] **Step 4: Run environment, autonomous forest, and Gymnasium contract tests**

Run: `pytest tests/test_multitask_env.py tests/test_autonomy.py -q`

Expected: all selected tests pass without Gymnasium checker warnings.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/flydrones/multitask_env.py tests/test_multitask_env.py
git commit -m "feat: add local-observation multitask environment"
```

### Task 4: Recurrent Skill Policy and Frozen Safety Projection

**Files:**
- Create: `src/flydrones/multitask_policy.py`
- Create: `tests/test_multitask_policy.py`

**Interfaces:**
- Consumes: `LocalObservation`, `PolicyIntent`, `SafetySnapshot`, and `Skill` from Task 1.
- Produces: `PolicyState`, `SharedRecurrentPolicy.act()`, `CentralizedCritic.forward()`, `SafetyProjector.project()`, and `SafePolicy.act()`.

- [ ] **Step 1: Write failing policy and fail-closed tests**

```python
import math
import time

import numpy as np

from flydrones.multitask_contract import LocalObservation, PolicyIntent, SafetySnapshot, Skill
from flydrones.multitask_policy import PolicyState, SafePolicy, SafetyProjector


class StubActor:
    def __init__(self, motion=(0.5, 0.0, 0.0, 0.0), latency_s=0.0):
        self.motion = motion
        self.latency_s = latency_s

    def act(self, observation, state):
        time.sleep(self.latency_s)
        return Skill.SEARCH_COVER, self.motion, 0.9, PolicyState.zeros(64)


def observation():
    return LocalObservation.from_arrays(
        np.zeros(32), np.zeros(8), np.zeros(8), np.zeros(16),
        np.zeros(16), np.zeros(4), np.ones(6), maximum_age_s=0.5, age_s=0.0,
    )


def test_safe_policy_accepts_valid_intent_and_projects_low_clearance():
    policy = SafePolicy(StubActor(), SafetyProjector(), maximum_latency_ms=35.0)
    healthy = SafetySnapshot(80.0, True, True, 2.0, False)
    accepted = policy.act(observation(), PolicyState.zeros(64), healthy)
    assert accepted.intent.skill is Skill.SEARCH_COVER
    close = policy.act(observation(), accepted.state, SafetySnapshot(80.0, True, True, 0.4, False))
    assert close.intent.skill is Skill.YIELD_RETURN_LAND
    assert close.safety_overrode


def test_nan_and_late_actor_outputs_fall_back_deterministically():
    health = SafetySnapshot(80.0, True, True, 2.0, False)
    nan_result = SafePolicy(StubActor((math.nan, 0.0, 0.0, 0.0)), SafetyProjector()).act(
        observation(), PolicyState.zeros(64), health
    )
    late_result = SafePolicy(StubActor(latency_s=0.01), SafetyProjector(), maximum_latency_ms=1.0).act(
        observation(), PolicyState.zeros(64), health
    )
    assert nan_result.intent.skill is Skill.YIELD_RETURN_LAND
    assert late_result.intent.motion == (0.0, 0.0, 0.0, 0.0)
    assert {nan_result.reason, late_result.reason} == {"invalid-output", "deadline"}


def test_frozen_malecns_reflex_preempts_learned_motion():
    policy = SafePolicy(StubActor(), SafetyProjector())
    reflex = PolicyIntent(Skill.YIELD_RETURN_LAND, (0.0, -1.0, 0.0, 0.0), 1.0, 0.2)
    result = policy.act(
        observation(), PolicyState.zeros(64),
        SafetySnapshot(80.0, True, True, 2.0, False),
        reflex_override=reflex,
    )
    assert result.intent == reflex
    assert result.reason == "malecns-reflex"
```

- [ ] **Step 2: Run policy tests and verify RED**

Run: `pytest tests/test_multitask_policy.py -q`

Expected: collection fails because `flydrones.multitask_policy` does not exist.

- [ ] **Step 3: Implement policy state, actor, and safety wrapper**

`PolicyState.zeros(size)` returns an immutable finite float32 hidden vector. `SharedRecurrentPolicy` uses a PyTorch GRU with input 90, hidden 64, a six-logit skill head, four-value `tanh` motion head, and sigmoid confidence head. `CentralizedCritic` receives only `MultiTaskEnv.critic_observation()` during training and returns one scalar value per active vehicle; its object is not serialized into the deployment actor artifact. Export/import methods persist a versioned actor state dict and architecture metadata; importing a wrong input, hidden, or skill dimension raises `ValueError`.

`SafetyProjector.project()` applies the following fixed rules in order: emergency or invalid health returns zero-motion `YIELD_RETURN_LAND`; a valid frozen MaleCNS `reflex_override` preempts learned motion; battery below 35% returns a bounded home-directed return intent; clearance below 0.65 m sets forward motion at most zero and creates a turn-away/yield intent; otherwise it returns the checked learning intent. `SafePolicy.act()` measures wall-clock latency, catches non-finite/shape errors, and returns a `SafePolicyResult(intent, state, safety_overrode, reason, latency_ms)`.

Add skill hysteresis: a proposed new skill must win for two consecutive policy decisions unless the current hold time expired, task completion was signaled, or safety preempted it.

- [ ] **Step 4: Run policy, binary behavior, and local planner tests**

Run: `pytest tests/test_multitask_policy.py tests/test_binary_behavior.py tests/test_local_planner.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/flydrones/multitask_policy.py tests/test_multitask_policy.py
git commit -m "feat: add recurrent skill policy safety boundary"
```

### Task 5: Learned Estimates Through Existing Mission Authority

**Files:**
- Create: `src/flydrones/mission_learning.py`
- Create: `tests/test_mission_learning.py`
- Modify: `src/flydrones/mission_agent.py`
- Modify: `tests/test_mission_agent.py`

**Interfaces:**
- Consumes: `WorkUnit`, `AgentState`, `MissionAgent.step(preferred_task_ids=...)`, and Task 4 policy intentions.
- Produces: `TaskEstimate`, `MissionLearningAdapter.rank_work_units()`, `MissionLearningAdapter.preferred_task_ids()`, and optional `MissionAgent(..., learning_adapter=None)`.

- [ ] **Step 1: Write failing authority-boundary tests**

```python
from dataclasses import replace

from flydrones.mission_agent import AgentState, MissionAgent
from flydrones.mission_contract import MissionContract
from flydrones.mission_learning import MissionLearningAdapter, TaskEstimate


def contract():
    return MissionContract.from_dict({
        "schema_version": 1, "mission_id": "learning-test",
        "mission_type": "search_confirm_rally",
        "area_polygon_m": [[0, 0], [40, 0], [40, 40], [0, 40]],
        "search_cell_size_m": 20, "target_classes": ["person"],
        "confirmation_quorum": 2, "rally_position_m": [50, 20, 20],
        "deadline_s": 60,
        "safety": {"maximum_speed_mps": 8, "minimum_separation_m": 3,
                   "geofence_margin_m": 5, "minimum_battery_return_pct": 30},
    })


def state(**changes):
    values = {"position_m": (10.0, 10.0, 20.0), "velocity_mps": (0.0, 0.0, 0.0),
              "battery_pct": 90.0, "depth_age_s": 0.0, "localization_valid": True}
    values.update(changes)
    return AgentState(**values)


def test_adapter_only_ranks_known_work_units_and_never_mutates_ledger():
    agent = MissionAgent.for_contract(0, 5, contract())
    before = agent.ledger.snapshot()
    adapter = MissionLearningAdapter(
        lambda unit, _: TaskEstimate(unit.task_id, 5.0, 2.0, 0.8)
    )
    ranked = adapter.preferred_task_ids(agent, state())
    assert set(ranked) <= set(agent.work_unit_ids)
    assert agent.ledger.snapshot() == before


def test_unknown_nonfinite_and_low_battery_estimates_are_ignored():
    agent = MissionAgent.for_contract(0, 5, contract())
    bad = MissionLearningAdapter(
        lambda unit, _: TaskEstimate("invented-task", float("nan"), -1.0, 2.0)
    )
    assert bad.preferred_task_ids(agent, state()) == ()
    low = replace(state(), battery_pct=contract().safety.minimum_battery_return_pct)
    assert bad.preferred_task_ids(agent, low) == ()


def test_mission_safety_preempts_learned_preference():
    agent = MissionAgent.for_contract(0, 5, contract())
    decision = agent.step(
        0.0, state(battery_pct=30.0), (), (), (),
        preferred_task_ids=(agent.work_unit_ids[0],),
    )
    assert decision.safety_phase == "return"
    assert decision.intent.source == "safety-return"
```

- [ ] **Step 2: Run mission-learning tests and verify RED**

Run: `pytest tests/test_mission_learning.py -q`

Expected: collection fails because `flydrones.mission_learning` does not exist.

- [ ] **Step 3: Implement the narrow estimation adapter**

`TaskEstimate` contains `task_id`, `duration_s`, `energy_pct`, and `success_probability`. Validation requires a known ID, finite non-negative duration and energy, and probability in `[0, 1]`. Ranking score is `100 * probability - duration_s - 2 * energy_pct`, descending with task ID as deterministic tie-breaker.

`MissionLearningAdapter.rank_work_units(units, state)` validates and sorts estimates. `preferred_task_ids(agent, state)` returns an empty tuple when battery is at or below the existing return threshold or the estimator raises/returns invalid data. It may call public `agent.work_unit()` and `agent.work_unit_ids`; it must not call ledger mutation methods.

Add an optional adapter to `MissionAgent.__init__()` and `for_contract()`. At the start of nominal bidding, merge explicit `preferred_task_ids` with adapter preferences while preserving explicit order. Existing safety checks run before this call and existing `_allocate_or_renew()` retains ownership authority.

Define the agent-facing surface as a `Protocol` in `mission_learning.py` and place concrete `MissionAgent` imports under `TYPE_CHECKING` to avoid a circular import. Keep `mission_learning.py` free of NumPy, PyTorch, and training-framework imports so the existing 100-process lightweight-import test continues to pass.

- [ ] **Step 4: Run mission integration and consensus tests**

Run: `pytest tests/test_mission_learning.py tests/test_mission_agent.py tests/test_task_consensus.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add src/flydrones/mission_learning.py src/flydrones/mission_agent.py tests/test_mission_learning.py tests/test_mission_agent.py
git commit -m "feat: connect learned estimates to mission bidding"
```

### Task 6: Shadow Continual-learning Gate and Rollback

**Files:**
- Create: `src/flydrones/continual_learning.py`
- Create: `tests/test_continual_learning.py`

**Interfaces:**
- Consumes: `SafetySnapshot`, `PolicyIntent`, per-skill evaluation metrics, and frozen parameter hashes.
- Produces: `ResidualAdapter.update()`, `ShadowPolicyRunner.compare()`, `SignedCheckpoint`, `CandidateMetrics`, `PromotionDecision`, `ContinualLearningGate.evaluate()`, `CanaryController.activate()`, and `CanaryController.observe()`.

- [ ] **Step 1: Write failing signature, health, regression, and rollback tests**

```python
from flydrones.continual_learning import (
    CanaryController,
    CandidateMetrics,
    ContinualLearningGate,
    ResidualAdapter,
    SignedCheckpoint,
)
from flydrones.multitask_contract import SafetySnapshot


def checkpoint(version: str, payload: bytes = b"adapter"):
    return SignedCheckpoint.create(version, payload, key=b"test-secret", frozen_hash="f" * 64)


def test_unsigned_wrong_base_and_unhealthy_candidates_never_promote():
    gate = ContinualLearningGate(key=b"test-secret", maximum_skill_drop=0.02, maximum_kl=0.05)
    base = checkpoint("base")
    candidate = checkpoint("candidate")
    healthy = SafetySnapshot(80.0, True, True, 2.0, False)
    metrics = CandidateMetrics(False, 0, 0.01, {"search_cover": 0.96}, {"search_cover": 0.95})
    assert not gate.evaluate(base, candidate.tampered(), metrics, healthy).promote
    assert not gate.evaluate(base, candidate, metrics, SafetySnapshot(20.0, True, True, 2.0, False)).promote


def test_skill_regression_and_collision_block_promotion():
    gate = ContinualLearningGate(key=b"test-secret", maximum_skill_drop=0.02, maximum_kl=0.05)
    base, candidate = checkpoint("base"), checkpoint("candidate")
    health = SafetySnapshot(80.0, True, True, 2.0, False)
    regression = CandidateMetrics(False, 0, 0.01, {"gate_course": 0.89}, {"gate_course": 0.92})
    collision = CandidateMetrics(False, 1, 0.01, {"gate_course": 0.93}, {"gate_course": 0.92})
    assert not gate.evaluate(base, candidate, regression, health).promote
    assert not gate.evaluate(base, candidate, collision, health).promote


def test_canary_rolls_back_on_first_safety_failure():
    stable, candidate = checkpoint("stable"), checkpoint("candidate")
    controller = CanaryController(stable)
    controller.activate(candidate, vehicle_id=7)
    controller.observe(vehicle_id=7, safety_failure="collision", latency_ms=4.0)
    assert controller.active.version == "stable"
    assert controller.rollback_reason == "collision"


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
```

- [ ] **Step 2: Run continual-learning tests and verify RED**

Run: `pytest tests/test_continual_learning.py -q`

Expected: collection fails because `flydrones.continual_learning` does not exist.

- [ ] **Step 3: Implement signing, promotion gates, shadow mode, and rollback**

Use HMAC-SHA256 for local integrity in this phase. `SignedCheckpoint` includes schema version, version, payload digest, frozen base hash, and signature; `verify(key)` uses constant-time comparison. A candidate must share the current base frozen hash.

`ResidualAdapter` contains only six skill biases, duration/energy estimate scales, and four bounded skill parameters. `update()` returns a new immutable adapter, refuses unhealthy `SafetySnapshot`, clips every per-update delta to `0.05`, and never receives or returns base actor parameters. `ShadowPolicyRunner.compare()` executes stable and candidate adapters over the same immutable observation records without allowing candidate actions to reach the environment, then emits `CandidateMetrics`.

`CandidateMetrics` includes `shadow_only`, `collisions`, `policy_kl`, `candidate_success_by_skill`, and `baseline_success_by_skill`. Promotion requires a valid signature, matching frozen hash, `SafetySnapshot.can_learn`, completed shadow evaluation, zero collisions, KL at or below the configured maximum, identical skill-key sets, and no success drop greater than two percentage points.

`CanaryController` accepts exactly one vehicle ID. It rolls back on any safety failure, non-finite latency, or latency above 35 ms, and records an immutable audit event. It never broadcasts payload bytes; `peer_announcement()` returns only version, digest, and frozen hash.

- [ ] **Step 4: Run continual-learning and policy boundary tests**

Run: `pytest tests/test_continual_learning.py tests/test_multitask_policy.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 6**

```bash
git add src/flydrones/continual_learning.py tests/test_continual_learning.py
git commit -m "feat: gate and rollback continual learning adapters"
```

### Task 7: Curriculum, Evaluation Gates, and Configuration

**Files:**
- Modify: `src/flydrones/training.py`
- Modify: `tests/test_training.py`
- Create: `configs/multitask_training.yaml`
- Create: `tests/test_multitask_config.py`

**Interfaces:**
- Consumes: per-task metrics and scenario levels from Tasks 2 and 3.
- Produces: `MultiTaskAcceptance.from_dict()`, `MultiTaskAcceptance.evaluate() -> AcceptanceReport`, and the canonical nine-stage configuration.

- [ ] **Step 1: Write failing hard-gate tests**

```python
from pathlib import Path

import yaml

from flydrones.training import MultiTaskAcceptance


def passing_metrics():
    return {
        "episodes": 1000,
        "full_scale_episodes": 100,
        "collisions": 0,
        "geofence_violations": 0,
        "return_reserve_violations": 0,
        "central_control_commands": 0,
        "exit_success": 0.95,
        "tracking_success": 0.95,
        "tracking_rmse_m": 0.75,
        "tracking_loss_fraction": 0.05,
        "search_coverage": 0.95,
        "duplicate_coverage": 0.20,
        "formation_rmse_m": 0.40,
        "gate_success": 0.90,
        "gate_contacts": 0,
        "task_release_s": 3.0,
        "task_reopen_s": 3.2,
        "task_reassign_s": 5.0,
        "compound_success": 0.90,
        "maximum_skill_drop": 0.02,
    }


def test_acceptance_requires_every_safety_and_task_gate():
    gate = MultiTaskAcceptance.spec_defaults()
    assert gate.evaluate(passing_metrics()).passed
    unsafe = passing_metrics()
    unsafe["collisions"] = 1
    report = gate.evaluate(unsafe)
    assert not report.passed
    assert "collisions" in report.failures


def test_canonical_config_contains_all_levels_and_frozen_layers():
    data = yaml.safe_load(Path("configs/multitask_training.yaml").read_text(encoding="utf-8"))
    assert [stage["level"] for stage in data["curriculum"]] == list(range(9))
    assert data["frozen"] == ["malecns_reflex", "safety_projector", "px4_inner_loop"]
    assert data["deployment"]["central_control_commands_allowed"] == 0
```

- [ ] **Step 2: Run training/config tests and verify RED**

Run: `pytest tests/test_training.py tests/test_multitask_config.py -q`

Expected: import fails for `MultiTaskAcceptance`, and the new YAML file is absent.

- [ ] **Step 3: Implement metric evaluation and canonical configuration**

Add frozen `AcceptanceReport(passed: bool, failures: tuple[str, ...])`. `MultiTaskAcceptance.spec_defaults()` contains the exact thresholds in the design specification. `evaluate()` rejects missing, non-numeric, or non-finite metrics and returns failures in deterministic key order; safety counters use equality-to-zero and performance metrics use inclusive boundaries.

Create the YAML with levels `0` regression, `1` individual skill, `2` paired tasks, `3` compound tasks, `4` full 20/50/100-aircraft stress, `5` PX4 SITL, `6` hardware-in-the-loop, `7` tethered/caged canary, and `8` controlled real-flight shadow/canary. Include seed ranges, active-factor minimums, promotion metrics, frozen layers, maximum policy latency `35`, maximum skill drop `0.02`, maximum KL `0.05`, shadow-only default `true`, and central commands allowed `0`.

- [ ] **Step 4: Run training and configuration tests**

Run: `pytest tests/test_training.py tests/test_multitask_config.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 7**

```bash
git add src/flydrones/training.py tests/test_training.py configs/multitask_training.yaml tests/test_multitask_config.py
git commit -m "feat: add multitask curriculum acceptance gates"
```

### Task 8: Train/Evaluate Tools and End-to-end Smoke Run

**Files:**
- Create: `tools/train_multitask.py`
- Create: `tools/evaluate_multitask.py`
- Create: `tests/test_multitask_tools.py`
- Create: `docs/MULTITASK_LEARNING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: scenario generator, environment, recurrent policy, continual-learning gate, configuration, and acceptance evaluator from Tasks 1–7.
- Produces: reproducible CLI training/evaluation commands, JSON model manifests, JSON evaluation reports, and operator documentation.

- [ ] **Step 1: Write failing CLI smoke tests**

```python
import json
import subprocess
import sys


def test_train_and_evaluate_smoke_are_reproducible(tmp_path):
    checkpoint = tmp_path / "checkpoint.pt"
    train_report = tmp_path / "train.json"
    command = [
        sys.executable, "tools/train_multitask.py", "--level", "0", "--seed", "5",
        "--steps", "16", "--checkpoint", str(checkpoint), "--report", str(train_report),
    ]
    subprocess.run(command, check=True)
    first = json.loads(train_report.read_text(encoding="utf-8"))
    subprocess.run(command, check=True)
    second = json.loads(train_report.read_text(encoding="utf-8"))
    assert first["manifest_digest"] == second["manifest_digest"]
    assert first["seed"] == second["seed"] == 5
    assert checkpoint.exists()

    evaluation = tmp_path / "evaluation.json"
    subprocess.run([
        sys.executable, "tools/evaluate_multitask.py", "--checkpoint", str(checkpoint),
        "--seeds", "5,6", "--episodes", "2", "--report", str(evaluation),
    ], check=True)
    result = json.loads(evaluation.read_text(encoding="utf-8"))
    assert result["central_control_commands"] == 0
    assert len(result["episodes"]) == 2
```

- [ ] **Step 2: Run tool tests and verify RED**

Run: `pytest tests/test_multitask_tools.py -q`

Expected: subprocess fails because `tools/train_multitask.py` does not exist.

- [ ] **Step 3: Implement reproducible command-line tools**

`train_multitask.py` validates arguments, seeds Python/NumPy/PyTorch, generates the requested manifest, constructs `MultiTaskEnv`, `SharedRecurrentPolicy`, and `CentralizedCritic`, and loops the shared actor across every active vehicle. `--fleet-size` defaults to one for the smoke command and full curriculum invocations pass 20, 50, or 100 explicitly. Use clipped PPO with discount `0.99`, GAE lambda `0.95`, clip ratio `0.20`, entropy coefficient `0.01`, value coefficient `0.50`, and four update epochs. It writes a deployment actor checkpoint without critic weights atomically, then writes a JSON report with seed, manifest digest, code version, checkpoint digest, steps, reward terms, collisions, and central command count. The 16-step one-aircraft smoke path must complete on CPU in under 30 seconds.

`evaluate_multitask.py` loads and verifies architecture metadata, prohibits training, runs each requested seed exactly once, aggregates the Task 7 metrics, applies `MultiTaskAcceptance`, and writes episode details plus deterministic sorted failures. It exits `0` when the process ran correctly even if the candidate fails admission; invalid input or corrupt checkpoints exit nonzero.

`docs/MULTITASK_LEARNING.md` documents environment setup with `pip install -e ".[learning,dev]"`, smoke commands, full curriculum commands, report locations, frozen layers, the meaning of shadow/canary/rollback, and the explicit statement that simulation results are not authorization for unsupervised real flight. Add one README link to this guide.

- [ ] **Step 4: Run smoke, focused suites, then the full repository suite**

Run: `pytest tests/test_multitask_tools.py tests/test_multitask_contract.py tests/test_multitask_scenarios.py tests/test_multitask_env.py tests/test_multitask_policy.py tests/test_mission_learning.py tests/test_continual_learning.py tests/test_multitask_config.py -q`

Expected: all new tests pass.

Run: `pytest -q`

Expected: the complete repository suite passes; any pre-existing warning is recorded without adding a new warning.

Run: `python tools/train_multitask.py --level 0 --seed 42 --steps 64 --checkpoint results/multitask-smoke/checkpoint.pt --report results/multitask-smoke/train.json`

Expected: command exits zero and creates the checkpoint and report.

Run: `python tools/evaluate_multitask.py --checkpoint results/multitask-smoke/checkpoint.pt --seeds 100,101,102 --episodes 3 --report results/multitask-smoke/evaluation.json`

Expected: command exits zero, reports three episodes, zero central commands, and an admission decision with explicit failures when the untrained smoke model does not meet production thresholds.

- [ ] **Step 5: Commit Task 8**

```bash
git add tools/train_multitask.py tools/evaluate_multitask.py tests/test_multitask_tools.py docs/MULTITASK_LEARNING.md README.md
git commit -m "feat: add multitask training and evaluation workflow"
```

### Task 9: PX4 SITL and Independent-physics Validation Boundary

**Files:**
- Create: `src/flydrones/multitask_sitl.py`
- Create: `tests/test_multitask_sitl.py`
- Modify: `tools/evaluate_multitask.py`
- Modify: `docs/MULTITASK_LEARNING.md`

**Interfaces:**
- Consumes: `SafePolicyResult`, existing MAVLink/PX4 velocity-setpoint interfaces, scenario manifests, and evaluation report schema.
- Produces: `MultiTaskSITLAdapter.to_setpoint()`, `MultiTaskSITLAdapter.step_vehicle()`, and optional `--backend fast|px4|pybullet` evaluation selection.

- [ ] **Step 1: Write failing adapter isolation tests**

```python
import pytest

from flydrones.multitask_contract import PolicyIntent, Skill
from flydrones.multitask_sitl import MultiTaskSITLAdapter


def test_adapter_converts_only_local_normalized_intent_to_bounded_setpoint():
    adapter = MultiTaskSITLAdapter(maximum_speed_mps=8.0, maximum_yaw_rate_rps=1.5)
    setpoint = adapter.to_setpoint(
        vehicle_id=4,
        intent=PolicyIntent(Skill.TRACK_TARGET, (2.0, -2.0, 0.5, 1.0), 0.9, 0.5),
    )
    assert setpoint.vehicle_id == 4
    assert setpoint.velocity_mps == (8.0, -8.0, 4.0)
    assert setpoint.yaw_rate_rps == 1.5
    assert setpoint.source == "local-multitask-policy"


def test_adapter_rejects_global_or_cross_vehicle_commands():
    adapter = MultiTaskSITLAdapter(maximum_speed_mps=8.0, maximum_yaw_rate_rps=1.5)
    with pytest.raises(ValueError, match="vehicle"):
        adapter.step_vehicle(local_vehicle_id=4, commanded_vehicle_id=5, intent=None)
    with pytest.raises(TypeError, match="PolicyIntent"):
        adapter.step_vehicle(local_vehicle_id=4, commanded_vehicle_id=4, intent=(1, 0, 0, 0))


def test_optional_pybullet_backend_fails_with_install_instruction_when_absent():
    adapter = MultiTaskSITLAdapter(maximum_speed_mps=8.0, maximum_yaw_rate_rps=1.5)
    if not adapter.pybullet_available:
        with pytest.raises(RuntimeError, match="gym-pybullet-drones"):
            adapter.validate_backend("pybullet")
```

- [ ] **Step 2: Run SITL adapter tests and verify RED**

Run: `pytest tests/test_multitask_sitl.py -q`

Expected: collection fails because `flydrones.multitask_sitl` does not exist.

- [ ] **Step 3: Implement the local SITL adapter and optional backend probe**

Create frozen `LocalVelocitySetpoint(vehicle_id, velocity_mps, yaw_rate_rps, source)`. `to_setpoint()` checks and clips a `PolicyIntent`, scales local normalized axes by configured speed/yaw limits, and always stamps source `local-multitask-policy`. `step_vehicle()` requires local and commanded IDs to match before invoking the existing per-process MAVLink adapter; it has no fleet-state input and no method for routing a command to another vehicle.

`validate_backend("fast")` always succeeds. `validate_backend("px4")` verifies the existing PX4/Gazebo prerequisites without starting processes. `validate_backend("pybullet")` imports the optional package and otherwise raises an installation message naming `gym-pybullet-drones`. Add `--backend` to evaluation so the same held-out seeds and report schema can run against available physics, with `backend` and dependency versions recorded in the report.

- [ ] **Step 4: Run adapter and existing PX4 integration suites**

Run: `pytest tests/test_multitask_sitl.py tests/test_distributed_px4.py tests/test_sitl.py tests/test_sitl_swarm.py -q`

Expected: all selected tests pass without starting an external simulator.

- [ ] **Step 5: Commit Task 9**

```bash
git add src/flydrones/multitask_sitl.py tests/test_multitask_sitl.py tools/evaluate_multitask.py docs/MULTITASK_LEARNING.md
git commit -m "feat: add multitask SITL validation boundary"
```

### Task 10: Final Regression, Review Package, and Evidence Record

**Files:**
- Create: `results/multitask-smoke/summary.json`
- Modify only when findings require a RED-to-GREEN fix: files owned by Tasks 1–9.

**Interfaces:**
- Consumes: all Tasks 1–9 and the design acceptance rules.
- Produces: a machine-readable smoke evidence summary and a fresh-context whole-branch review.

- [ ] **Step 1: Generate the smoke evidence summary**

Write `summary.json` from the two Task 8 reports with schema version, git commit, configuration digest, checkpoint digest, scenario digests, test command, test result count, collision count, central command count, admission result, and admission failures. Use a script invocation from `tools/evaluate_multitask.py --summary` rather than hand-editing measured values.

- [ ] **Step 2: Verify repository hygiene and frozen boundaries**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `pytest -q`

Expected: complete suite passes.

Run: `python -m compileall -q src tools`

Expected: command exits zero.

- [ ] **Step 3: Commit the measured evidence**

```bash
git add results/multitask-smoke/summary.json
git commit -m "test: record multitask learning smoke evidence"
```

- [ ] **Step 4: Build and dispatch the final review package**

Use the `executing-plans` review-package script with this plan, the branch merge base, and `HEAD`. Give the reviewer the design spec, this plan, the five Review Focus lines, and every ledger ruling. Classify all returned findings by user-visible effect before changing code.

- [ ] **Step 5: Apply one verified fix pass if required**

For each Critical or Important finding, add the smallest failing regression test, run it to observe RED, implement the fix, observe GREEN, run `pytest -q`, and commit the fix. Record Minor findings in the ledger for the final report without modifying them.

- [ ] **Step 6: Finish the branch**

Load `superpowers:finishing-a-development-branch`, report the final test evidence, rulings, deferred minor findings, measured smoke limitations, and present the integration choices required by that skill.
