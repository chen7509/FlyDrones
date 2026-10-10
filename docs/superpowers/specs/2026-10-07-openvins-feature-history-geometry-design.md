# OpenVINS feature history and geometry diagnosis

## Problem

The fixed feature-rejection trace shows that 1,202 of 1,235 MSCKF
candidates are removed after clone-time cleaning because fewer than two
measurements remain, while 114 of 160 delayed-SLAM candidates fail linear
triangulation.  The aggregate counters do not distinguish short tracker
lifetimes from clone-window pruning, or identify which fixed upstream
triangulation validity check rejects the delayed landmarks.

## Fixed boundary

Use OpenVINS commit `69488123ed9362dd44b6f28e7f4680abbff1442b`,
the qualified motion-intent adapter, and the immutable
`study-v21/capture-v1` requests and images.  Build a new isolated
GPL-3.0-or-later diagnostic library by applying the preceding feature-trace
patch and an additional history/geometry-only patch.  Do not start PX4 or
Gazebo, change a configuration value, threshold, feature order, branch,
random source, image, IMU record, motion command, or state value.

The uninstrumented replay remains the semantic control.  Every non-timing
camera-state field must match control within `1e-12`.

## History trace

For every MSCKF and delayed-SLAM candidate, record its exact feature ID,
selection origin, total measurement count and first/last timestamp before
cleaning.  At updater entry, record the count and range before and after
`clean_old_measurements`, the number removed, camera count, current clone
count and clone time range.  A strict audit must classify each insufficient
MSCKF candidate as:

- `raw_short`: fewer than two measurements existed before clone cleaning;
- `clone_pruned`: at least two existed before cleaning but fewer than two
  matched current clone timestamps.

Records must reconcile one-for-one with the existing `FD_PIPE`, `FD_MSCKF`
and `FD_SLAM_DELAY` inputs.  Duplicate IDs, unknown origins, inconsistent
counts, missing records or candidates that cross stages fail the audit.

## Geometry trace

For every candidate that reaches fixed upstream 3-D triangulation, record the
actual feature ID and the quantities already used by `FeatureInitializer`:
measurement count, anchor identity/time, linear-system condition number,
anchor-frame depth and the exact condition/depth/non-finite rejection flags.
Add diagnostic-only maximum anchor baseline, pairwise camera baseline and
angular parallax.  Non-finite raw quantities use an explicit finite flag and
a finite placeholder so log parsing remains deterministic; the original
upstream rejection expression remains unchanged.

The fixed configuration uses 3-D triangulation and nonlinear refinement.
The trace must still fail closed if an unexpected 1-D call appears.  A
geometry record must occur exactly once for each post-cleaning candidate and
its acceptance must reconcile with the updater counters.  The audit may
report geometry distributions and exact rejection flag combinations; it may
not infer that an untested parameter change would improve VIO.

## Evidence and failure handling

The MIT-side parser accepts only the documented structured fields and rejects
unknown, missing, non-finite, negative, inconsistent, duplicate or out-of-
session records.  Tests cover short raw histories, clone pruning, timestamp
identity, multiple rejection flags, zero baseline/non-finite geometry,
pre-initialization and duplicate motion-intent refusal, truncated logs,
short-write/close failure and archive tampering.

Retain raw logs, both patches, build identities, fixed requests, state
equivalence, all failed attempts and the final independent audit.  The result
can localize the observed fixed-input mechanisms.  It cannot qualify physical
VIO, authorize tuning or another physical run, establish online latency, or
enable ODOMETRY, arming, EKF2 injection or fusion.
