# Estimator-heartbeat retry prepare-only plan

**Goal:** Bind the immutable `study-v11` routing refusal and exact correction archive into a new audited package, then exercise only the production startup-preflight path.

**Spec:** `docs/superpowers/specs/2026-10-07-estimator-heartbeat-retry-preflight-design.md`

- [x] Confirm no competing simulator, estimator, training or test process and freeze the immutable inputs and output contract.
- [x] Add RED tests for the failed-attempt validator, correction archive validator, resource gate and package member gate.
- [x] Implement the minimal prepare-only builder and independent auditor without changing workload, safety or timing limits.
- [ ] Retain `study-v12` and its post-Ruff `binding baseline` refusal; commit the stable code, then re-audit fresh `study-v13` from the committed tree.
- [ ] Run one production `--startup-preflight` at `study-v13/startup-preflight-v1`; independently audit it and retain cleanup/resource evidence.
- [ ] Run targeted/full regressions, update report/PR, seal evidence and record the next dependency. Do not create a physical `capture-v1`.
