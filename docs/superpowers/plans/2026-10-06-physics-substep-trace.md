# Physics substep diagnostic plan

> Execute inline with superpowers:executing-plans; one fresh whole-branch review after implementation/evidence.

**Goal:** Distinguish full-rate physics consistency from quarter-rate sampling effects.
**Architecture:** Isolated bounded pre/post trace attached to existing disarmed fixture, explicit sensor-only CLI mode, pure offline phase analysis.
**Tech stack:** Installed Gazebo8.15/PX4, Python/numpy/scipy, no estimator or dependency installation.
**Spec:** docs/superpowers/specs/2026-10-06-physics-substep-trace.md

## Global constraints
Keep physical and sensor rates/force unchanged; native worker omitted explicitly, so no workload/RTF comparison. Truth only in external fixture/diagnostics. All failures preserved. Current worktree/standing user authority; no new task or repeat approval.

## Review focus
Missing post callback at shutdown; pre/post state-time convention; short/failed writes and cleanup failures; sensor-only flag accidentally bypassing source/unarmed guards; attribution from phase-biased integrals.

### Task1: Trace and capture contract
- [x] Record official callback semantics and actual installed backend provenance research.
- [x] Add failing tests for SubstepTrace, phase_closures and parse_capture_args mode combinations.
- [x] Implement bounded trace, optional fixture hook and explicit sensor-only diagnostic with source watchdog retained; targeted GREEN.

### Task2: Frozen physical evidence
- [x] Freeze prospective condition/code/model/binary/package metadata and check no competitors.
- [x] One25s attempt; audit timestamps/continuity/full-rate and phase closure, source rates, force, noarmULog, runtime backend map and cleanup.
- [x] Report actual outcome and remaining uncertainty, no VIO/RTF success claim.

### Task3: Review and seal
- [x] Regression, one independent review and one correction pass as needed.
- [x] Seal evidence, stacked draft PR, attach, update existing continuation to next supported dependency.
