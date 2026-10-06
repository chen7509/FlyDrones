# Heartbeat simulation-time physical retry implementation plan

**Goal:** Bind the dual-clock heartbeat correction into one audited `study-v16` package and execute at most one unchanged physical development attempt.

**Spec:** `docs/superpowers/specs/2026-10-07-heartbeat-sim-time-physical-retry-design.md`

### Task 1: Build and audit the prepare-only package

- [x] Add RED tests for source/audit/archive drift, destination reuse, execution drift, runtime-baseline drift and overclaims.
- [x] Implement the minimal prepare-only generator and independent auditor.
- [x] Generate `study-v16`, audit it, commit the boundary and rerun the audit from the committed head.

### Task 2: Run the startup-only preflight

- [x] Execute exactly one startup preflight at `study-v16/startup-preflight-v1`.
- [x] Audit phase exclusion, runtime files, supervisor cleanup, resources and package membership.
- [x] Seal and commit the startup-qualified physical boundary.

### Task 3: Execute one immutable physical attempt

- [ ] Verify exact head/archive/audits/destination and empty resources in a one-shot wrapper.
- [ ] Run `study-v16/capture-v1` once and retain success or failure without retry.
- [ ] Independently classify the earliest terminal cause and all downstream false claims.

### Task 4: Verify and report

- [ ] Run focused and full regressions, Ruff and diff checks.
- [ ] Update the diagnosis report, seal evidence, push PR65 and advance the automation only to the next proven dependency.
