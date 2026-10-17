# Connectome depth validity storage (2026-10-09)

## Result

The sequence archive now has an opt-in v3 schema that stores normalized float32 depth and an exact per-pixel boolean validity mask. A missing depth pixel remains missing, including when every pixel in a frame is invalid. V3 also requires the existing teacher-horizon validity array. The previous 12-feature extractor refuses all v3 frames, so this change does not authorize student training or silently interpret unknown space as clear. V1/v2 writing and loading retain their previous schemas.

This fixes a storage contract mismatch identified in code: the benchmark gateway normalizes depth outside its configured range or non-finite input to `NaN`, while v1/v2 required all depth values to be finite. No deployment-visible corpus producer has yet been run, and no full MaleCNS learning result follows from this storage change.

## Implementation and evidence

- `SequenceFrame.depth_valid` is optional. V3 requires it on every frame; mixed v3/legacy frames fail before output.
- The mask must have boolean dtype, the exact depth geometry, and equal `isfinite(depth_m) & (depth_m > 0)` at every pixel. V3 also checks float32 depth and matching uint8 RGB geometry.
- The v3 NPZ includes `depth_valid` and `teacher_horizon_valid` under the existing archive digest. The loader checks the exact schema-specific array key set and revalidates the restored sequence.
- `frame_features` refuses v3, even when its pixels are all valid. The old feature count, model inputs and parameter artifacts were not changed.
- New tests cover NaN and all-invalid round trips, malformed masks, geometry/dtype, mixed modes, absent horizon validity, archive hash tampering, legacy v2 round trip, and old-feature refusal.

The first new-test run failed as expected before implementation (`results/connectome-depth-validity-dev-1701/red.txt`). Targeted storage and recorder tests passed 19/19, and the training-entry tests passed 2/2. An initial full connectome suite run with only `src` on `PYTHONPATH` recorded 2 subprocess import failures (`ModuleNotFoundError: No module named 'tools'`), 245 passes and 1 skip. Repeating the affected module with both `src` and the repository root on `PYTHONPATH` passed 27/27; the full connectome suite under that environment passed **247, skipped 1** with one PyTorch warning. The first failed run remains in `results/connectome-depth-validity-dev-1701/green-connectome-suite.txt`; the successful run is in `green-connectome-suite-env.txt`. No product change was made to hide that test-launch environment issue.

## Boundaries and next dependency

This is archival schema validation, not a mask-aware training feature profile, live student capture, or a physical fly-versus-EGO comparison. The existing EGO planner smoke used synthetic ROS inputs and cannot be used as teacher training evidence. A subsequent, separately versioned feature/parameter mapping must expose depth coverage to the full connectome model and safety gate. A deployment-visible capture producer must prove the same normalized camera frame, PX4/EKF2 state, calibrated camera pose, source health, time alignment, pinned teacher output and failure retention before its v3 output can be treated as a real training corpus. Current VIO→EKF2 and five-drone capacity gates remain independent.
