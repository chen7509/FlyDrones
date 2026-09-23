# Resumable Multi-task Curriculum Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated, resumable curriculum trainer that evaluates the shared recurrent actor through live MaleCNS reflexes and the deterministic safety chain, measures real task telemetry, validates mission reassignment, and blocks promotion on safety or skill regression.

**Architecture:** A live MaleCNS bridge and reusable `SafetyArbiter` form the only action path used by evaluation and PPO sampling. `MultiTaskEnv` supplies actual disturbance injection and accumulated telemetry; separate evaluator and mission-validation modules produce evidence. A checkpointed `PPOTrainer` is orchestrated by a deterministic curriculum state machine and CLI with atomic state, locking, resume, best-model selection, and cross-skill regression.

**Tech Stack:** Python 3.12, PyTorch, NumPy, Gymnasium, PyYAML, pytest, existing MaleCNS/mission modules, Windows/RTX 3070 Ti.

**Spec:** `docs/superpowers/specs/2026-09-22-resumable-curriculum-training-design.md`

## Global Constraints

- Execute in a native managed worktree created from the plan commit; do not implement in the current checkout with 28 tracked modifications and 194 untracked entries.
- Bring in only reviewed MaleCNS source/test dependencies that are absent from Git; never copy results, logs, generated assets, data files, or checkpoints.
- The deployed artifact contains actor weights only; critic, optimizer, simulator truth, and RNG state remain training-only.
- Every final action passes live MaleCNS reflex arbitration and deterministic safety projection; raw actor output is diagnostic data only.
- PPO actor loss excludes every sample whose proposed action was not executed because a reflex or safety rule overrode it.
- Training and held-out seeds never overlap; manifests and reports retain canonical digests.
- Missing evidence, non-finite metrics, fallback MaleCNS execution, collisions, geofence violations, return-reserve violations, or central per-aircraft commands fail closed.
- `smoke` and `desktop` never select 100 aircraft implicitly; only the explicit `full` profile may use 100 aircraft.
- Fast-simulation promotion does not authorize PX4, hardware-in-loop, or real flight.

## Review Focus

- A stale/dropped frame must stop actor execution after the age deadline rather than appear as a fresh zero-valued observation; Task 3 pins this.
- A requested disturbance with no implementation must raise during environment construction rather than silently disappear; Task 3 pins this.
- A MaleCNS file mismatch or runtime fallback must prevent admission without discarding the last stable actor; Tasks 1 and 8 pin this.
- A crash between checkpoint write and state commit must resume from the previous committed batch without replaying a partially committed update; Tasks 6 and 7 pin this.
- A high reward must never compensate for a collision, safety override attribution error, or more than 0.02 regression in an earlier skill; Tasks 4, 6, and 8 pin this.

## Test Support Conventions

Each new test module owns its small deterministic fixtures instead of depending on hidden global state. `tests/test_multitask_reflex.py` defines `StubMaleCNS` and `local_observation`; `tests/test_multitask_trainer.py` defines `trainer_for`, `manifest`, and override factories; `tests/test_multitask_curriculum.py` defines its valid/invalid config builders; and `tests/test_multitask_curriculum_cli.py` defines subprocess, state-reading, initialization, and lock helpers. These helpers must construct the production types named in the task interfaces, use fixed seeds, and contain no production decision logic.

## Execution Pre-flight: Isolated Worktree and Baseline

- [ ] **Step 1: Create the managed worktree**

Use `mcp__codex_app__create_worktree` with ref equal to the plan commit and name `curriculum-training`. Use the returned workspace directory for every later command.

- [ ] **Step 2: Inventory prerequisite files that are absent from HEAD**

Run in both the source checkout and worktree:

```powershell
git ls-files src/flydrones/malecns_policy.py tests/test_malecns_policy.py
Get-FileHash src/flydrones/malecns_policy.py,tests/test_malecns_policy.py -Algorithm SHA256
```

