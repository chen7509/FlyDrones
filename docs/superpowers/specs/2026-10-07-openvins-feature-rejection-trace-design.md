# OpenVINS feature rejection trace design

## Problem

The sealed physical run contains 217 regular update opportunities but only two
one-feature MSCKF updates and no SLAM feature update.  A separate image proxy
cannot identify whether the loss occurs in FAST/KLT, database lifetime,
candidate selection, triangulation/refinement, or chi-square rejection.

## Fixed boundary

Use OpenVINS commit `69488123ed9362dd44b6f28e7f4680abbff1442b` and the two
already disclosed initialization-only log patches.  Build a separate
GPL-3.0-or-later diagnostic library.  The patch may add counters and structured
logging to `TrackKLT`, `VioManager`, `UpdaterMSCKF`, and, only if candidates
reach it, `UpdaterSLAM`; it must not change a threshold, state value, branch
condition, feature ordering, random source, configuration, or input.

Replay the immutable `study-v21/capture-v1` native requests and PPM payloads
through the same single worker with the qualified motion-intent handoff.  Do
not start PX4 or Gazebo.  Preserve the uninstrumented replay as the semantic
control and compare estimator state values on identical camera samples.

## Trace contract

Each camera must produce strict, parseable records:

- `FD_TRACK`: previous active IDs, topped-off KLT input, combined KLT/RANSAC rejection,
  out-of-bounds rejection, mask rejection, and accepted current tracks.
- `FD_PIPE`: database size and lost/marginal/max-track/SLAM/MSCKF candidate and
  accepted counts at the actual update path.
- `FD_MSCKF`: input, insufficient-measurement, triangulation, refinement,
  chi-square, and accepted counts.  Rejection categories must sum exactly to
  input.
- `FD_SLAM_DELAY` / `FD_SLAM_UPDATE` are required only if nonzero SLAM
  candidates occur; zero input remains explicit in `FD_PIPE`.

The parser rejects unknown fields, non-finite or non-integer values, negative
counts, impossible sums, duplicate non-SLAM stages, missing per-camera track
rows, or a pipeline count that disagrees with the updater input. OpenVINS can
invoke its fiducial and ordinary SLAM updater separately at one timestamp, so
those records are summed only after each strict record parses; their aggregate
must match the single pipeline total. Raw log bytes and the diagnostic patch
are evidence; a post-hoc reconstructed count is not.

## Equivalence and claims

The diagnostic build qualifies only if the fixed-input camera state sequence,
initialization flags, motion latch, IMU state values, and closed fusion fields
match an uninstrumented control within a prospectively fixed numerical
tolerance.  Timing is excluded from equivalence and cannot be reported as
online latency.

The result may classify the first evidenced feature-loss stage.  It cannot
qualify physical VIO, tune the sealed test, claim that logging is production
safe, or authorize ODOMETRY, arming, EKF2 injection, or another physical run.
