# OpenVINS to PX4 disarmed receiver preflight design

Date: 2026-10-08

## Scope

This stage prepares the first reversible, disarmed PX4 receiver study. It does
not create a UDP endpoint, send `TIMESYNC` or `ODOMETRY`, read or write live PX4
parameters, start PX4/Gazebo/OpenVINS, or expose a physical-study destination.
Task 5 remains the first network and PX4-mutation stage and requires separate
authorization.

The input is the qualified Task 3 file-only 50 Hz stream plus retained runtime
and ULog evidence from the accepted single-aircraft simulation. The output is a
frozen endpoint/clock/parameter/ULog contract and pure synthetic fault tests.

## Fixed upstream evidence

- PX4-Autopilot commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`,
  BSD-3-Clause. The repository was non-archived and had an upstream push on
  2026-10-07. Exact `Timesync`, MAVLink receiver, EKF2 parameter and message
  sources are copied into the evidence directory; the locally built binary is
  identified separately because the checkout contains documented simulation
  changes.
- pymavlink `2.4.49` and its installed MAVLink common-v2 dialect. The package is
  reused because Tasks 1-3 already proved exact in-memory ODOMETRY encoding.
  No transport is constructed here.
- [MAVLink TIMESYNC](https://mavlink.io/en/services/timesync.html) defines the
  request/response fields and address behavior. The pinned PX4 implementation,
  rather than current-main behavior, controls the acceptance constants.
- [PX4 external-position documentation](https://docs.px4.io/main/en/ros/external_position_estimation)
  and the pinned EKF2 parameter sources define the downstream interface. The
  documentation is guidance; exact pinned source and retained runtime evidence
  decide this study.

## Frozen endpoint

Retained PX4 logs and runtime binding identify instance 8, `MAV_SYS_ID=9`,
autopilot component 1, Onboard UDP local port 14588 and companion port 14548.
The vehicle model is `gz_x500_benchmark`. The future companion identity is
explicitly selected as system 254 and `MAV_COMP_ID_ONBOARD_COMPUTER` component
191. That sender component was not present in the earlier read-only capture and
is a prospective choice, not reconstructed history.

The Task 4 endpoint record sets `network_enabled=false`. Task 5 must construct
the endpoint only after checking the exact committed preflight and proving that
no competing PX4/Gazebo/OpenVINS/training process exists.

## Clock and TIMESYNC contract

One `RemoteMonotonicClock` owns the sample clock used by both ODOMETRY and the
TIMESYNC responder. Its frozen mapping has slope one:

`remote_ns = remote_origin_ns + (sim_ns - sim_origin_ns)`

Origins and the clock-session identity are chosen once before a future run.
Repeated or regressed simulation time, a jump, or a process restart latches the
clock and requires a new identity and origins. Arrival time is recorded
separately and can never replace the ODOMETRY sample timestamp.

The pure verifier mirrors pinned PX4 `Timesync.cpp`: round trips must be below
10 ms; convergence requires 500 accepted samples; deviations above 100 ms are
rejected after convergence; the eleventh consecutive high-deviation sample
resets the filter and requires clock-session replacement. The verifier predicts
the pinned receiver state but does not prove delivery. Task 5 must compare it
with PX4 `timesync_status` and reject arrival-time fallback.

The 500-sample convergence interval occurs before the bounded receiver study
timer. No ODOMETRY candidate can leave the future sender before both the local
verifier and actual PX4 evidence show convergence.

## Parameter transaction

The retained accepted ULog supplies the baseline without live parameter access.
It identifies `MAV_SYS_ID=9`, `EKF2_EV_CTRL=0`, message variance mode,
`EKF2_EV_QMIN=0`, zero EV delay, equal zero EV/IMU lever arms, GPS height
reference, and the existing GPS/flow/barometer/range/magnetometer controls.
External-vision noise floors and gates are also included so a future fusion
study cannot change them implicitly.

Every required parameter must produce exactly one finite value. A future
transaction snapshots the complete set, applies only a predeclared profile,
requires an acknowledgement, reads each value back, runs the bounded action,
then restores and verifies the baseline in reverse write order. Missing or
ambiguous values fail before mutation. Apply and verify failures latch as the
primary error; rollback is still attempted, and rollback failures are reported
without replacing the primary error.

The receiver-only profile contains only `EKF2_EV_CTRL=0`, which already equals
the retained baseline. It does not change height reference, other aiding
sources, noise, delay, lever arms, policy, arming or setpoints. The equal zero
EV/IMU reference point is accepted only because the retained baseline proves
both triplets are zero.

## ULog acceptance contract

The future receiver-only run must retain `vehicle_visual_odometry`,
`timesync_status`, `vehicle_status`, `estimator_status`,
`estimator_status_flags`, and EV position/velocity/height aid-source topics.
The run must remain unarmed, show no EV fusion flags, preserve sample and
arrival clocks, match every uORB sample to one sent identity, and restore the
full parameter snapshot. Absence of an expected topic, a reset mismatch,
timestamp substitution, a field mismatch or incomplete rollback fails the run.

The retained baseline ULog naturally lacks `vehicle_visual_odometry`,
`timesync_status` and EV aid-source topics because Task 3 sent no ODOMETRY. It
proves parameter values and available logging only; it is not receiver evidence.

## Fault and test boundary

Synthetic tests cover 499/500-sample convergence, high RTT, time jump,
pause/regression, session replacement, missing/ambiguous parameters,
acknowledgement failure, verify failure, rollback failure and exact runtime
resource selection. Tests assert that the modules have no socket or subprocess
surface. The one-shot prepare tool refuses an existing output and produces no
physical destination.

Task 5 must separately predeclare normal and upstream-rejected duplicate,
reorder and covariance cases, run with `EKF2_EV_CTRL=0`, and restore all
parameters. This design does not authorize it.

## Status boundary

- **Verified here:** pinned clock math, 500-sample synthetic convergence,
  session-reset behavior, retained parameter baseline, runtime identities,
  rollback model and ULog acceptance schema.
- **Implemented but not live-tested:** remote-clock/TIMESYNC responder logic and
  parameter transport transaction model.
- **Not tested:** UDP endpoint, actual TIMESYNC convergence, parameter protocol,
  `vehicle_visual_odometry`, PX4 receiver parity, EKF2 innovation or fusion.
- **Still false:** network ODOMETRY, live parameter access, fusion, arming,
  hardware/HITL/flight calibration and flight readiness.
