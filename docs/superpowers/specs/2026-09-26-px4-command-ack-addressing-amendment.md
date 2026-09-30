# PX4 COMMAND_ACK Addressing Amendment

Date: 2026-09-26

Amends: `2026-09-26-px4-takeoff-actuator-readiness-design.md`

## Triggering evidence

The first D3D12 single-vehicle development run,
`takeoff-dev-single-d3d12-20260926-1`, failed before mission entry. PX4's
ULog records an accepted arm command (`MAV_CMD_COMPONENT_ARM_DISARM`, result
`MAV_RESULT_ACCEPTED`) and the subsequent heartbeat reports `armed=true`, but
the worker timed out waiting for the arm acknowledgement. Policy and planner
call counts remained zero, landing was confirmed, and owned resources were
released.

The failure is caused by treating the `COMMAND_ACK.target_system` and
`target_component` payload fields as the identity of the vehicle that emitted
the acknowledgement. MAVLink defines those fields as the recipient of the
acknowledgement: the system and component that sent the original command. The
vehicle identity is carried by the MAVLink message header.

References:

- <https://mavlink.io/en/messages/common.html#COMMAND_ACK>
- <https://docs.px4.io/main/en/msg_docs/VehicleCommandAck>

## Corrected evidence contract

`CommandAckEvidence` records both address directions:

- `source_system` and `source_component`: the PX4 sender from the MAVLink
  message header;
- `target_system` and `target_component`: the local command sender named in
  the `COMMAND_ACK` payload.

An acknowledgement matches a pending command only when all of these hold:

1. the command ID matches;
2. the header source system matches the connected PX4 target system;
3. when discovery selects a specific PX4 target component, the header source
   component is broadcast/unknown or matches it; a discovered target component
   of `0` is a wildcard and accepts the responding PX4 component;
4. the payload target system is absent/broadcast (`0`) or matches the local
   MAVLink source system;
5. the payload target component is absent/broadcast (`0`) or matches the local
   MAVLink source component.

Payload target fields absent from a MAVLink 1 frame are recorded as zero and
accepted only through the explicit absent/broadcast rule. A wrong vehicle
source or a nonzero wrong local recipient remains unmatched and cannot satisfy
the transaction.

## Scope and validation

The correction changes only ACK address extraction, matching, and serialized
evidence. It does not change takeoff thresholds, retry rules, policy weights,
planner behavior, PX4 parameters, Gazebo models, sensors, or mission geometry.

Regression tests must cover a PX4 system `1` ACK addressed to local system
`255`, a wrong PX4 header source, a wrong local recipient, missing MAVLink 2
target extensions, `IN_PROGRESS` followed by a final result, and unchanged
interleaved telemetry ingestion. After the focused and full automated suites
pass, all frozen hashes are refreshed once. Live validation restarts with new
development IDs; the failed run remains immutable.

## Live follow-up: ULog motor layout and landing confirmation

The third D3D12 single-vehicle development run,
`takeoff-dev-single-d3d12-20260926-3`, completed the intended physical flight:
PX4 accepted arm, takeoff, and offboard commands; Gazebo and ULog both record
the climb; the worker exited successfully; and policy and planner call counts
remained zero. The offline evidence gate nevertheless rejected the run for two
valid reasons that expose defects in the evidence and shutdown path.

First, real `pyulog` data presents actuator motor outputs as flattened fields
named `control[0]` through `control[11]`, while the extractor only recognized
the matrix-shaped `control` field used by its test fixture. Unused flattened
channels also contain `NaN`. The extractor must support both representations,
discard non-finite samples, and compute actuator evidence from every remaining
finite control value.

Second, the worker considered altitude below 0.15 metres sufficient evidence
of landing and then stopped PX4. The ULog therefore ended while
`vehicle_land_detected.landed` was still false. The PX4 landing path must send
LAND, keep ingesting telemetry until both low altitude and `landed=true` are
observed, issue an ordinary disarm, and then wait until `armed=false`. A
landing-confirmation or disarm-confirmation timeout is an explicit worker
failure and may not be converted into an accepted trial.

Regression tests cover flattened actuator fields, non-finite unused channels,
delayed landed state, disarm only after confirmed landing, and landing and
disarm timeouts. This follow-up changes no policy weights, planner behavior,
mission thresholds, PX4 parameters, Gazebo models, sensors, or geometry. After
the focused and full automated suites pass, frozen hashes are refreshed and
live validation restarts under a new immutable development ID.
