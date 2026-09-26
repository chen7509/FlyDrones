# VIO Evidence Mission Window Amendment

Date: 2026-09-27

Amends:

- `2026-09-24-vio-degradation-stress-design.md`
- `2026-09-26-gazebo-d3d12-five-vehicle-stability-design.md`

## Triggering evidence

The frozen formal campaign `renderer-formal-20260927-1` completed all ten
five-vehicle trials and failed only its final D3D12 trial,
`renderer-pair-5-2-d3d12-nvidia`. All five vehicles reached mission-ready,
received motor commands, climbed in Gazebo and the PX4 estimator, and landed
cleanly. Vehicle 3 alone failed the external-vision and post-GNSS evidence
summaries because `vehicle_local_position.vxy_reset_counter` changed from 3
to 4.

The ULog places the reset outside the autonomous mission window:

- `EKF2_GPS_CTRL=0` was recorded at 86.916 simulated seconds.
- PX4 received `MAV_CMD_NAV_LAND` at 98.616 seconds and entered AUTO_LAND at
  98.640 seconds.
- The velocity reset occurred at 102.804 seconds while AUTO_LAND was active.
- Its logged delta was approximately `(0.00220, -0.00745)` m/s.
- Ground contact was reported at 103.524 seconds and landed state at 104.196
  seconds.

Before LAND, EV position fusion, EV position and velocity control, local
position validity, and visual-odometry continuity remained accepted, with no
inertial dead reckoning or innovation rejection. The current summarizer scans
from the post-GNSS grace boundary to the end of the ULog, so a landing-phase
velocity convergence reset is incorrectly treated as an autonomous
mission-phase estimator reset.

## Corrected evidence contract

1. External-vision health and post-GNSS operational continuity use a bounded
   mission window: from the existing start boundary through the first
   `MAV_CMD_NAV_LAND` command, excluding samples at and after that command.
2. A horizontal position or velocity reset before LAND remains a hard
   rejection. The reset threshold is not relaxed.
3. When no LAND command is present, the evidence window continues to the end
   of the log, preserving fail-closed behavior for incomplete runs.
4. The evidence summary records the mission-window end and whether it came
   from a LAND command so the exclusion is auditable.
5. Landing remains independently gated by worker landing confirmation, ULog
   landed state, actuator/Gazebo evidence, and owned-process cleanup.

This correction changes evidence phase scoping only. It does not change the
controller, policy, planner, fault profile, timing thresholds, PX4 parameters,
Gazebo model, sensors, dynamics, or geometry.

## Validation and restart

Tests must prove that a reset before LAND is rejected, a reset after LAND is
excluded from mission continuity, a missing LAND command does not hide a
late reset, and the reported end boundary is the first LAND command. After
focused and complete gates pass, refresh only the affected renderer evidence
hash and rerun a new smoke campaign followed by a complete formal campaign
from trial 1. The failed formal campaign remains immutable and cannot be
resumed or spliced.
