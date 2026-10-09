# Connectome Depth Validity Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve normalized missing depth pixels and an exact validity mask in a new corpus archive version without enabling unqualified training.

**Architecture:** `SequenceFrame` gains an optional mask. The v3 writer/loader stores mask plus the existing v2 horizon validity array, while v1/v2 remain unchanged. The current 12-feature extractor explicitly refuses v3 until a separately versioned feature and parameter mapping exists.

**Tech Stack:** Python 3.12, NumPy NPZ, PyTorch feature entry point, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-connectome-depth-validity-design.md`

## Global Constraints

- Do not change the frozen formal comparison, existing v1/v2 schemas, PX4/Gazebo or the upstream EGO image.
- `depth_valid` is true iff normalized `depth_m` is finite and greater than zero; it does not identify the cause of an invalid pixel.
- V3 requires the v2 `teacher_horizon_valid` array and must not authorize the 12-feature training path.
- Preserve all failure outputs and use a new output directory for each archive probe.

## Review Focus

- A boolean-looking integer mask must be rejected rather than silently cast.
- NaN marked valid and a finite positive depth marked invalid must both be rejected.
- A frame with every depth invalid must round-trip as evidence without becoming a trainable all-clear image.
- A masked frame mixed with an unmasked frame, or with a target lacking `horizon_valid`, must fail before creating output.
- Existing v1/v2 archives and parameter artifacts must retain their exact prior semantics.

### Task 1: Versioned depth storage and refusal boundary

**Files:**
- Modify: `src/flydrones/connectome_training/dataset.py`
- Modify: `src/flydrones/connectome_training/features.py`
- Create: `tests/connectome_training/test_depth_validity.py`

**Interfaces:**
- `SequenceFrame.depth_valid: np.ndarray | None = None` appended after existing fields.
- `SCHEMA_V3 = "flydrones-connectome-sequence-v3"`; v3 NPZ adds `depth_valid` and requires `teacher_horizon_valid`.
- `frame_features(frame)` raises `ValueError("masked depth feature profile not implemented")` for masked frames, even if every pixel is valid.

- [x] Write tests for a v3 NaN round trip, all-invalid round trip, schema and hash, mask dtype/shape/contents, mixed modes, missing horizon mask, tampered archive, legacy regression and feature refusal.
- [x] Run `PYTHONPATH=src python -m pytest tests/connectome_training/test_depth_validity.py -q` and retain the expected RED output.
- [x] Implement only the v3 storage/loader validation and explicit old-feature refusal; do not add a trainer or imputation.
- [x] Run the new tests and `tests/connectome_training/test_dataset.py`, `test_recorder.py`, `test_train_stage_b.py`, plus Ruff and `git diff --check`; retain GREEN output.
- [x] Review the diff for old-schema changes, update the stage report with achieved and untested claims, commit and push to `personal` (8758302).

### Task 2: Future capture integration gate

**Files:**
- Future design and tests for the actual deployment-visible capture producer; no product code in this plan.

**Interfaces:**
- The producer must derive the mask from the same normalized depth frame only after `validate_capture_input()` proves non-truth PX4/EKF2 and calibrated camera sources.
- The later feature/parameter profile must have a new identity; loading v3 into the 12-feature path stays rejected.

- [ ] When a live capture producer exists, independently specify its source identity, mask timing, teacher reference binding, fault retention and fail-closed rules before implementation.
