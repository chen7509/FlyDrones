# Implement frozen OpenVINS track geometry audit

**Scope:** One diagnostic development episode, no new PX4/Gazebo run. Preserve
the fixed upstream, input, and config. Execute natively in this worktree.

## Task 1: Trace and parser

1. Add `tests/benchmark/test_openvins_track_geometry.py` asserting that a
   parser preserves a feature's camera ID, normalized UV, observation time and
   update-window time, including repeated IDs and malformed rows. Run it and
   confirm the expected missing-feature failure.
2. Add `tools/benchmark/audit_openvins_track_geometry.py` parser with an exact
   trace schema and rejection of malformed/nonfinite/out-of-order observations.
   Run the focused test to green.
3. Add a logging-only patch in the isolated pinned OpenVINS worktree after
   `clean_old_measurements`, rebuild its ROS-free shared library, and replay
   the fixed 604 images. Compare state CSV SHA-256 with the original and count
   exactly 183 exported post-clean candidate attempts. Save patch and trace.

## Task 2: PX4 reference pose and geometry

1. Add synthetic tests to the same test module for body-FRD to NED quaternion
   rotation, fixed `T_CtoI` composition, interpolated pose, known-point
   triangulation and reprojection, and invalid/reset/gap rejection. Watch them
   fail before implementation.
2. Implement pose extraction from ULog with optional pyulog import, then pure
   NumPy interpolation/geometry functions in
   `tools/benchmark/audit_openvins_track_geometry.py`. Use
   `timestamp_sample`, `xy_valid`, `z_valid` and reset counters. No fit of
   extrinsic, scale or time offset.
3. Score all trace attempts into a per-attempt CSV and aggregate JSON with
   unscored reasons. Recompute summaries from the CSV and keep both.

## Task 3: Evidence and verification

1. Record the exact upstream and PX4 versions, inputs/config/runner/binary
   hashes, trace, ULog hash, code patch, per-attempt CSV and aggregate JSON in a
   non-overwriting indexed evidence ZIP. Verify every archived file's hash.
2. Write `docs/OPENVINS_TRACK_GEOMETRY_REPORT.md` with observed outcomes,
   failure cases and the next single hypothesis. Do not label an EKF reference
   as VIO truth or claim EKF2 visual fusion.
3. Run focused tests, Ruff, `git diff --check`, then full `pytest -q`. Review
   any failures. Commit and create a draft PR based on the previous diagnostic
   branch only after checking the evidence and worktree.

## Review focus

- Quaternion direction must match PX4's body-to-NED documentation.
- Reused feature IDs must not be collapsed into unique landmarks.
- Missing or reset PX4 local pose must not be interpolated across.
- OpenVINS states must remain byte-identical after instrumentation.
- A positive EKF geometry check is not a VIO or flight-safety pass.
