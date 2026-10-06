# Full-Load Runtime Mapping Study Implementation Plan

> **For Codex:** Use `superpowers:executing-plans` to implement this plan task by task with TDD. Preserve every failed dry build or physical run.

**Goal:** Produce and execute one prospectively frozen 25-second PX4/Gazebo/OpenVINS runtime-mapping study without relaxing load, watchdogs, safety, or truth boundaries.

**Architecture:** A prospective builder derives an exact v3 binding from the sealed resource graph plus source-selected runtime ELF roots and strict `ldd` closures. The existing declared capture executes the study. A separate auditor qualifies mapping coverage while keeping runtime closure, VIO accuracy, and fusion false.

**Tech Stack:** Python 3.12, pytest, WSL Linux `/proc`, PX4 SITL, Gazebo Sim 8, OpenVINS, existing capture/binding/supervisor infrastructure.

---

### Task 1: Build the strict runtime inventory

**Files:**
- Create: `tools/benchmark/full_load_runtime_mapping.py`
- Create: `tests/benchmark/test_full_load_runtime_mapping.py`

- [ ] Write failing tests for exact candidate selection, zero/multiple candidates, stable canonical identities, deterministic ordering, and duplicate path refusal.
- [ ] Write failing tests for bounded `ldd` success, nonzero, timeout, `not found`, unsupported output, and dependency drift.
- [ ] Implement explicit root roles for Python/Gazebo bindings, selected systems, DART, Ogre2, required sensor libraries, PX4, OpenVINS, and native reference.
- [ ] Record package versions and selection reasons without calling unused installed candidates selected.
- [ ] Run focused tests and changed-file Ruff.

### Task 2: Produce exact contracts before launch

**Files:**
- Modify: `tools/benchmark/full_load_runtime_mapping.py`
- Modify: `tests/benchmark/test_full_load_runtime_mapping.py`

- [ ] Write failing tests for deriving generated hashes from the pinned board archive and current `gz_env.sh`.
- [ ] Write failing tests for merging the sealed v2 resource declaration into v3 without changing its graph context or silently dropping a path.
- [ ] Write failing tests for exact self/owned lifecycle phases, 8 MiB/16-observation bounds, and 300/300 execution limits.
- [ ] Implement deterministic `execution-contract.json`, `runtime-binding-v3.json`, study manifest, and exact declared command.
- [ ] Refuse active resources, legacy undeclared execution, input drift, short writes, and destination reuse.

### Task 3: Add the terminal study auditor

**Files:**
- Create: `tools/benchmark/audit_full_load_runtime_mapping.py`
- Create: `tests/benchmark/test_audit_full_load_runtime_mapping.py`

- [ ] Write failing tests for missing/out-of-order phases, unknown mappings, incomplete 25-second simulation, capture nonzero, missing ULog, cleanup uncertainty, and pre/post drift.
- [ ] Implement qualification that sets only mapping coverage true; keep runtime closure, VIO accuracy, health, fusion, and flight readiness false.
- [ ] Preserve partial capture and audit evidence on every refusal.

### Task 4: Perform the prospective dry build

- [ ] Verify no competing PX4/Gazebo/OpenVINS/training process exists.
- [ ] Run the builder in `--prepare-only` mode under WSL and retain all declarations, root-selection evidence, `ldd` outputs, and hashes.
- [ ] Independently validate schema, member counts, path existence, execution limits, profiles, and pre-run identities.
- [ ] If dry build fails, diagnose from source/package evidence and create a new dry-build attempt; never add a path solely because a process mapped it.

### Task 5: Run the single full-load mapping study

- [ ] Recheck active resources and byte identity of the accepted dry-build inputs.
- [ ] Launch exactly the declared command once; do not change parameters or repeat to seek a pass.
- [ ] Follow the existing bounded supervisor until terminal; do not start a competing run.
- [ ] Verify resource release, ULog retention, supervisor journal, capture status, required phases, source/readiness/native health, and declared-file stability.
- [ ] Run the terminal auditor and retain all failures.

### Task 6: Regression, review, report, and evidence

**Files:**
- Create: `docs/FULL_LOAD_RUNTIME_MAPPING_REPORT.md`
- Create: `evidence/full-load-runtime-mapping-dev-1701.zip`

- [ ] Run focused tests, full Python regression, changed-file Ruff, whole-repository Ruff comparison, and `git diff --check`.
- [ ] Self-review for source-derived selection, declaration drift, retry bias, phase ordering, process cleanup, and overclaiming; record the lack of an independent reviewer under the current single-agent constraint.
- [ ] Write the report with exact pass/fail status, commits, hashes, runtime limits, phase evidence, process release, and unchanged prior failures.
- [ ] Seal all dry-build and run attempts with per-member hashes, CRC verification, and external SHA-256.
- [ ] Commit in reviewable units, create and attach a draft PR, and update the next-step record to the trajectory/gauge contract.
