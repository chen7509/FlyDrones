# Read-only PX4 EstimatorStatus journal design

## Purpose and dependency

The checked student-capture gate needs a fresh, independently sourced
`EstimatorStatus.filter_fault_flags`. Fixed PX4 `d6f12ad` does not publish
`/fmu/out/estimator_status` in its compiled uXRCE-DDS topic list. The
one-topic YAML candidate and exact-message ROS source overlay are source-only
preparation. The bounded status type build in
`results/px4-status-ros-type-build-dev-1701` must be audited before this
journal can claim a compiled ROS type.

Create an **independent read-only typed status journal**. It must never publish
ROS or MAVLink messages, set PX4 parameters, arm, influence EKF2, or grant
student capture. The first runnable stage is a synthetic ROS publisher and
subscriber using a newly sealed, isolated build source. Actual PX4 receipt
requires a separately compiled pinned firmware candidate and an unarmed
Agent/PX4 trial under the unchanged physical resource gate.

## Source and transport contract

- Pin PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` and
  `EstimatorStatus.msg` SHA-256
  `44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
  The derived `px4_msgs` source profile must retain that exact message; no
  installed ROS type is trusted by package name alone.
- Keep the existing odometry collector and its historical journals byte-stable.
  Add a separate executable/schema for status. Derive a new source tree from
  the frozen status overlay, explicitly list and hash every added or changed
  collector file, and reject extra build/install products before building.
- At start, verify the installed `EstimatorStatus.msg` bytes. Subscribe only
  to `/fmu/out/estimator_status` using the fixed ROS 2 Humble/rclcpp typed
  interface. Preserve the serialized CDR, its SHA-256, decoded status fields,
  RMW implementation and publisher GID, RMW sequence and timestamps when
  supported, PX4 publication/sample microseconds, callback steady time,
  sequence number, run identity and bounded terminal/fault row.
- The minimum decoded fields are `filter_fault_flags`, `control_mode_flags`,
  `solution_status_flags`, `timestamp`, `timestamp_sample`, accuracy and
  innovation test ratios, and reset counters. Retain all other fields if a
  later consumer requires them; never infer an absent field from a flag topic.
  An all-zero fault mask is an observation, not proof of estimator health.
- Accept only bounded CDR size, valid source identity shape, nonzero and
  strictly increasing PX4 sample/publication timestamps (sample no later than
  publication), increasing callback time, and nonregressing supported RMW
  sequences. Do **not** blanket-reject nonfinite innovation ratios: fixed
  EKF2 intentionally emits `NaN` for an unavailable velocity test ratio.
  Preserve its original CDR and encode such a decoded ratio as JSON `null`
  with an explicit availability indicator. A downstream health gate must
  treat an unavailable required ratio as unknown or failed, never as zero or
  a passing finite value. Check fields that must be finite by their specific
  semantics rather than by a whole-message float sweep.
  Separate unsupported RMW metadata from zero. Missing first sample,
  decode/serialization error, duplicate, rollback, discontinuity, source
  silence, changed GID, journal I/O failure and interrupted session terminate
  with an explicit failed row. Preserve the offending CDR when safely bounded.
- The journal uses exclusive creation, complete writes, bounded line count,
  terminal fsync/close handling and a fail-closed Python audit. A readable
  `complete` terminal is only a claim: the auditor reports `completed=true`
  solely when the caller also supplies a separately observed exit code zero
  from the owned writer process. `fsync` or `close` failure must produce a
  nonzero exit, and the later capture producer must bind that observed exit to
  the owned process identity. RMW timestamp zero has no supported-time proof:
  emit `null` with an explicit false availability bit rather than a numeric
  zero; a change in availability ends the session. Never repair
  or overwrite a failed run. CDR-to-decoded-field parity must be checked by
  an independent deserializer in the same binary/image, not inferred from
  the subscriber's own fields.

## Identity, time and eligibility

The synthetic loopback proves only type generation, callback parsing and
serialization parity. A publisher GID does not identify a PX4 process by
itself. The later live trial must bind the GID/session to the owned Agent,
PX4 process, DDS domain, fixed firmware binary, topic declaration and ULog.
Measure DDS writer/reader sequence gaps separately from upstream transport
loss. DDS sequence gaps alone cannot count PX4 uORB-to-uXRCE-to-Agent loss,
especially with the deliberate nominal 20 Hz rate limit. The latter needs a
correlated PX4/ULog status timestamp stream and declared rate-limit accounting.
Measure frame-relative state age from `timestamp_sample`, the fixed EKF2
delayed state time, and publication-to-sample delay from `timestamp` minus
`timestamp_sample`. Map both PX4 times through an explicitly evidenced PX4-to-
steady-clock relation and apply a predeclared age bound; a fresh publication
cannot make an old sample fresh. Arrival time alone is insufficient.
After a reset or source replacement, stop the prior session and require a new
identity/time binding. A 20 Hz source rate is only a configured nominal rate,
not a guaranteed live arrival interval.

The journal's own result always sets `live_source_authenticated=false`,
`fusion_qualified=false`, `camera_calibration_qualified=false` and
`training_eligible=false` for offline/synthetic work. A future capture gate
must combine status with odometry, VIO and safety evidence from compatible
sessions and causal timestamps. It may not use Gazebo truth as VIO.

## Validation stages and limits

1. Source-only format, exact-type, output and fault tests, including malformed
   CDR/field/time/GID/sequence cases and unchanged legacy collector behavior.
2. After the current type build is verified, derive and compile a separate
   bounded status-journal source tree. Preserve all failed builds.
3. Synthetic ROS publisher/subscriber with independent CDR decode and fault
   injection; retain binary/image/source hashes and all journals.
4. Only after pinned firmware build and resource admission, unarmed PX4/Agent
   receipt with ULog/source/process binding, both PX4 times mapped to the
   camera clock, separately qualified DDS gaps/upstream loss, and RTF
   measurement under the frozen camera/physics workload.

The fixed PX4 and official `px4_msgs` sources are BSD-3-Clause; ROS 2 Humble
`rclcpp` is Apache-2.0. The existing project reports record upstream commits,
maintenance observations and the reason to reuse rclcpp. This design adds a
small read-only executable but the separate firmware build and physical trial
remain resource-expensive and unverified. At design time the host had less
than the unchanged 4 GiB free-memory gate for that trial. No native Linux, hardware or
flight result is implied.

## Acceptance

Accept the offline stage only when exact pinned source and generated type are
verified, synthetic CDR parity and refusal tests pass, build outputs and
cleanup are sealed, and independent review finds no material omission. The
live-source and training gates remain closed until their separate evidence is
present. Retain the v6 first-TIMESYNC failure and five-camera 0.873 RTF result.
