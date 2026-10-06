# Estimator Physical Refusal Diagnosis Implementation Plan

**Goal:** Diagnose and close the two pre-motion refusals from the one `study-v2/capture-v1` attempt without rerunning it.

**Spec:** `docs/superpowers/specs/2026-10-06-estimator-physical-refusal-diagnosis-design.md`

- [x] Preserve the 10 ms capture failure, process-cleanup result, and exact downstream false classifications.
- [x] Add RED tests for the valid 1 ms source lead, excessive lead, and inconsistent derived simulation age.
- [x] Implement the minimum readiness validation change and run focused tests, Ruff, and diff checks.
- [x] Identify every first-step mapping and its installed package owner; record the mutable Mesa cache separately.
- [ ] Implement a no-PX4/no-OpenVINS isolated first-render-step probe with prospectively declared `MESA_SHADER_CACHE_DISABLE=true`.
- [ ] Freeze package versions, copyright/license evidence, paths, hashes, compiler/runtime inputs, and exact added mappings; independently audit the probe.
- [ ] Build and independently audit `study-v3` with the fixed timestamp contract and qualified renderer closure. Do not execute its command in the prepare stage.
- [ ] Only after the new package passes, perform at most one capture at `study-v3/capture-v1`; preserve every failure and never overwrite `study-v2/capture-v1`.
