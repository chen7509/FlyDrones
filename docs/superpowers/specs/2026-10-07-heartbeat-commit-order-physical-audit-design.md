# Heartbeat commit-order physical audit design

## Goal

Seal and independently audit the single immutable `study-v21/capture-v1`
physical run.  The audit must preserve the completed 25 second run and its
failed VIO accuracy result.  It must not start PX4, Gazebo, OpenVINS or a
training process and must not modify the captured input.

## Evidence contract

The audit consumes the committed one-shot boundary plus its dispatch,
completion and output, the capture result, source and fan-out journals,
heartbeat observations, native request/acknowledgement/state session,
estimator readiness, fresh physical reference, force and physics traces,
runtime mappings, supervisor record and retained ULog.  It verifies exact
counts, monotonic identities, the unchanged execution profile, successful
process exits and the empty post-run resource scan.  File identities used for
diagnosis are recorded so later analysis cannot silently switch inputs.

Trajectory scoring reuses the frozen four-degree-of-freedom gauge contract:
the first internally initialized state selects the origin without truth, with
fixed scale and no time shift or later realignment.  Gazebo state is used only
for offline scoring.  Unknown reset and quality plus uncalibrated covariance
keep fusion closed even if public OpenVINS output is continuous.

## First-divergence diagnosis

Parse the fixed OpenVINS state stream, motion truth and native log.  Report
per-state position, velocity and attitude errors and accelerometer bias, then
identify the first crossings of the frozen accuracy screens.  Separately
record the five ZUPT-labelled states, actual physical displacement and
velocity during that interval, native ZUPT disparity/accept/reject messages,
and regular MSCKF/SLAM feature-update counts.

The pinned OpenVINS source is
`69488123ed9362dd44b6f28e7f4680abbff1442b` (GPL-3.0, non-archived at the
recorded lookup, last recorded push 2025-11-30; current maintenance cadence
uncertain).  Its `UpdaterZeroVelocity` permits the disparity test to override
chi-square and estimated-speed rejection, then updates accelerometer bias.
`VioManager` returns immediately after an accepted ZUPT.  The official API,
calibration guide and Geneva et al. ICRA 2020 paper are algorithm context;
they do not prove this configuration calibrated or accurate.  Existing
source snapshots are reused and no dependency is added.

The diagnosis may conclude that real support motion was accepted as ZUPT and
that the accepted interval coincides with a large vertical bias change.  It
must call this the first demonstrated failure mechanism, not proof that every
later metre of drift has a single cause.  It must retain sparse visual updates
as a separate inability to correct the corrupted inertial state.

## Claims and next gate

Passing the evidence audit qualifies only the integrity and classification of
this physical attempt.  VIO accuracy, estimator health, covariance, reset,
quality, ODOMETRY, EKF2 fusion, arming, flight and fruit-fly policy remain
false.  No new physical run or parameter change is allowed until this fixed
input diagnosis, report, tests and evidence archive are reviewed and a
separate correction specification is frozen.
