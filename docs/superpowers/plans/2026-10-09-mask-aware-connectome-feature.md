# Mask-aware connectome feature plan

**Spec:** `docs/superpowers/specs/2026-10-09-mask-aware-connectome-feature-design.md`

## Task 1: Explicit v3 feature reduction

**Files:** `features.py`, `tests/connectome_training/test_depth_validity.py`, `tests/connectome_training/test_inference_artifact.py`.

- [x] Add RED tests for exact 15-feature order, valid-only medians and fractions, empty-sector representation, all-invalid refusal, malformed mask/depth, and unchanged legacy outputs.
- [x] Add `MASKED_FEATURE_NAMES`, `feature_profile_for_names()` and explicit `profile` selection in `frame_features()` / `sequence_tensors()`. Keep legacy default and refusal of v3 through that default.
- [x] Run focused GREEN and adjacent feature tests.

## Task 2: Model mapping and curriculum identity

**Files:** `parameters.py`, `model.py`, `curriculum_session.py`, trainer tests.

- [x] RED: v3 mapping missing a channel is refused; v3 name reordering changes identity; v1 digest stays exact; mixed v1/v3 curriculum is refused before model construction.
- [x] Bind the v3 name/version into its mapping digest; require complete v3 feature coverage. Store selected feature order on the core, pass it to sequence tensorization, and bind it in full curriculum loading/checkpoints. Leave synthetic smoke legacy.
- [x] Run focused GREEN and resume/rollback tests.

## Task 3: Inference parity and fail-closed loading

**Files:** `inference_artifact.py`, `inference.py`, tests.

- [x] Test matching v3 tiny artifact and masked controller (initially RED), direct-core parity, v1/v3 frame refusal, unchanged v1 loading, and both checkpoint mismatch directions (review additions).
- [x] Select the exact profile from parameter names, carry it in provenance and use it in the controller without altering high-level safety limits or flight eligibility.
- [x] Run focused GREEN, full connectome and repository regressions, changed Ruff and diff check.

## Task 4: Evidence and review

- [x] Independent read-only review of data leakage, profile/version identity and legacy compatibility; fix reproduced findings with tests.
- [x] Write status report and seal source/test/failure evidence with member hashes and CRC. State that no real v3 training or flight result exists.

After verification, commit only this stage's files and push to `personal` on draft PR65.
