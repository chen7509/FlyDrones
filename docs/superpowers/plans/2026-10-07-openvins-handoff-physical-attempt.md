# OpenVINS handoff-corrected physical attempt implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute and independently audit exactly one immutable physical development attempt from the sealed `study-v15` package.

**Architecture:** A committed documentation boundary authorizes a one-shot wrapper that consumes the already-audited manifest and startup evidence. The wrapper fails before dispatch on any identity, destination, audit or resource mismatch, then preserves success or failure for a result-specific independent audit.

**Tech Stack:** Python 3.12, pytest, PX4 SITL, Gazebo Sim 8, pinned OpenVINS, JSON/JSONL evidence, Git and GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-handoff-physical-attempt-design.md`

## Global Constraints

- Exactly one target is allowed: `results/estimator-physical-refusal-diagnosis-dev-1701/study-v15/capture-v1`.
- Preserve the exact 25 s/1 ms/250 Hz/10 Hz 160×120 workload and all declared binaries, profiles, deadlines and safety gates.
- Refuse existing targets/evidence, audit or archive drift, command drift, active competing resources, and any positive unearned downstream qualification.
- Do not arm, publish ODOMETRY, inject EKF2, use truth inside VIO, tune after observing the target, or retry the target.
- Retain every failure and restrict cleanup claims to the evidence actually recorded.

## Review Focus

- A stale but passing-looking audit from a different study or head must refuse before dispatch.
- A destination mismatch between manifest and command must refuse before any process starts.
- Existing dispatch, completion, output or target paths must never be overwritten.
- A nonzero run return must still record completion, resources and the immutable partial target.
- A successful process exit must not be promoted to VIO accuracy, health, fusion or flight without result-specific evidence.

---

### Task 1: Commit and verify the execution boundary

**Files:**
- Create: `docs/superpowers/specs/2026-10-07-openvins-handoff-physical-attempt-design.md`
- Create: `docs/superpowers/plans/2026-10-07-openvins-handoff-physical-attempt.md`
- Create: `results/openvins-handoff-physical-attempt-dev-1701/preconditions.json`

**Interfaces:**
- Consumes: `study-v15/study-manifest.json`, passing post-startup package audit, passing startup audit, sealed stage ZIP.
- Produces: a committed head and a precondition record for the one-shot wrapper.

- [ ] Commit this specification and plan without modifying the frozen package or any runtime input.
- [ ] Re-run `audit_openvins_handoff_retry_preflight --after-startup-preflight` from the committed head and require no failures.
- [ ] Verify the archive name/SHA, startup audit, exact future destination, absent target/evidence paths and empty Windows/WSL resource scans; write the immutable precondition record.

### Task 2: Execute exactly one declared physical attempt

**Files:**
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v7-launcher.py`
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v7-dispatch.json`
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v7-completion.json`
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v7-output.txt`
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/study-v15/capture-v1/`

**Interfaces:**
- Consumes: Task 1 committed head and preconditions plus the exact manifest command.
- Produces: one immutable physical target and dispatch/completion evidence.

- [ ] Write the one-shot wrapper with exact head/audit/archive/destination/resource assertions and exclusive evidence paths.
- [ ] Dry-check only the wrapper's static inputs; do not call the target command during the check.
- [ ] Execute the wrapper once under WSL Ubuntu and wait for its terminal result without restarting on timeout or nonzero exit.
- [ ] Confirm completion/resource evidence and preserve the target exactly as produced.

### Task 3: Classify and independently audit the immutable result

**Files:**
- Create or modify only after inspecting the target: `tools/benchmark/audit_openvins_handoff_physical_attempt.py`
- Create or modify only after inspecting the target: `tests/benchmark/test_audit_openvins_handoff_physical_attempt.py`
- Create: `results/openvins-handoff-physical-attempt-dev-1701/physical-attempt-audit.json`

**Interfaces:**
- Consumes: Task 2 immutable target, dispatch, completion and supervisor/resource evidence.
- Produces: a result-specific, fail-closed independent audit with explicit false downstream claims.

- [ ] Identify the earliest evidence-supported terminal cause without changing or rerunning the target.
- [ ] Write RED tests for the exact normal result and inverse drift in cause, timing/state transition, motion/fusion, ULog, cleanup and resources.
- [ ] Implement the minimal independent auditor and run the RED tests to GREEN.
- [ ] Run the auditor on the immutable target and retain all failures or qualifications exactly.

### Task 4: Verify, report and seal

**Files:**
- Modify: `docs/ESTIMATOR_PHYSICAL_REFUSAL_DIAGNOSIS_REPORT.md`
- Modify: `docs/superpowers/plans/2026-10-07-openvins-handoff-physical-attempt.md`
- Create: `evidence/openvins-handoff-physical-attempt-dev-1701.zip`

**Interfaces:**
- Consumes: Tasks 1–3 evidence and tests.
- Produces: reviewable report, archive, commit and PR update; a precise next dependency.

- [ ] Run focused tests, changed-file Ruff, `git diff --check`, and the full suite with this worktree's `src` first on `PYTHONPATH`.
- [ ] Update the report with what ran, first refusal or passed gates, timing scope, all false qualifications and remaining risk.
- [ ] Seal the prior archive, complete immutable attempt evidence, source/tests/spec/plan/report and verification logs with ZIP CRC and per-member hashes.
- [ ] Commit, push and update draft PR65; update the monitoring automation to the next verified dependency without authorizing a blind retry.
