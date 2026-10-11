# PX4 estimator-status transport prerequisite

## Purpose and fixed evidence

The checked student-capture gate requires a separate, fresh PX4
`EstimatorStatus.filter_fault_flags` value. The pinned PX4
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4` uXRCE-DDS source publishes
`/fmu/out/vehicle_local_position`, `/fmu/out/vehicle_attitude`,
`/fmu/out/vehicle_odometry` and `/fmu/out/estimator_status_flags`, but omits
`/fmu/out/estimator_status`. The flag topic is not a substitute for the
`filter_fault_flags` field. The pinned PX4 source file SHA-256 is
`7e9c730d45b22af92acfebbb81cb5de4e4a69ac0ca46b012b71ed8fa5c89cbc0`;
`EstimatorStatus.msg` SHA-256 is
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
The earlier `upstream-px4_msgs` snapshot has different `EstimatorStatus.msg`
bytes (SHA-256
`acb1ef1f13d82763e3982d5a649af3a772b59662ad3a7f1a011330c17368a822`):
it adds a `GPS_CHECK_FAIL_JAMMED` constant. Its wire fields otherwise appear
in order, but it must not be called a matched ROS interface. An exact copy of
the pinned message in a separately built ROS workspace is a future
prerequisite, not an action of this stage.

The [PX4 uXRCE-DDS documentation](https://docs.px4.io/v1.15/en/middleware/uxrce_dds)
states that `dds_topics.yaml` selects which uORB messages are compiled into
the client and that ROS `px4_msgs` definitions must match the firmware. The
fixed [upstream topic list](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/dds_topics.yaml)
and [message definition](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg)
are authoritative for this candidate. PX4 is BSD-3-Clause, its repository is
maintained, and the pinned local checkout is clean for these files. Existing
PyYAML is declared in `pyproject.toml`, so the preflight adds no dependency.

## Narrow design

Create a read-only preflight that validates the pinned source SHA, exact
publication topic/type mapping without duplicate keys or topics, the
`EstimatorStatus.msg` field and exact message bytes, and the corresponding
`px4_msgs` message bytes. It reports a missing transport prerequisite on the
current fixed config and a ROS-interface mismatch on the earlier snapshot.
A separately versioned candidate patch adds only
`/fmu/out/estimator_status` with `px4_msgs::msg::EstimatorStatus` and a
prospectively chosen 20 Hz rate limit; the current 50 Hz local-position and
10 Hz camera settings are untouched. Verify the patch against an exact
snapshot of the pinned YAML and prove all other YAML data is unchanged.

No source-only result can prove that a rebuilt PX4 binary contains the topic,
that an owned Agent/ROS collector received it, that `px4_msgs` exactly matches
the installed build, or that the 20 Hz stream satisfies a 100 ms causal age
gate under load. The preflight must therefore always leave
`firmware_compiled_verified`, `live_source_authenticated`,
`camera_calibration_qualified`, `fusion_qualified` and `training_eligible`
false. It does not modify the installed PX4 checkout or launch a simulator.

## Validation

Test the actual pinned YAML snapshot and message bytes, then mutation cases:
missing topic, duplicate mapping/key, wrong type, rate outside declared
candidate, modified base bytes, missing status field, and mismatched ROS
message. A valid candidate remains transport-source-only. Run targeted and
affected regression, changed Ruff and diff checks, independent review, and
seal the original snapshot, candidate, mutation results and report. Preserve
all failures. A later resource-qualified build and unarmed runtime must
measure actual publication, identity, causal age, lost messages and PX4 CPU/
RTF impact before a live capture producer can consume this field.
