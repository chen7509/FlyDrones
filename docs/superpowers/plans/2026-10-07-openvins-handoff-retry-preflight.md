# OpenVINS handoff-corrected retry preflight plan

**Goal:** Build, commit-audit and non-physically preflight a fresh package that binds the initializer-handoff correction.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-handoff-retry-preflight-design.md`

- [x] Add RED tests for the exact correction archive/audit and immutable physical refusal.
- [x] Implement the strict prepare-only builder and independent auditor.
- [x] Retain rejected `study-v14`, then generate fresh `study-v15`, audit it, commit the implementation and audit it again.
- [x] Run exactly one production startup preflight at `study-v15/startup-preflight-v1`.
- [x] Audit startup evidence and confirm that the future physical destination remains absent.
- [x] Run focused/full verification, update the report/PR and seal evidence.