Expected: absent from the worktree HEAD but present in the source checkout. Record the source hashes in `.superpowers/sdd/2026-09-23-resumable-curriculum-training/progress.md`.

- [ ] **Step 3: Copy only the reviewed prerequisite pair**

Copy `src/flydrones/malecns_policy.py` and `tests/test_malecns_policy.py` from the source checkout into the worktree with `Copy-Item -LiteralPath`. Do not copy any directory recursively.

- [ ] **Step 4: Install and verify the isolated baseline**

Run:

```powershell
python -m pip install -e ".[learning,dev]"
python -m pytest -q
```

Record the clean-worktree test count and any difference from the source checkout's `291 passed, 1 warning` baseline. Investigate failures before feature implementation.

- [ ] **Step 5: Commit the explicit prerequisite import**

```powershell
git add src/flydrones/malecns_policy.py tests/test_malecns_policy.py
git commit -m "feat: track live MaleCNS policy dependency"
```

---

### Task 1: Live MaleCNS Reflex Bridge

**Files:**
- Create: `src/flydrones/multitask_reflex.py`
- Modify: `src/flydrones/malecns_policy.py`
- Create: `tests/test_multitask_reflex.py`
- Modify: `tests/test_malecns_policy.py`

**Interfaces:**
- Consumes: `LocalObservation`, `PolicyIntent`, `Skill`, and `MaleCNSPolicy.predict(observation: np.ndarray) -> np.ndarray`.
- Produces: `ReflexEvidence`, `ReflexDecision`, `ReflexBridge.evaluate(observation)`, and `MaleCNSReflexBridge`.

- [ ] **Step 1: Write failing bridge and backend-identity tests**

```python
def test_live_bridge_returns_none_for_go_and_override_for_escape():
    policy = StubMaleCNS(actions=[(0.5, 0.0, "malecns:go"), (-0.9, 0.8, "malecns:turn-away")])
    bridge = MaleCNSReflexBridge(policy)
    assert bridge.evaluate(local_observation()).intent is None
    escape = bridge.evaluate(local_observation())
    assert escape.intent == PolicyIntent(
        Skill.YIELD_RETURN_LAND, (0.0, 0.8, 0.0, 0.8), 1.0, 0.2
    )
    assert escape.evidence.source == "malecns-v1.0-live"


def test_required_live_backend_fails_on_fallback_or_wrong_metadata():
    bridge = MaleCNSReflexBridge(StubMaleCNS(fallback_calls=1, neurons=10), require_live=True)
    with pytest.raises(RuntimeError, match="MaleCNS"):
        bridge.evaluate(local_observation())
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_reflex.py tests/test_malecns_policy.py -q`

Expected: collection fails because `flydrones.multitask_reflex` and the command-note evidence do not exist.

- [ ] **Step 3: Expose the decoded MaleCNS command and implement the bridge**

Add `last_command_note: str | None` to `MaleCNSPolicy`; set it from `FlightCommand.note` on successful neural updates and to `None` on fallback. Implement:

```python
@dataclass(frozen=True)
class ReflexEvidence:
    source: str
    neurons: int
    connections: int
    neural_updates: int
    fallback_calls: int
    p95_ms: float


@dataclass(frozen=True)
class ReflexDecision:
    intent: PolicyIntent | None
    evidence: ReflexEvidence


class ReflexBridge(Protocol):
    def evaluate(self, observation: LocalObservation) -> ReflexDecision: ...
```

`MaleCNSReflexBridge` downsamples the first 16 local depth features to nine sectors, places them in indices `5:14` of the existing 16-value MaleCNS input, and preserves one policy instance per vehicle. `malecns:go` returns no override. `malecns:brake` returns zero motion. `malecns:turn-away` converts signed yaw into a bounded lateral/yaw override. A policy exception returns a zero-motion override and evidence with an incremented fallback; `require_live=True` raises after capturing the evidence.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_multitask_reflex.py tests/test_malecns_policy.py tests/test_multitask_policy.py -q`

Expected: all pass with no new warnings.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/flydrones/multitask_reflex.py src/flydrones/malecns_policy.py tests/test_multitask_reflex.py tests/test_malecns_policy.py
git commit -m "feat: bridge live MaleCNS reflexes into multitask policy"
```

