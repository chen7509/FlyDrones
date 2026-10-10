# Heartbeat simulation-time readiness implementation plan

**Goal:** Remove the proven heartbeat clock-domain mismatch without weakening high-rate source or processing watchdogs.

**Spec:** `docs/superpowers/specs/2026-10-07-heartbeat-simulation-time-readiness-design.md`

### Task 1: Freeze design and sources

- [x] Record the immutable failure values and upstream PX4/MAVLink timing rationale.
- [x] Reject timeout inflation and dynamic RTF scaling; freeze the dual-clock contract.

### Task 2: Implement under TDD

- [x] Add RED cases for slow healthy simulation, true simulation silence, future/regressed stamps and stale high-rate sensors.
- [x] Implement the minimal `JournaledReadiness` dual-clock change with explicit proof diagnostics.
- [x] Run focused readiness, fan-out and estimator-readiness regressions.

### Task 3: Replay fixed evidence

- [x] Add a deterministic fixed-evidence auditor/replay with inverse counterfactual checks.
- [x] Run it on the immutable `study-v15` values without starting simulation or estimation.

### Task 4: Report and seal

- [x] Update the physical diagnosis report with the corrected policy boundary and remaining physical verification need.
- [x] Run changed-file Ruff, focused tests, full regression and diff checks.
- [x] Seal evidence, commit, push, update PR65 and move the automation to the next verified dependency.
