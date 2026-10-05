# Diagnostic Reference Freshness Implementation Plan

> Execute inline with superpowers:executing-plans under standing authorization. One independent whole-branch review before publication.

**Goal:** Find and document internally inconsistent cached-looking Link diagnostics without declaring VIO success.

**Architecture:** Pure offline validator/analyzer plus explicit timestamp provenance in future trace records. Existing raw data is read by hash from the PR41 archive; evidence is never overwritten.

**Tech Stack:** Existing Python/NumPy/pytest, installed Gazebo bindings for read-only capability inspection.

**Spec:** docs/superpowers/specs/2026-10-06-diagnostic-reference-freshness.md

## Task

- [x] Add synthetic acceleration, static, cached-field, timing/order/nonfinite/incomplete-input tests and provenance regression; confirm RED.
- [x] Implement tools/benchmark/diagnostic_reference_freshness.py and provenance fields in physics_substep_trace.py; targeted GREEN and changed Ruff.
- [x] Freeze implementation; run one fixed-input audit from sealed PR41 members, archive manifests and read-only upstream/binding evidence.
- [x] Report contradictory intervals, force-boundary examples and source hypothesis limitations; no physical or estimator replay.
- [x] Run full regression, obtain one independent review, correct findings with targeted failure tests.
- [x] Seal results and create stacked draft PR42; automation handoff uses sealed next-native-reference-research.md (publication recorded in report and ledger).
