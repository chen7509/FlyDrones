# PX4 COMMAND_ACK Backlog Amendment

Date: 2026-09-27

Amends:

- `2026-09-26-px4-takeoff-actuator-readiness-design.md`
- `2026-09-26-px4-command-ack-addressing-amendment.md`

## Triggering evidence

The five-vehicle D3D12 development trial
`takeoff-dev-five-d3d12-20260926-4` failed its frozen gate for vehicles 2 and
4. Both workers reported `offboard-command-rejected` because they did not
receive the expected `MAV_CMD_DO_SET_MODE` acknowledgement within the fixed
three-second transaction timeout.

The preserved evidence rules out an actual PX4 rejection. Both ULogs record
an accepted command 176 acknowledgement. Both vehicles produced actuator
output, delivered motor commands to Gazebo, climbed in Gazebo truth and the
PX4 estimator, landed, disarmed, and released owned resources. Vehicles 0, 1,
and 3 completed the same transaction. The failure is therefore in live ACK
observation under the five-vehicle telemetry load.

The OFFBOARD priming loop currently sends setpoints for 1.5 seconds without
draining incoming MAVLink traffic. `_wait_command_ack` then consumes only one
interleaved message per iteration. A command acknowledgement behind the
accumulated telemetry can remain unseen until the wall-clock deadline even
though PX4 accepted the command.

## Corrected transaction contract

The correction is limited to MAVLink receive handling and failure evidence:

1. OFFBOARD priming drains and ingests telemetry on every priming iteration,
   while continuing the unchanged setpoint frequency and duration.
2. After each blocking receive, `_wait_command_ack` drains a bounded burst of
   already queued messages non-blockingly and ingests every message before it
   evaluates the acknowledgement queue.
3. The burst has a fixed maximum so a continuously producing connection
   cannot bypass the existing wall-clock timeout.
4. A missing ACK at the deadline is classified as
   `offboard-command-timeout`. A received non-accepted ACK remains
   `offboard-command-rejected`.
5. Either failure remains fail-closed: request LAND, require confirmed landed
   and disarmed state, preserve the trial, and do not enter mission control.

The three-second ACK timeout is unchanged. Policy weights, planner behavior,
mission thresholds, PX4 parameters, Gazebo models, sensors, dynamics, and
geometry are unchanged.

## Validation and restart

Regression tests must place a valid ACK behind a large interleaved telemetry
backlog, prove that the backlog is ingested rather than discarded, prove the
drain is bounded, distinguish ACK timeout from explicit rejection, and retain
the existing wrong-source and wrong-recipient rejection tests.

After focused and complete automated gates pass, refresh every affected frozen
hash and restart all three development scenarios with new immutable IDs. The
failed five-vehicle trial remains unchanged. Only after the restarted single,
five-vehicle, and stationary-physics scenarios pass may the ten-cycle
stability gate begin.