---

### Task 2: Shared Safety Arbitration for Evaluation and PPO

**Files:**
- Modify: `src/flydrones/multitask_policy.py`
- Modify: `tests/test_multitask_policy.py`

**Interfaces:**
- Consumes: `PolicyIntent`, `SafetySnapshot`, and optional `reflex_override`.
- Produces: `SafetyArbiter.preflight()`, `SafetyArbiter.resolve()`, and a refactored `SafePolicy` that delegates to one arbiter.

- [ ] **Step 1: Write failing shared-arbitration tests**

```python
def test_arbiter_preflight_skips_actor_for_reflex_and_emergency():
    arbiter = SafetyArbiter(SafetyProjector())
    reflex = PolicyIntent(Skill.YIELD_RETURN_LAND, (0.0, 1.0, 0.0, 1.0), 1.0, 0.2)
    result = arbiter.preflight(healthy_snapshot(), reflex_override=reflex)
    assert result is not None and result.intent == reflex
    assert result.reason == "malecns-reflex"


def test_safe_policy_and_training_path_resolve_identically():
    proposed = PolicyIntent(Skill.SEARCH_COVER, (0.3, 0.0, 0.0, 0.0), 0.9, 0.2)
    direct = SafetyArbiter(SafetyProjector()).resolve(proposed, healthy_snapshot(), now=1.0)
    wrapped = SafePolicy(StubActor(proposed), SafetyProjector()).act(
        observation(), PolicyState.zeros(64), healthy_snapshot(), now=1.0
    )
    assert direct.intent == wrapped.intent
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_policy.py -q`

Expected: imports or calls fail because `SafetyArbiter` and explicit `now` do not exist.

- [ ] **Step 3: Extract arbitration without changing safety priority**

Move health preflight, projector invocation, and skill hysteresis into `SafetyArbiter`. `preflight()` returns a `ProjectionResult | None`; `resolve()` validates a proposed intent and returns `ProjectionResult`. Inject monotonic time into `SafePolicy.act(..., now: float | None = None)` for deterministic tests while preserving wall-clock latency measurement.

- [ ] **Step 4: Run focused safety and legacy tests**

Run: `python -m pytest tests/test_multitask_policy.py tests/test_binary_behavior.py tests/test_control.py -q`

Expected: all pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/flydrones/multitask_policy.py tests/test_multitask_policy.py
git commit -m "refactor: share deterministic safety arbitration"
```

---

### Task 3: Real Disturbance Injection and Episode Telemetry

**Files:**
- Create: `src/flydrones/multitask_metrics.py`
- Modify: `src/flydrones/multitask_env.py`
- Modify: `src/flydrones/multitask_contract.py`
- Modify: `tests/test_multitask_env.py`
- Create: `tests/test_multitask_metrics.py`

**Interfaces:**
- Consumes: scenario disturbances and the true/local environment state.
- Produces: `EpisodeTelemetry`, `MultiTaskEnv.local_observation()`, `MultiTaskEnv.safety_snapshot()`, and `MultiTaskEnv.telemetry()`.

- [ ] **Step 1: Write failing disturbance and telemetry tests**

```python
@pytest.mark.parametrize("name", ["wind", "sensor_noise", "packet_loss", "frame_drop", "localization_drift", "battery_variation"])
def test_each_declared_disturbance_has_a_measured_effect(name):
    env = MultiTaskEnv(manifest_with(name), max_steps=20)
    env.reset(seed=9)
    run_hold_steps(env, 10)
    assert env.telemetry().disturbance_injections[name] > 0


