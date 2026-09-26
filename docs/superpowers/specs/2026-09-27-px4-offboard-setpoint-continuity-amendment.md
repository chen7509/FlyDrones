# PX4 OFFBOARD Setpoint Continuity Amendment

Date: 2026-09-27

Amends:

- `2026-09-26-px4-takeoff-actuator-readiness-design.md`
- `2026-09-27-px4-command-ack-backlog-amendment.md`

## Triggering evidence

The frozen campaign `takeoff-stability-d3d12-20260927-1` passed seven complete
five-vehicle cold starts (35/35 vehicles) and then stopped at trial
`takeoff-stability-08`. Vehicle 2 accepted arm, takeoff, and OFFBOARD commands,
produced actuator output, climbed in Gazebo truth and the PX4 estimator, and
landed and disarmed cleanly. Its worker nevertheless timed out waiting to
observe the OFFBOARD navigation state.

The ULog resolves the ambiguity. `vehicle_control_mode.flag_control_offboard_enabled`
changed to 1 at 81.652 seconds and back to 0 at 82.636 seconds. The vehicle
therefore entered OFFBOARD for about 0.98 simulated seconds, then lost it
before the worker observed and accepted the state. The current implementation
stops publishing velocity setpoints while waiting for the mode ACK and again
while polling the navigation state. PX4 requires the OFFBOARD input stream to
continue throughout those transaction windows.

## Corrected continuity contract

1. `_wait_command_ack` accepts an optional bounded keepalive callback. The
   OFFBOARD transaction uses it to publish the same zero-velocity and zero-yaw
   hold setpoint while waiting for the ACK.
2. After an accepted ACK, every OFFBOARD state-poll iteration publishes the
   same hold setpoint until the state is confirmed or the existing deadline
   expires.
3. The worker still requires both an accepted ACK and an observed OFFBOARD
   state. A transient state that is never observed does not pass.
4. ACK and state deadlines remain three seconds. Timeout paths still request
   LAND and require confirmed landed and disarmed state.

This is protocol maintenance for the PX4 OFFBOARD contract. It does not change
policy weights, planner behavior, mission thresholds, PX4 parameters, Gazebo
models, sensors, dynamics, or geometry.

## Validation and restart

Tests must prove that setpoints continue during an interleaved ACK wait and a
delayed OFFBOARD-state confirmation, while explicit ACK rejection and state
timeout remain fail-closed. After focused and complete gates pass, refresh the
affected frozen hashes and restart all development scenarios with new IDs.
Only then may a new ten-cycle stability campaign start from trial 1; the
seven-pass-plus-one-failure campaign remains immutable and cannot be resumed or
spliced.
