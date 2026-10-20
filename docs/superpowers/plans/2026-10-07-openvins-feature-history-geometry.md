# OpenVINS Feature History and Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain the fixed-input MSCKF history loss and delayed-SLAM triangulation failure without changing OpenVINS decisions or inputs.

**Architecture:** Extend the isolated GPL diagnostic build with per-candidate selection, cleaned-history and triangulation geometry records. Extend the MIT-side strict parser and auditor to reconcile those records with the already qualified aggregate trace and compare the diagnostic state sequence to the uninstrumented control.

**Tech Stack:** C++17, OpenVINS `69488123ed9362dd44b6f28e7f4680abbff1442b`, Python 3.12, pytest, JSONL, SHA-256.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-feature-history-geometry-design.md`

## Global Constraints

- Do not start PX4 or Gazebo and do not rerun or overwrite `study-v21/capture-v1`.
- Do not change estimator state, inputs, thresholds, configuration, feature order, random sources or upstream branch conditions.
- Use the immutable sealed requests and the qualified motion-intent handoff.
- Preserve GPL diagnostics under `tools/benchmark/gpl/`; do not copy GPL implementation into MIT Python.
- Require non-timing camera-state equivalence to control within `1e-12`.
- Do not claim physical accuracy, online latency, root-cause closure, fusion, ODOMETRY, arming or EKF2 qualification.

## Review Focus

- A feature with several raw observations but only one current-clone observation must be classified `clone_pruned`, never `raw_short`.
- A condition number or depth that is NaN or infinite must stay auditable without emitting a non-finite numeric JSON value.
- The same feature ID appearing in separate frames must remain scoped by timestamp and stage.
- An unexpected 1-D triangulation call must fail the fixed-profile audit.
- A missing final history or geometry record in an otherwise parseable log must fail closed.

---

### Task 1: Strict history and geometry parser

**Files:**
- Modify: `tools/benchmark/openvins_feature_trace.py`
- Modify: `tests/benchmark/test_openvins_feature_trace.py`

**Interfaces:**
- Consumes: structured `FD_SELECT`, `FD_HISTORY`, `FD_TRI` log lines.
- Produces: `parse_feature_trace(text: str) -> dict` with per-frame `select`, `history` and `triangulation` records plus reconciled totals.

- [ ] Write failing tests for strict fields, enums, finite placeholders, duplicate identities, raw/valid count conservation, stage reconciliation and the five Review Focus cases.
- [ ] Run `pytest -q tests/benchmark/test_openvins_feature_trace.py` and retain the RED output.
- [ ] Implement the minimal parser and reconciliation changes.
- [ ] Re-run the focused parser tests and require PASS.
- [ ] Commit parser and tests.

### Task 2: Isolated GPL diagnostic patch

**Files:**
- Create: `tools/benchmark/gpl/openvins_feature_history_geometry.patch`
- Modify: `tools/benchmark/gpl/README.md`
- Test: `tests/benchmark/test_openvins_feature_trace.py`

**Interfaces:**
- Consumes: the preceding qualified feature-trace patch applied to the pinned upstream worktree.
- Produces: state-neutral `FD_SELECT`, `FD_HISTORY` and `FD_TRI` records with fixed schemas.

- [ ] Add source-guard tests that require exact upstream locations, unchanged rejection expressions and all required trace fields; run them RED.
- [ ] Add diagnostic-only candidate origins/history and 3-D geometry logging in a new isolated upstream worktree.
- [ ] Export the exact GPL patch and record compiler, linked library, source and binary hashes.
- [ ] Build the diagnostic library and native probe; run source guards and focused tests GREEN.
- [ ] Commit the patch, README and guards.

### Task 3: Fixed replay and independent audit

**Files:**
- Modify: `tools/benchmark/audit_openvins_feature_trace.py`
- Modify: `tests/benchmark/test_openvins_feature_trace.py`
- Create: `results/openvins-feature-history-geometry-dev-1701/`

**Interfaces:**
- Consumes: immutable sealed requests, uninstrumented control and Task 2 diagnostic worker.
- Produces: strict audit with history classification, geometry rejection combinations, source/binary identities and state equivalence.

- [ ] Add RED audit tests for tampered counts, identities, state values, truncated logs and invalid eligibility claims.
- [ ] Run final pre-initialization and duplicate-intent negative protocols.
- [ ] Replay the complete fixed input once through the new diagnostic build; do not run physics.
- [ ] Audit one-for-one record reconciliation, state equivalence and exact fixed-input mechanism totals.
- [ ] Run focused and full regressions, changed-file Ruff and `git diff --check`.
- [ ] Update the report/status matrix, seal evidence, commit, push and update draft PR 65 and the active automation.