def test_localization_drift_changes_actor_estimate_not_critic_truth():
    control = MultiTaskEnv(manifest_without_disturbances())
    drifted = MultiTaskEnv(manifest_with("localization_drift"))
    control.reset(seed=4)
    drifted.reset(seed=4)
    run_identical_hold_steps((control, drifted), 5)
    assert np.array_equal(control.true_positions(), drifted.true_positions())
    assert not np.array_equal(
        control.local_observation(0).flight_state,
        drifted.local_observation(0).flight_state,
    )


def test_stale_dropped_frame_fails_before_policy_input():
    env = MultiTaskEnv(manifest_with("frame_drop"), maximum_observation_age_s=0.2)
    env.reset(seed=1)
    env._debug_force_frame_drops(0, count=3)
    with pytest.raises(ValueError, match="stale"):
        env.local_observation(0)
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_env.py tests/test_multitask_metrics.py -q`

Expected: missing telemetry/local-observation APIs and ignored frame/localization disturbances.

- [ ] **Step 3: Implement immutable telemetry and measured local state**

Create a frozen `EpisodeTelemetry` containing sample counts/sums for tracking squared error and loss, union/duplicate coverage, formation squared error, gate crossings/contacts, safety failures, overrides, final evidence, and a disturbance-injection mapping. Maintain `_estimated_positions`, `_last_visual_features`, per-vehicle ages, validity masks, and injection counters separately from true positions. `critic_observation()` uses only truth; `local_observation()` creates the validated `LocalObservation` or raises stale.

Reject unknown manifest disturbances in `MultiTaskEnv.__init__`. Packet loss clears the peer-validity bit, frame drop reuses visual features and advances age, and localization drift is a seeded bounded random walk applied only to local estimates.

- [ ] **Step 4: Run environment, contract, and determinism suites**

Run: `python -m pytest tests/test_multitask_env.py tests/test_multitask_metrics.py tests/test_multitask_contract.py tests/test_multitask_scenarios.py -q`

Expected: all pass and repeated seeds produce identical telemetry digests.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/flydrones/multitask_metrics.py src/flydrones/multitask_env.py src/flydrones/multitask_contract.py tests/test_multitask_env.py tests/test_multitask_metrics.py
git commit -m "feat: measure disturbances and multitask episode telemetry"
```

---

### Task 4: Evidence-based Evaluation Through the Full Safety Chain

**Files:**
- Create: `src/flydrones/multitask_evaluation.py`
- Modify: `tools/evaluate_multitask.py`
- Modify: `tests/test_multitask_tools.py`
- Create: `tests/test_multitask_evaluation.py`

**Interfaces:**
- Consumes: actor checkpoint, per-vehicle reflex bridge factory, `SafetyArbiter`, environment telemetry, and held-out manifests.
- Produces: `EvaluationEvidence`, `evaluate_manifests()`, structured missing-evidence failures, and the existing CLI JSON schema version 2.

- [ ] **Step 1: Write failing no-placeholder and full-chain tests**

```python
def test_evaluator_uses_final_actions_and_measured_metrics():
    result = evaluate_manifests(actor, [manifest], reflex_factory=recording_reflex_factory)
    assert result.reflex_calls == result.local_decisions
    assert result.metrics["tracking_rmse_m"] == pytest.approx(
        math.sqrt(result.telemetry.tracking_squared_error_sum / result.telemetry.tracking_samples)
    )
    assert "999" not in json.dumps(result.to_dict())


def test_missing_evidence_is_structured_and_cannot_pass():
    result = evaluate_manifests(actor, [exit_only_manifest], reflex_factory=noop_live_factory)
    assert "formation_rmse_m" in result.missing_evidence
    assert not result.admission.passed
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_evaluation.py tests/test_multitask_tools.py -q`

Expected: evaluator module is missing and the CLI still emits fixed `0.75`, `0.20`, and `999.0` values.

- [ ] **Step 3: Implement reusable evaluation and thin CLI delegation**

