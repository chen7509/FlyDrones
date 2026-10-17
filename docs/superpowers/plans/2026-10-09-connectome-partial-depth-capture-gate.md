# Partial-depth capture gate plan

**Goal:** Admit deployment-visible normalized RGB-D observations with partial missing depth while failing closed on a wholly missing or malformed frame.

**Spec:** `docs/superpowers/specs/2026-10-09-connectome-partial-depth-capture-gate-design.md`

**Scope:** `capture_input.py` and its contract tests only. Do not change the frozen comparison, the old sequence schemas, the EGO image, the flight stack or the unimplemented live capture producer.

- [x] Add failing tests for partial NaN acceptance with unchanged source/teacher checks and EGO image encoding; reject all-invalid, infinity, zero, negative, float64, malformed and truth-backed data.
- [x] Capture RED output, then implement the minimal normalized-depth predicate in `validate_capture_input()`.
- [x] Run capture gate, v3 storage and related benchmark sensor/adapter tests; run changed-file Ruff and diff check.
- [x] Review, report actual versus untested behavior, seal source/test/log evidence, commit and push to `personal` (ac9ac2c).
