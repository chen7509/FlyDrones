# OpenVINS State Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Observe prearm VIO states and reject invalid diagnostic streams without enabling fusion.
**Spec:** docs/superpowers/specs/2026-10-05-openvins-state-diagnostics-design.md
**Architecture:** Standalone GPL-linked read-only C++ probe plus offline Python auditor; fixed library/input/config and old CSV parity.

- [ ] Write failing tests for strict field/stream validation, numeric health, stale/future states, lost initialization, covariance corruption, prearm completeness and the dangling incomplete marker; implement and run focused tests.
- [ ] Adapt the sealed runner into tools/benchmark/openvins_state_probe.cpp, export actual internal fields/covariance via read-only subclass, compile against pinned unchanged library, log provenance.
- [ ] Replay fixed input once into new results/openvins-state-diagnostics-dev-1701; compare old CSV byte-for-byte; audit all rows and prearm window. Preserve every failure, never regenerate inputs or weaken thresholds.
- [ ] Run appropriate regression, independent final review, seal evidence and report explicit passed/failed/unverified boundaries, submit stacked draft PR.

Review focus: stale latched ZUPT vs per-frame event; covariance native ordering vs PX4 ordering; absent reset/quality/arrival metadata; invalid values masked by pre-init sentinel; read-only probe changes original CSV. No real-time or online fusion claims.