For every vehicle, construct an independent reflex bridge, arbiter, and recurrent state. Build `SafetySnapshot` from the environment, run reflex preflight, call the actor only when permitted, and step with final actions. Aggregate only telemetry samples that exist. Represent unavailable metrics as keys in `missing_evidence`, omit numeric values, and make admission fail for every missing required key.

Delete all success-to-constant metric conversions from `tools/evaluate_multitask.py`; keep argument parsing, backend prerequisite validation, summary generation, and atomic report writing.

- [ ] **Step 4: Run evaluation and policy suites**

Run: `python -m pytest tests/test_multitask_evaluation.py tests/test_multitask_tools.py tests/test_multitask_policy.py tests/test_multitask_reflex.py -q`

Expected: all pass; smoke evaluation fails admission with explicit missing evidence rather than sentinels.

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/flydrones/multitask_evaluation.py tools/evaluate_multitask.py tests/test_multitask_evaluation.py tests/test_multitask_tools.py
git commit -m "feat: evaluate final safe actions from measured evidence"
```

---

### Task 5: Deterministic Mission Reassignment Validation

**Files:**
- Create: `src/flydrones/mission_validation.py`
- Create: `tests/test_mission_validation.py`

**Interfaces:**
- Consumes: `MissionContract`, `MissionAgent`, task messages, low-battery/failure/network schedules.
- Produces: `MissionValidationScenario`, `MissionValidationEvidence`, and `MissionValidationRunner.run()`.

- [ ] **Step 1: Write failing release/reopen/reassign tests**

```python
def test_low_battery_releases_and_healthy_peer_reassigns_without_double_owner():
    evidence = MissionValidationRunner(contract(), vehicle_count=5).run(
        MissionValidationScenario.low_battery(seed=12, vehicle_id=1, at_s=5.0)
    )
    assert evidence.task_release_s <= 3.0
    assert evidence.task_reassign_s <= 5.0
    assert evidence.maximum_simultaneous_owners == 1


def test_partition_and_stale_messages_cannot_change_safe_state():
    evidence = MissionValidationRunner(contract(), vehicle_count=5).run(
        MissionValidationScenario.partition_with_stale_replay(seed=13)
    )
    assert evidence.stale_messages_accepted == 0
    assert evidence.safety_violations == 0
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_mission_validation.py -q`

Expected: collection fails because `flydrones.mission_validation` does not exist.

- [ ] **Step 3: Implement a read-only deterministic validation harness**

Advance independent `MissionAgent` instances on a fixed `0.1 s` clock. Deliver versioned task messages through seeded delay/drop/partition schedules, inject state changes, and derive timings from ledger transitions rather than reward. The runner never mutates actor weights and never supplies per-aircraft motion commands.

- [ ] **Step 4: Run mission and consensus suites**

Run: `python -m pytest tests/test_mission_validation.py tests/test_mission_agent.py tests/test_task_consensus.py tests/test_mission_learning.py -q`

Expected: all pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src/flydrones/mission_validation.py tests/test_mission_validation.py
git commit -m "feat: measure deterministic mission reassignment"
```

---

### Task 6: Resumable PPO Trainer and Versioned Checkpoints

**Files:**
- Create: `src/flydrones/multitask_trainer.py`
- Modify: `tools/train_multitask.py`
- Create: `tests/test_multitask_trainer.py`
- Modify: `tests/test_multitask_tools.py`

**Interfaces:**
- Consumes: manifest, actor, critic, reflex factory, safety arbiter, device, and PPO hyperparameters.
- Produces: `TrainerCheckpoint`, `BatchTrainingReport`, `PPOTrainer.train_batch()`, `.save()`, `.load()`, and `.export_actor()`.

- [ ] **Step 1: Write failing checkpoint and attribution tests**

