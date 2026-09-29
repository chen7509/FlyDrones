# Five-Camera Render Capacity Amendment 34: Wall-Clock PX4 Multi-Instance Release

## Trigger

The zero-time joint release preserved a common simulation epoch but still produced
only 13 of 20 Gazebo flight-sensor source messages. Earlier preserved trials showed
different missing IMU, barometer, magnetometer, and GPS streams while all topics
were advertised. The failure therefore occurs before camera-capacity scoring and is
not an observer timeout. Five lockstep PX4 processes sharing one Gazebo world can
form a circular wait: one PX4 instance waits for a sensor update while Gazebo waits
for every lockstep participant to advance.

PX4 revision `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` provides the official
`px4_sitl_nolockstep` board target. Its generated board configuration defines
`CONFIG_BOARD_NOLOCKSTEP 1`.

## Correction

Use the official `px4_sitl_nolockstep` build for capacity-mode trials only. Keep
`px4_sitl_default` as the launcher default for mission, VIO, and other non-capacity
runs. The capacity runner freezes and exports the build name and expected PX4
revision; the launcher rejects any other capacity build, rejects a revision
mismatch, and rejects a generated board configuration that does not prove
`CONFIG_BOARD_NOLOCKSTEP 1`.

Write `px4-build-evidence.json` before startup with the selected build name, PX4
revision, PX4 binary SHA-256, generated board-config SHA-256, and the no-lockstep
attestation. Preserve that file with every trial. Keep all camera, dynamics,
threshold, schedule, safety, and cleanup rules unchanged.

## Acceptance

- A regression proves capacity trials select `px4_sitl_nolockstep`, export the
  frozen PX4 revision, and reject any different build name.
- Structural coverage proves non-capacity launch remains on
  `px4_sitl_default`, and capacity launch requires the generated no-lockstep
  board definition.
- The build evidence is a required preserved artifact.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun from a fresh ID. The
  20-source witness, exact topology, five PX4 health gates, RTF, camera phase,
  cleanup, and all failures remain preserved and separately reported.
