# OpenVINS motion-intent and fixed-frame visual diagnosis design

## Purpose

The sealed `study-v21/capture-v1` run demonstrates two separate mechanisms: a
zero-velocity update was accepted after commanded physical motion began, and
the later visual path contributed only two one-feature MSCKF updates.  This
stage defines truth-independent contracts for both findings.  It does not
alter the sealed run, estimator thresholds, scene, noise, forces or camera
rate, and it does not authorize another physical run.

## Pinned upstream basis

The estimator remains OpenVINS commit
`69488123ed9362dd44b6f28e7f4680abbff1442b`, GPL-3.0.  The recorded repository
metadata says non-archived with last push `2025-11-30`; maintenance cadence is
uncertain.  The frozen `VioManager.cpp` only stops beginning-only ZUPT after
`has_moved_since_zupt` becomes true, which normally occurs after a successful
regular feature propagation.  `UpdaterZeroVelocity.cpp` can let a low image
disparity override velocity and chi-square rejection.  The official OpenVINS
ZUPT documentation describes the update as a stationary-motion constraint,
so an independently authorized nonzero motion command is valid negative
evidence for applying that constraint.  The existing OpenVINS adapter is a
GPL-linked research executable; the MIT Python control/evidence layer must not
copy upstream GPL implementation.

## Motion-intent contract

`MotionIntentGate` consumes only estimator acknowledgements and the safety
supervisor's authorized velocity/yaw setpoint.  Gazebo pose, velocity,
acceleration and all other truth fields are forbidden.  A command may be
created only after a causal internal-initialization acknowledgement, while the
vehicle remains unarmed, in one explicit estimator/clock session.  The command
must be nonzero, fresh, monotonically sequenced and have a future or current
simulation-time effective point.

The gate emits one immutable, hashed `motion_intent` action for the later
single-owner native transport.  No physical step at or after the effective
time is authorized until the same native session acknowledges that it applied
the intent, remained initialized and latched `has_moved_since_zupt=true`.
Missing, late, duplicate, mutated, reset, reconnected, armed or mismatched
evidence latches failure.  A new session requires a new gate; no silent reset
or replay is accepted.  The contract preserves static initialization because
it cannot emit before internal initialization and does not disable ZUPT
globally.

This stage implements and tests only that Python evidence/state contract.  A
later GPL-adapter stage must add a bounded native message and expose a narrow
subclass method that verifies `try_zupt=true` and
`zupt_only_at_beginning=true`, latches the already-existing protected movement
flag, acknowledges it before actuation and remains under the single native
worker.  Until that adapter and fixed-input replay pass, the contract is only
implemented, not integrated or physically validated.

## Fixed-frame visual diagnosis

The second tool reads the immutable RGB PPM files, frozen estimator config and
native log.  It verifies the selected front-end settings, exact image shape,
monotonic timestamps and file hashes, then reports deterministic Harris-corner
counts and phase-correlation translation/patch-retention statistics after the
same histogram equalization mode.  This dependency-free proxy is deliberately
separate from OpenVINS.  It is not OpenVINS'
internal feature database, does not reproduce its grid/RANSAC/marginalization
logic and cannot qualify VIO.

The log parser separately retains every OpenVINS MSCKF/SLAM update count and
ZUPT disparity feature count.  If raw frames contain corners and pairwise
tracks while OpenVINS still uses almost no update features, the result narrows
the issue to the internal tracking-to-update path; it does not select a
threshold change or prove a single root cause.  All low-texture, identical,
malformed or incomplete cases remain explicit rather than being discarded.

## Qualification boundary

Passing tests qualifies the truth-free evidence contract and read-only fixed
frame diagnostic only.  Native application of the motion latch, estimator
replay, corrected accuracy, calibrated covariance, reset/quality, ODOMETRY,
EKF2, arming, flight, swarm scaling and the fruit-fly comparison remain false.
