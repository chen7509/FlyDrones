# OpenVINS Health Contract Design

## Scope

The passing 25 s single-aircraft physical VIO run proves the existing accuracy
screens but still emits `quality=null`, `reset_counter=null`, and an
uncalibrated covariance.  This stage adds a fail-closed health contract before
any ODOMETRY publication or PX4 EKF2 injection.  It does not arm, publish,
train, or expand to multiple aircraft.

The contract is limited to the pinned OpenVINS commit
`69488123ed9362dd44b6f28e7f4680abbff1442b`, PX4 commit
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, the identity FRD camera/IMU/body
installation, and the existing 1 ms physics / 250 Hz raw IMU / 10 Hz RGB-D
development fixture.  Real hardware covariance qualification remains a
separate external requirement.

## Source decisions

- MAVLink ODOMETRY defines `quality=-1` as failed, `0` as unknown, `1` as the
  worst positive quality and `100` as the best.  The adapter therefore uses
  only `-1`, `0`, and `1`; it never invents a higher score.
- MAVLink requires the reset counter to increment whenever any pose, velocity,
  attitude, or angular-rate estimate resets.  The adapter treats every native
  estimator process/session replacement as an origin reset.  A first session
  starts at total reset `0`; each accepted replacement increments the total,
  and the wire value is `total % 256`.
- OpenVINS recommends NEES and component error-versus-bound plots to evaluate
  consistency.  A single passing run cannot establish statistical covariance
  calibration.  The contract first creates a conservative simulation-domain
  covariance envelope and keeps `covariance_sim_domain_qualified=false` until
  independent held-out physical runs pass the frozen envelope.
- The pinned PX4 receiver consumes ODOMETRY position, orientation, and linear
  velocity variance diagonals.  The existing `px4-d6f12ad-body-tangent`
  transform remains the only supported covariance convention.

## State machine

`OpenVinsHealthContract` owns one estimator session and has three output
states:

1. `UNKNOWN`: `quality=0`, before public initialization or before all required
   health evidence is available.
2. `VALID_MINIMUM`: `quality=1`, only while public initialization is true,
   the state timestamp equals the camera sample, the latest regular visual
   update is no older than 200 ms, source/native watchdogs are healthy, the
   covariance is finite/symmetric/PSD, and the frozen covariance profile has
   been qualified on held-out simulation runs.
3. `FAILED`: `quality=-1`, latched after a time regression, initialized-state
   reversion, session mismatch, source/native failure, invalid covariance, or
   reset without an explicit new-session transition.  No later sample can
   recover the same instance.

The initial process has reset total `0`.  `replace_session(new_id)` is the only
valid way to continue after a native process restart.  It returns a fresh
contract with reset total incremented exactly once and `quality=0` until the
new estimator becomes healthy.  Reusing an old session identity, rolling back
the total, or changing the session without replacement is rejected.

## Covariance profile

The profile is named `px4-d6f12ad-gate-floor-v1`.  It applies the existing
JPL/body-tangent transform and conservative variance floors fixed before new
physical validation:

- position: `(0.25 m / 3)^2` per axis;
- linear velocity: `(0.25 m/s / 3)^2` per axis;
- attitude tangent: `(10 deg / 3)^2` per axis.

The floors come from existing frozen safety screens, not from fitting a new
run.  Native variances larger than the floor are preserved.  Cross terms are
retained where the current transform supports them.  Angular-rate covariance
remains the pinned fast-propagation approximation and is not used to qualify
the PX4 external position/velocity envelope.

The profile becomes simulation-domain-qualified only after a development
cohort freezes the profile and a separately generated held-out cohort passes
all of these checks:

- every position, velocity, and attitude component stays within its 3-sigma
  envelope for at least 99% of qualified public samples;
- no component has five consecutive 3-sigma violations;
- every run completes 25 s, preserves source/native health, and passes the
  existing trajectory accuracy screens;
- all failed runs remain in the cohort and count against qualification.

This qualification is not a real-sensor, HITL, or flight covariance claim.

## Evidence and fault behavior

Fixed-input tests cover public initialization, stale visual updates, time
regression, state reversion, invalid covariance, session replacement, reset
wrap, duplicate sessions, and latched failure.  Native protocol tests cover
IMU silence, camera silence, truncated image data, processing timeout, and
process restart.  A new physical run is allowed only after these tests pass.

The first physical run with the new fields remains shadow-only and unarmed.
It must record all per-state health inputs, quality transitions, reset total,
covariance profile/version, watchdog state, ULog, process evidence, and all
failures.  ODOMETRY and EKF2 remain disabled until the held-out covariance
cohort and explicit restart/loss tests pass.

## Provenance

- OpenVINS fixed source/API and GPL-3.0 provenance are inherited from the
  sealed PR30-65 evidence chain; the upstream repository was observed as
  non-archived, with the last recorded push on 2025-11-30.  Current maintenance
  cadence remains uncertain.
- PX4 fixed source is BSD-3-Clause and remains pinned to `d6f12ad`; no current
  `main` behavior is assumed.
- MAVLink Common ODOMETRY field semantics were checked against the official
  message definition.
- OpenVINS official evaluation guidance identifies NEES and error-versus-bound
  plots as consistency evidence; it does not certify this project profile.

