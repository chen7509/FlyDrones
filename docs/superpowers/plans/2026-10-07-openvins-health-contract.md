# OpenVINS Health Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce fail-closed quality/reset/covariance evidence for the passing OpenVINS physical workload before any ODOMETRY or EKF2 integration.

**Architecture:** A small pure-Python health state machine validates native camera-state evidence and estimator-session transitions.  The GPL-linked native probe exposes the exact 15x15 IMU covariance needed by the state machine but does not decide fusion eligibility.  Offline cohort tooling evaluates a predeclared conservative covariance envelope on development and held-out physical runs.

**Tech Stack:** Python 3.12, pytest, NumPy/SciPy, C++17, pinned OpenVINS, PX4/Gazebo SITL evidence harness.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-health-contract-design.md`

## Global Constraints

- Keep ODOMETRY publication, EKF2 injection, arming, training, and multi-aircraft execution disabled.
- Keep the 25 s, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGB-D workload and current safety thresholds unchanged.
- Use only MAVLink quality values `-1`, `0`, and `1`; never infer a higher score.
- Never use Gazebo truth in the online estimator or health state machine.
- Preserve all failures, immutable evidence, configuration hashes, ULog, trajectories, and process records.
- Simulation-domain covariance qualification is not hardware, HITL, or flight calibration.

## Review Focus

- A public-initialized sample with a stale regular visual update must remain quality `0`.
- A state-time regression or initialized-state reversion must latch quality `-1`.
- Native covariance with NaN, asymmetry, or a materially negative eigenvalue must fail closed.
- Reusing or rolling back a session/reset identity must be rejected, including 255-to-0 wire wrap.
- Partial delivery followed by source/native failure must not emit a later positive quality.

---

### Task 1: Pure health state machine

**Files:**
- Create: `tools/benchmark/openvins_health_contract.py`
- Create: `tests/benchmark/test_openvins_health_contract.py`

**Interfaces:**
- Produces: `CovarianceProfile`, `OpenVinsHealthContract.accept_camera(row, source_health)`, `OpenVinsHealthContract.fail(reason)`, and `OpenVinsHealthContract.replace_session(new_session_id)`.

- [ ] Write failing tests for unknown/valid/failed quality, visual-update age, covariance structure, latched failure, session replacement, duplicate identity, rollback, and reset wrap.
- [ ] Run `python -m pytest tests/benchmark/test_openvins_health_contract.py -q` and confirm failure because the module is absent.
- [ ] Implement the smallest state machine and fixed covariance profile that satisfies the spec.
- [ ] Re-run the focused tests and commit.

### Task 2: Native covariance and health input exposure

**Files:**
- Modify: `tools/benchmark/openvins_online_probe.cpp`
- Modify: `tools/benchmark/openvins_online_shadow.py`
- Test: `tests/benchmark/test_openvins_online_shadow.py`
- Test: `tests/benchmark/check_openvins_online_probe.py`

**Interfaces:**
- Consumes: the Task 1 camera-row schema.
- Produces: camera acknowledgements containing the 15x15 native IMU covariance and session-local public/update flags; Python retains and validates these fields.

- [ ] Add failing protocol/schema tests for covariance length, finite values, malformed covariance, and unchanged motion-intent acknowledgements.
- [ ] Run the focused tests and preserve RED output.
- [ ] Add read-only covariance output using `StateHelper::get_marginal_covariance(state, {state->_imu})`; do not alter OpenVINS state or thresholds.
- [ ] Update the Python acknowledgement validator and fixed replay checks.
- [ ] Rebuild against the pinned OpenVINS library, run parse/fault/fixed-input tests, and commit.

### Task 3: Covariance cohort audit

**Files:**
- Create: `tools/benchmark/audit_openvins_health_cohort.py`
- Create: `tests/benchmark/test_audit_openvins_health_cohort.py`

**Interfaces:**
- Consumes: predeclared cohort manifest, per-run camera health rows, isolated offline truth, and existing trajectory audits.
- Produces: immutable per-component 3-sigma coverage, consecutive-violation counts, run failures, and `covariance_sim_domain_qualified`.

- [ ] Write failing tests for 99% coverage, five consecutive violations, missing failed runs, truth/session mismatch, and manifest mutation.
- [ ] Run the focused tests and preserve RED output.
- [ ] Implement deterministic cohort auditing without modifying the profile from observed validation data.
- [ ] Run focused tests, Ruff, and commit.

### Task 4: Fixed replay and fault rejection

**Files:**
- Modify: `tools/benchmark/replay_openvins_motion_intent.py`
- Add evidence under: `results/openvins-health-contract-dev-1701/`

**Interfaces:**
- Consumes: Tasks 1-2 native binary and the sealed study-v23 source stream.
- Produces: normal replay plus IMU silence, camera silence, truncated image, time regression, timeout, and process-restart evidence.

- [ ] Freeze source/binary/config hashes and the exact fault matrix before execution.
- [ ] Run normal fixed replay and every fault once; retain all failures and process cleanup evidence.
- [ ] Audit exact counts, quality/reset transitions, covariance profile, and absence of network/ODOMETRY output.
- [ ] Commit the implementation and fixed-input evidence boundary.

### Task 5: Physical development and held-out validation cohort

**Files:**
- Add immutable study configuration/results under: `results/openvins-health-physical-dev-1701/`
- Create: `docs/OPENVINS_HEALTH_CONTRACT_REPORT.md`
- Create: `evidence/openvins-health-contract-dev-1701.zip`

**Interfaces:**
- Consumes: Tasks 1-4 and the existing passing physical harness.
- Produces: frozen development profile, separately generated held-out cohort, health/fault results, and an explicit decision on simulation-domain covariance qualification.

- [ ] Predeclare development/held-out seeds and motion profiles without viewing held-out results.
- [ ] Run the development cohort, freeze the profile, then run every held-out case once; preserve all failures.
- [ ] Run explicit source-loss and native-restart shadow-only physical cases while unarmed.
- [ ] Audit accuracy, 3-sigma coverage, quality transitions, reset totals, ULog, process cleanup, and unchanged load.
- [ ] Run full pytest, changed-file Ruff, `git diff --check`, archive CRC/hash verification, update PR65, and commit/push.
- [ ] Keep fusion false unless every spec gate passes; even a pass authorizes only the subsequent VIO-to-EKF2 design stage.