```python
def test_checkpoint_round_trip_restores_optimizer_rng_and_counters(tmp_path):
    trainer = trainer_for(seed=22)
    trainer.train_batch(manifest(), steps=8)
    trainer.save(tmp_path / "trainer.pt", config_digest="a" * 64, state_digest="b" * 64)
    restored = PPOTrainer.load(tmp_path / "trainer.pt", device="cpu", config_digest="a" * 64)
    assert restored.actor_digest() == trainer.actor_digest()
    assert restored.global_updates == trainer.global_updates
    assert restored.environment_steps == trainer.environment_steps
    assert restored.random_state_digest() == trainer.random_state_digest()


def test_reflex_overridden_sample_updates_critic_but_not_actor():
    trainer = trainer_for(reflex_factory=always_override_factory)
    before_actor, before_critic = trainer.actor_digest(), trainer.critic_digest()
    report = trainer.train_batch(manifest(), steps=8)
    assert report.actor_samples == 0
    assert report.critic_samples > 0
    assert trainer.actor_digest() == before_actor
    assert trainer.critic_digest() != before_critic
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_trainer.py tests/test_multitask_tools.py -q`

Expected: trainer module is missing and the existing CLI cannot resume.

- [ ] **Step 3: Move PPO mechanics behind `PPOTrainer`**

Preserve per-vehicle GAE. Preflight reflex/safety before sampling; mark each transition with `actor_executed`. Train the critic on all valid transitions and actor only on `actor_executed=True`. Move actor, critic, optimizer, counters, Python/NumPy/Torch CPU/CUDA RNG states, metadata, and digests into schema-versioned atomic checkpoints. Reinitialize only the critic and optimizer critic parameter group when fleet-dependent critic input dimension changes; preserve actor weights and record the reset.

Make `tools/train_multitask.py` a one-batch compatibility wrapper around `PPOTrainer`.

- [ ] **Step 4: Run trainer, tool, and deterministic replay suites**

Run: `python -m pytest tests/test_multitask_trainer.py tests/test_multitask_tools.py tests/test_multitask_evaluation.py -q`

Expected: all pass; interrupted/reloaded and uninterrupted two-batch runs have identical actor digests.

- [ ] **Step 5: Commit Task 6**

```powershell
git add src/flydrones/multitask_trainer.py tools/train_multitask.py tests/test_multitask_trainer.py tests/test_multitask_tools.py
git commit -m "feat: add resumable safe PPO training"
```

---

### Task 7: Curriculum Configuration, Scheduling, State, and Locking

**Files:**
- Create: `src/flydrones/multitask_curriculum.py`
- Modify: `src/flydrones/multitask_scenarios.py`
- Modify: `configs/multitask_training.yaml`
- Create: `tests/test_multitask_curriculum.py`
- Modify: `tests/test_multitask_scenarios.py`
- Modify: `tests/test_multitask_config.py`

**Interfaces:**
- Consumes: YAML profile/stage definitions, explicit active skills, trainer/evaluator reports, and output directory.
- Produces: `CurriculumConfig.load()`, `CurriculumStage`, `CurriculumState`, `RunLock`, deterministic `manifest_for_batch()`, atomic `commit_batch()`, and `promotion_decision()`.

- [ ] **Step 1: Write failing validation, resume, and rollback tests**

```python
def test_config_rejects_seed_overlap_and_implicit_full_scale(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        CurriculumConfig.from_dict(config_with(train_seeds=[1], eval_seeds=[1]))
    with pytest.raises(ValueError, match="100"):
        CurriculumConfig.from_dict(config_with(profile="desktop", fleets=[100]))


def test_partial_batch_is_not_resumed_as_committed(tmp_path):
    store = CurriculumStore(tmp_path)
    committed = store.initialize(valid_config())
    write_orphan_checkpoint(tmp_path / "latest-trainer.pt")
    assert store.load().last_committed_batch == committed.last_committed_batch


def test_skill_regression_rolls_back_candidate():
    decision = promotion_decision(
        current=safe_metrics(success=0.96),
        baselines={"search": 0.95},
        regressions={"search": 0.92},
        maximum_drop=0.02,
    )
    assert not decision.promote
    assert decision.reasons == ("skill-regression:search",)
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_curriculum.py tests/test_multitask_config.py tests/test_multitask_scenarios.py -q`

