# Partial-depth capture gate design (2026-10-09)

## Problem

The benchmark camera normalizer replaces out-of-range and non-finite returns with `NaN`. The new sequence-v3 archive preserves a pixel mask, but `validate_capture_input()` currently requires every depth pixel to be finite. Consequently a partially missing yet otherwise usable normalized frame cannot pass the future student-capture gate. The gate also currently accepts zero depth, which the normalizer would have marked invalid. This is a local contract contradiction, not a failed live PX4/EGO capture.

## Contract

Keep all existing PX4 EKF2, calibrated camera, timestamp, pinned teacher inspection, and Gazebo-truth rejection checks. For the normalized depth frame, require matching uint8 RGB geometry and a float32 depth image. Permit `NaN` only as an invalid pixel marker. Every non-NaN value must be finite and strictly positive, and at least one positive finite pixel must exist. Reject positive or negative infinity, zero, negative distances, non-float32 depth, and a wholly invalid image. The subsequent v3 recorder must derive `depth_valid` from this same validated depth array, not a separate truth or synthetic image; that recorder and live producer are separate work.

The all-invalid image remains preservable by the generic v3 archive for failure analysis, but cannot be treated as a valid teacher observation through this capture gate. The gate validates claimed sources and a pinned inspection record; it cannot itself attest that a live PX4 stream or EGO process exists. Passing synthetic unit tests therefore never authorizes training, fusion, flight or a fair comparison.

## Alternatives

Replacing NaN with far clip would invent observed free space. Rejecting every NaN would leave the new archive unusable for ordinary partial returns. Accepting an all-invalid frame as a healthy teacher observation would allow a sensor outage to masquerade as normal input. Preserving distinct REP 117 invalid categories would need an earlier change to the gateway normalizer; this stage does not reconstruct lost categories.

## Verification

Synthetic gate tests must show partial NaN passes without altering source, clock or inspection checks; the encoded EGO observation retains the non-finite pixel as image bytes. All-NaN, infinity, zero, negative, float64, malformed geometry and truth-backed inputs must fail. Existing capture gate and sequence-v3 tests must regress. No Docker planner or PX4/Gazebo process is needed for this contract test.
