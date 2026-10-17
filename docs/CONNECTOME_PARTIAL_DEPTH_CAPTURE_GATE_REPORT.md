# Partial-depth student capture gate (2026-10-09)

## Result

The local `validate_capture_input()` contract now accepts a normalized float32 RGB-D frame with some `NaN` depth pixels when at least one positive finite depth remains. It still rejects all-invalid images, infinities, zero or negative depths, mismatched geometry and non-float32 depth. Existing PX4 EKF2 source, calibrated camera pose, clock, pinned teacher-inspection and Gazebo-truth checks are unchanged. A partly missing depth image is no longer blocked before the opt-in v3 archive can preserve its per-pixel validity.

This is an interface contract test. It did not connect a live PX4 EKF2 source, calibrated camera or EGO planner; a caller can supply synthetic evidence in the tests. No v3 live recorder, student training, flight controller publication or physical comparison is authorized by this change.

## Verification

The new tests first failed for partial `NaN` acceptance, zero-depth rejection and float64 rejection; the original RED output is retained. After the one-predicate change, 62 targeted capture, archive, recorder and benchmark sensor/adapter tests passed, as did changed-file Ruff and `git diff --check`. The full connectome suite passed **253 tests, skipped 1**, with one PyTorch sparse-tensor warning. The partial-NaN test confirms the existing EGO observation encoder keeps the missing pixel in its depth image bytes and that the PX4 estimator flag still gates acceptance. Synthetic all-invalid and malformed depth cases remain rejected. Logs are retained in `results/connectome-partial-depth-gate-dev-1701/`.

## Remaining dependency

The current `TeacherSequenceRecorder` still writes legacy frames without a `depth_valid` field, and no deployment-visible producer links real PX4/EKF2 state, calibrated camera pose and pinned EGO references to a v3 sequence. The next producer must derive its mask from the exact validated normalized frame, bind source identity and times before append, preserve failures, and refuse formal comparison worlds as training data. The old 12-feature learner still refuses v3; a separately identified mask-aware feature and full-connectome input-neuron mapping is required. Physical VIO→EKF2, five-drone RTF and hardware gates remain unchanged.
