# Checked EGO v3 recorder design (2026-10-09)

## Observed dependency

`TeacherSequenceRecorder` currently copies an `Observation` and command into v1/v2 but never calls the capture-source gate and never emits a depth-validity mask. Its `finish_with_reference_horizon()` correctly uses only actually received EGO positions. The repository has no non-truth PX4 EKF2/camera-pose capture backend: `NativeGazeboPx4Backend` explicitly reports `gazebo_model_truth`. The new API is therefore an offline contract, not a live producer or permission to train.

## Interface and invariants

Add an opt-in `append_capture_checked()` path to the existing recorder. Before mutating any list, it shall:

1. Call `validate_capture_input(backend, observation, source_evidence, corpus_config)`, retaining its pinned-image, PX4 source, camera calibration, timing, frame-shape and truth-backend refusal.
2. Require a `Decision` marked `controller="ego"` whose exact reference fields pass the existing EGO `validate_reference()` at the current observation sim time (zero permitted age). Require a finite nonnegative tracking gain and recompute `track_reference()` to check that the command belongs to that reference and observed position. The reference must be a received position, not an invented horizon point.
3. Enforce recorder mode consistency: an existing legacy frame cannot be followed by a checked frame and vice versa. A failed append leaves frames, targets and references unchanged.
4. Preserve the original RGB-D ndarray/dtype contract, take an owned copy of the complete observation, and validate that copy before deriving `depth_valid` from its float32 depth image (`isfinite & >0`). Reject any persisted numeric value that would become non-finite in float32 before mutating the recorder. The v3 archive also rejects infinite and nonpositive depth even when a mask marks it invalid; NaN remains representable as missing depth. Caller buffer reuse after validation must not change the stored frame. The initial one-point horizon placeholder is the received position; only `finish_with_reference_horizon()` may create the final masked multi-point horizon. Direct `finish()` on checked frames must continue to fail v3's required horizon-validity gate.

The method still accepts Python objects supplied by its caller. The gate checks claims and a pinned inspection record but cannot prove that a running PX4 estimator, calibrated camera or EGO process produced them; that needs a separate owned live capture implementation and physical validation. `SequenceProvenance`'s world/config/source binding is still supplied by the caller. The checked path must never be used to reclassify existing Gazebo-truth benchmark output or synthetic EGO smoke as a qualified training sequence.

## Verification

Synthetic tests exercise partial NaN round-trip to v3 with exact mask, two received references and a padded future horizon, legacy v1/v2 compatibility, truth/stale/invalid-EGO rejection, mixed-mode refusal, unchanged state after each failure, float32 overflow refusal, original type preservation, camera-buffer reuse, invalid v3 depth refusal, and direct-finish refusal. No PX4/Gazebo, Docker planner or full MaleCNS run is needed. The stage report must distinguish the unit-level interface from the missing live producer.
