# Fixed-input inertial consistency plan

> Execute inline with superpowers:executing-plans, one fresh-context whole-branch review at end.

**Goal:** Locate the first failure boundary with fixed sealed inputs.
**Architecture:** Pure Python offline packet and inertial closure audit; truth is diagnostics only.
**Tech stack:** Existing numpy/scipy/pytest, pinned upstream source, no new runtime.
**Spec:** docs/superpowers/specs/2026-10-06-openvins-inertial-consistency.md

## Global constraints
PR37 immutable input, no physical/native rerun or tuning; reject invalid data; preserve all failures. Standing authorization covers all design/tests/review/draft publication. Existing full-repo lint50errors remains explicit; no unrelated cleanup.

## Review focus
Endpoint interpolation masquerading as exact data; quaternion/frame/gravity sign; packet order/hash ambiguity; nonfinite/duplicate/gapped samples; inference from sampled acceleration versus unobserved1ms dynamics.

### Task1: Audit implementation and fixed input
- [x] Research native/simulator boundary and record pinned sources, license/cost/reasons.
- [x] Write failing synthetic tests for audit_inertial_window and audit_imu_delivery in tools/benchmark/audit_inertial_consistency.py.
- [x] Implement minimal pure audit, run GREEN and then one sealed-input audit with all prospectively selected windows.
- [x] Report actual mismatches and limits; do not claim aliasing/engine root cause without missing-rate evidence.

### Task2: Review and publication
- [x] Run applicable regression, one independent whole-branch review and one correction pass if needed.
- [ ] Seal evidence, publish stacked draft PR, attach, update ongoing heartbeat to actual next dependency.
