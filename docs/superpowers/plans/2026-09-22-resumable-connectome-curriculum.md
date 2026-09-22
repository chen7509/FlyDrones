# Resumable Connectome Curriculum Implementation Plan

**Goal:** Add an offline, fail-closed curriculum runner that resumes complete-connectome training without changing the frozen comparison evidence or substituting a PPO actor for the connectome.

**Architecture:** A strict YAML contract resolves profiles and ordered stages. Immutable per-batch checkpoints contain model/optimizer/RNG identity, while a small atomic `state.json` points only to the last fully committed batch. A coordinator trains through an injected connectome session, evaluates current and completed stages, commits only eligible candidates, and preserves the previous best on regression. The CLI provides a deterministic tiny-connectome smoke session and a complete-MaleCNS sequence-backed session; neither starts PX4 or Gazebo.

**Tech Stack:** Python 3.12, PyTorch, NumPy, SciPy, PyYAML, pytest.

**Specs:**
- `docs/superpowers/specs/2026-09-22-resumable-curriculum-training-design.md`
- `docs/superpowers/specs/2026-09-22-resumable-connectome-curriculum-binding.md`
- `docs/superpowers/specs/2026-09-22-connectome-constrained-realtime-training-design.md`

## Constraints

- Never modify a path covered by `results/fly-ego-comparison/freeze/manifest.json`.
- Only `ConnectomeConstrainedCore` shared parameters may be trained for artifacts labelled complete MaleCNS.
- `smoke` evidence remains explicitly synthetic and cannot promote PX4, HIL, or real-flight stages.
- Every production behavior starts with a failing test.
- Commit only files owned by this plan; preserve pre-existing worktree changes.

### Task 1: Configuration contract

**Files:**
- Create `configs/connectome_curriculum_v1.yaml`
- Create `src/flydrones/connectome_training/curriculum_config.py`
- Create `tests/connectome_training/test_curriculum_config.py`

Write tests for ordered unique stages, disjoint train/validation seeds, supported profiles, positive batch limits, explicit synthetic-smoke restriction, and deterministic configuration digest. Run the new test and verify it fails because the module is absent. Implement frozen dataclasses and `load_curriculum_config(path, profile)` with strict unknown-key rejection. Run the test and the connectome suite. Commit.

### Task 2: Resumable state, lock, and checkpoint restoration

**Files:**
- Modify `src/flydrones/connectome_training/checkpoint.py`
- Create `src/flydrones/connectome_training/curriculum_state.py`
- Create `tests/connectome_training/test_curriculum_state.py`

Write tests showing atomic committed-state round trips, incompatible config refusal, exclusive output locking, RNG round-trip, checkpoint identity validation, and rejection of orphan `.writing` files. Verify RED. Add `capture_rng_state()` and `restore_rng_state()` to the checkpoint module without weakening existing hashes. Implement `CurriculumState`, `StateStore`, and `RunLock`. Only committed state is durable. Verify GREEN and commit.

### Task 3: Curriculum coordinator and regression protection

**Files:**
- Create `src/flydrones/connectome_training/curriculum.py`
- Create `tests/connectome_training/test_curriculum.py`
- Modify `src/flydrones/connectome_training/__init__.py`

Define a narrow `TrainingSession` protocol: train one batch, evaluate a stage, save a checkpoint, restore a checkpoint, and report identity. Tests use a deterministic real implementation fixture, not mocks. Cover batch commit, exact resume without replay, stage promotion, current-stage gate failure, prior-stage regression rollback, maximum-batch failure, and interruption before state commit. Implement the coordinator with immutable batch directories, reports, best checkpoint references, and deterministic seed rotation. Verify the focused and connectome suites, then commit.

### Task 4: Connectome session and CLI

**Files:**
- Create `src/flydrones/connectome_training/curriculum_session.py`
- Create `tools/connectome_training/run_curriculum.py`
- Create `tests/connectome_training/test_curriculum_cli.py`
- Modify `docs/CONNECTOME_TRAINING.md`

Tests first cover a two-stage smoke run, bounded `--max-batches`, resume, restart refusal while locked, report identity, and fail-closed full profile when sequence evidence is absent. Implement a smoke session using the same deterministic tiny connectome contract as Stage B. Implement a sequence-backed session that loads exact `TrainingSequence` directories, validates partitions, loads the complete parameter artifact and source connectome, and refuses mismatched identities. The CLI defaults to resume, requires `--restart` to replace an existing run, selects `cpu|cuda|auto`, and never starts external simulators. Verify RED then GREEN and commit.

### Task 5: Measured smoke evidence and final audit

**Files:**
- Create `results/connectome-curriculum-smoke/summary.json` and small state/report artifacts
- Modify `docs/CONNECTOME_TRAINING.md` if measured values require clarification

Run the smoke curriculum for one committed batch, stop, then resume to completion. Verify that completed batch indices are not replayed and that the final actor/parameter digest matches an uninterrupted temporary run. Run freeze verification, all connectome tests, and the full project suite. Inspect for leaked training/PX4/Gazebo processes. Commit measured smoke evidence, perform final review, and keep the feature branch isolated pending integration choice.
