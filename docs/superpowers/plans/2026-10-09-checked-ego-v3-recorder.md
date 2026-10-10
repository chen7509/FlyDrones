# Checked EGO v3 recorder plan

**Goal:** Bind a gate-checked observation, a same-time EGO reference, and that observation's depth-validity mask into the opt-in v3 archive without changing legacy recorder behavior.

**Spec:** `docs/superpowers/specs/2026-10-09-checked-ego-v3-recorder-design.md`

**Files:** `src/flydrones/connectome_training/{recorder,dataset}.py`, `tests/connectome_training/{test_capture_input_gate,test_depth_validity,test_dataset}.py`, and a stage report/evidence archive.

- [x] Add RED synthetic tests for v3 checked round-trip with two references, exact mask and padded horizon; malformed/old reference, truth source, mixed modes, no partial mutation, direct-finish refusal, and legacy v2 preservation. A review-added RED run also caught missing command/gain checks.
- [x] Implement a separate checked append path using the existing capture and EGO reference validators, derive the mask from a copy of the validated image, and keep all append mutations transactional.
- [x] Run targeted and full connectome regressions, changed-file Ruff and diff check; retain all RED/GREEN logs. The final full-suite rerun after array-copy hardening is recorded separately.
- [x] Independently review source and tests. Three Important data-integrity findings were reproduced with RED tests and resolved: float32 overflow, type-changing coercion before the gate, and camera-buffer mutation after validation. Final read-only re-review found no remaining Important/Critical issue. Report the remaining backend dependency, seal evidence, commit and push only to `personal`.