Expected: curriculum types and explicit skill overrides are missing.

- [ ] **Step 3: Implement strict profiles and atomic curriculum state**

Add explicit `active_skills` override to `ScenarioGenerator.generate()` while retaining manifest validation. Extend YAML with `smoke`, `desktop`, and `full`; give every stage an ID, sequential index, level, active skills, fleets, training/evaluation/regression seeds, steps per batch, maximum batches, patience, and thresholds.

`RunLock` creates a lock atomically with PID/host/start time and refuses a live competing owner. `CurriculumStore` writes checkpoint/report first and replaces `state.json` last. It verifies config and checkpoint digests on load and ignores `.tmp` or unreferenced candidate files.

- [ ] **Step 4: Run curriculum and configuration suites**

Run: `python -m pytest tests/test_multitask_curriculum.py tests/test_multitask_config.py tests/test_multitask_scenarios.py -q`

Expected: all pass with deterministic stage/seed ordering.

- [ ] **Step 5: Commit Task 7**

```powershell
git add src/flydrones/multitask_curriculum.py src/flydrones/multitask_scenarios.py configs/multitask_training.yaml tests/test_multitask_curriculum.py tests/test_multitask_config.py tests/test_multitask_scenarios.py
git commit -m "feat: schedule resumable multitask curriculum"
```

---

### Task 8: Curriculum CLI, Promotion, and Recovery

**Files:**
- Create: `tools/run_multitask_curriculum.py`
- Create: `tests/test_multitask_curriculum_cli.py`
- Modify: `docs/MULTITASK_LEARNING.md`

**Interfaces:**
- Consumes: curriculum config/store, PPO trainer, evaluator, mission validator, device/profile/run limits.
- Produces: an executable curriculum loop, batch/regression/failure reports, `latest-trainer.pt`, `best-actor.pt`, and resumable `state.json`.

- [ ] **Step 1: Write failing end-to-end smoke, recovery, and lock tests**

```python
def test_smoke_curriculum_runs_and_resumes_without_repeating_batch(tmp_path):
    run_cli("--profile", "smoke", "--output", str(tmp_path), "--max-batches", "1")
    first = read_state(tmp_path)
    run_cli("--profile", "smoke", "--output", str(tmp_path), "--max-batches", "1")
    second = read_state(tmp_path)
    assert second.last_committed_batch == first.last_committed_batch + 1
    assert (tmp_path / "latest-trainer.pt").exists()
    assert (tmp_path / "best-actor.pt").exists()


def test_config_change_and_concurrent_writer_fail_closed(tmp_path):
    initialize_run(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        run_cli("--output", str(tmp_path), "--config", "changed.yaml")
    with held_run_lock(tmp_path):
        with pytest.raises(subprocess.CalledProcessError):
            run_cli("--output", str(tmp_path))
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_multitask_curriculum_cli.py -q`

Expected: subprocess fails because the curriculum CLI does not exist.

- [ ] **Step 3: Implement the orchestration loop**

Parse `--config`, `--profile`, `--output`, `--device auto|cpu|cuda`, mutually exclusive `--resume/--restart`, `--max-batches`, and `--stop-after-stage`. Resolve `auto` to CUDA only when `torch.cuda.is_available()`. For each batch: choose manifest deterministically, train, save candidate trainer, evaluate actor and mission evidence, run prior-stage regression, promote/export only on all gates, write reports, then atomically commit state. Capture exceptions in a failure report and exit nonzero without advancing state.

`--restart` refuses a non-empty output directory unless it contains a recognized curriculum state, then creates a new run-specific subdirectory instead of deleting existing evidence.

