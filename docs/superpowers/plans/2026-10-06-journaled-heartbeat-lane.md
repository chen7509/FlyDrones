# Journaled heartbeat lane implementation plan

> For agentic workers: use superpowers:executing-plans inline, standing user authorization.

**Goal:** Decouple actual heartbeat observation journal from native processing without weakening failure gates.
**Architecture:** Opt-in subclass of ReadyShadowFanout, wrapping only heartbeat readiness reconciliation; existing writer and native ownership unchanged.
**Tech stack:** Python3.12 threading, existing PX4/pymavlink receiver and test doubles.
**Spec:** docs/superpowers/specs/2026-10-06-journaled-heartbeat-lane.md.

## Constraints and review focus
No physical/estimator run. Original2s limits and32unmatched bound. Observation != estimator commit; gate failure atomic with journal update. No old evidence rewrite. Review clocks/identities, hidden consumer failure, constructor/close failure, concurrency and opt-in CLI.

## Tasks
- [x] Record fixed source clock and maintenance/license research; inspect installed configuration read-only.
- [x] Add failing tests for tools/benchmark/journaled_heartbeat_lane.py, implement minimal observation/reconciliation/fail-lock lifecycle.
- [x] Add failing receiver-helper/profile tests; integrate explicit new profile in capture_disarmed_sensors.py, preserving old mode.
- [x] Exercise fixed PR48 timing with synthetic sink and raw-event identity; retain virtual-time disclaimer.
- [x] Targeted/full regression, independent review, report and evidence seal, draft PR. Record remaining runtime-freeze/timeout/origin gates before any future physics.
