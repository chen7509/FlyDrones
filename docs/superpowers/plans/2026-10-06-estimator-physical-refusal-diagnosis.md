# Estimator Physical Refusal Diagnosis Implementation Plan

**Goal:** Diagnose and close the two pre-motion refusals from the one `study-v2/capture-v1` attempt without rerunning it.

**Spec:** `docs/superpowers/specs/2026-10-06-estimator-physical-refusal-diagnosis-design.md`

- [x] Preserve the 10 ms capture failure, process-cleanup result, and exact downstream false classifications.
- [x] Add RED tests for the valid 1 ms source lead, excessive lead, and inconsistent derived simulation age.
- [x] Implement the minimum readiness validation change and run focused tests, Ruff, and diff checks.
- [x] Identify every first-step mapping and its installed package owner; record the mutable Mesa cache separately.
- [x] Implement a no-PX4/no-OpenVINS isolated first-render-step probe with prospectively declared `MESA_SHADER_CACHE_DISABLE=true`.
- [x] Freeze package versions, copyright/license evidence, paths, hashes, compiler/runtime inputs, and exact added mappings; independently audit the probe.
- [x] Build and independently audit corrected prepare-only packages with the fixed timestamp contract and qualified isolated renderer closure. `study-v3` remains an audit failure; `study-v4` exposed an execution-entry schema gap without creating a capture; immutable `study-v5` passed two independent audits.
- [x] Perform at most one actual capture at `study-v5/capture-v1`; preserve the startup runtime-binding refusal, do not rerun it, and keep `study-v2/capture-v1`, rejected packages, and launcher failures immutable.