- [ ] **Step 4: Run smoke twice and verify deterministic resume**

Run:

```powershell
python tools/run_multitask_curriculum.py --config configs/multitask_training.yaml --profile smoke --output results/multitask-curriculum-smoke --device cpu --max-batches 1
python tools/run_multitask_curriculum.py --config configs/multitask_training.yaml --profile smoke --output results/multitask-curriculum-smoke --device cpu --max-batches 1
python -m pytest tests/test_multitask_curriculum_cli.py -q
```

Expected: second command advances exactly one committed batch; tests pass. A candidate may fail task admission, but process correctness and state integrity must pass.

- [ ] **Step 5: Commit Task 8**

```powershell
git add tools/run_multitask_curriculum.py tests/test_multitask_curriculum_cli.py docs/MULTITASK_LEARNING.md
git commit -m "feat: run and resume guarded curriculum training"
```

---

### Task 9: Final Regression, Drift Evidence, and Review

**Files:**
- Create: `results/multitask-curriculum-smoke/summary.json`
- Modify only for verified findings: files owned by Tasks 1–8.

**Interfaces:**
- Consumes: all task outputs, current Git commit, config digest, model digest, smoke state, reports, and tests.
- Produces: machine-readable drift evidence and a review-ready branch.

- [ ] **Step 1: Write the evidence summary from generated artifacts**

Add a `--summary` mode to the curriculum CLI or a focused helper that assembles the document from verified runtime values and atomically writes it. The implementation must follow this construction pattern:

```python
summary = {
    "schema_version": 1,
    "git_commit": read_git_commit(),
    "config_digest": sha256_file(config_path),
    "trainer_checkpoint_digest": sha256_file(trainer_checkpoint_path),
    "best_actor_digest": sha256_file(best_actor_path),
    "last_committed_batch": state.last_committed_batch,
    "male_cns_backend": evaluation.male_cns_backend,
    "male_cns_fallbacks": evaluation.male_cns_fallbacks,
    "disturbance_injections": evaluation.disturbance_injections,
    "safety_failures": evaluation.safety_failures,
    "missing_evidence": evaluation.missing_evidence,
    "admission_passed": evaluation.admission.passed,
    "test_command": test_run.command,
    "test_result": test_run.result,
}
```

`read_git_commit`, `sha256_file`, and the test-run capture are implemented in the summary helper and covered by a test that compares their output with Git, `hashlib`, and the completed verification record. Hand editing evidence is forbidden.

- [ ] **Step 2: Run static and full verification**

Run:

```powershell
git diff --check
python -m compileall -q src tools
python -m pytest -q
```

Expected: no whitespace/compile errors; all tests pass with only the recorded pre-existing MaleCNS group warning, if still present.

- [ ] **Step 3: Confirm repository isolation**

Run:

```powershell
git status --short
git diff --name-only $planBase..HEAD
```

Expected: no generated checkpoint, log, raw trajectory, or copied unrelated experiment appears in tracked changes. `$planBase` is the exact plan commit SHA captured in the execution ledger immediately before creating the managed worktree.

- [ ] **Step 4: Commit generated summary**

```powershell
git add results/multitask-curriculum-smoke/summary.json
git commit -m "test: record resumable curriculum smoke evidence"
```

- [ ] **Step 5: Review the whole plan range and fix findings**

Build a review package from the plan commit to HEAD. Review against the spec with special attention to actor-sample attribution, stale observation handling, MaleCNS backend identity, atomic commit order, and skill-regression rollback. For each Critical or Important finding, add a failing regression test, observe RED, implement the smallest fix, observe GREEN, rerun `python -m pytest -q`, and commit. Record deferred Minor findings in the SDD ledger.

- [ ] **Step 6: Finish the branch**

Load `superpowers:finishing-a-development-branch`, report final tests, smoke limitations, admission state, MaleCNS identity, disturbance coverage, rulings, and deferred findings, then present the required integration choices.
