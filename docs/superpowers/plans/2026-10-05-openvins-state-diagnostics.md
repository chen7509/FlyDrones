# OpenVINS State Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Observe prearm VIO states and reject invalid diagnostic streams without enabling fusion.
**Spec:** docs/superpowers/specs/2026-10-05-openvins-state-diagnostics-design.md
**Architecture:** Standalone GPL-linked read-only C++ probe plus offline Python auditor; fixed library/input/config and old CSV parity.

- [x] Write failing tests for strict field/stream validation, numeric health, stale/future states, lost initialization, covariance corruption, prearm completeness and the dangling incomplete marker; implement and run focused tests.
- [x] Adapt the sealed runner into tools/benchmark/openvins_state_probe.cpp, export actual internal fields/covariance via read-only subclass, compile against pinned unchanged library, log provenance.
- [x] Replay fixed input once into new results/openvins-state-diagnostics-dev-1701; compare old CSV byte-for-byte; audit all rows and prearm window. Preserve every failure, never regenerate inputs or weaken thresholds.
- [x] Run appropriate regression and independent final review; 607 Python tests plus standalone C++ output protection passed. Original replay producer v1 preserved; revised I/O producer compiled/tested separately, not re-replayed.
- [ ] Seal evidence and submit stacked draft PR (record completion in Git/PR metadata; do not rewrite sealed archives).

Review focus: stale latched ZUPT vs per-frame event; covariance native ordering vs PX4 ordering; absent reset/quality/arrival metadata; invalid values masked by pre-init sentinel; read-only probe changes original CSV. No real-time or online fusion claims.
