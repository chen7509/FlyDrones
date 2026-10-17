# PX4 VehicleOdometry ROS journal / ULog cross-check design

## Purpose and boundary

The fixed ROS 2 source journal retains a complete `VehicleOdometry` projection,
and the PX4 ULog preflight can detect an instance-zero topic. Neither currently
compares the same timestamped PX4 message in both records. Add a read-only
cross-check on these existing interfaces, with no simulator, network publisher
or training side effect. A matching pair is a prerequisite for a future owned
source study, not proof that an Agent/DDS publisher was the intended PX4
process. The audit must never authorize live capture, EKF2 injection, training
or flight.

## Fixed source contract

Use PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`'s
[`VehicleOdometry.msg`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleOdometry.msg)
(BSD-3-Clause) and the repository's pinned `px4_msgs` blob
`cf117ff82cdbf191bf576db91db900b7ce34f6a7`. The message uses microsecond
publication and sample timestamps, NED pose/velocity frame 1, FRD body angular
rate, Hamilton quaternion, float32 arrays, reset counter and unused quality 0.
The source journal writes float arrays with C++ `max_digits10`, sufficient to
round-trip a finite float32. The installed WSL parser is `pyulog` 1.2.4
(BSD-3-Clause); its `data_list` contains named/multi-instance columns. This
stage reuses that parser interface but installs nothing and does not assume
that a Python mapping supplied by a test has real ULog provenance. Upstream
maintenance observations and the logger's changed-load cost remain in
`docs/PX4_ULOG_ODOMETRY_PREFLIGHT_REPORT.md`.

## Interface and acceptance

Add a focused pure comparator accepting the tuple returned by
`read_offline_odometry_geometry(path)` and the `pyulog.ULog.data_list` shape.
First require the existing `audit_topic` schema to find exactly one
instance-zero `vehicle_odometry` with valid columns and monotonic timestamps.
Require at least two journal rows, one journal digest/run/GID, contiguous
sequence numbers, monotonic publication/sample times and a stable reset
counter. For each journal row, join a unique ULog row by the exact
`(timestamp_sample, timestamp)` microsecond pair. Require every journal row
to be present; extra ULog rows are reported, not silently interpreted as
DDS continuity. Compare pose/velocity frame, reset and quality exactly, then
each of the seven arrays componentwise by finite float32 bits. Reject missing,
duplicate, ambiguous, malformed or mismatched values. A successful result
reports counts and `matching_samples_only=true`; it always reports
`source_authenticated=false`, `capture_eligible=false` and
`training_eligible=false`. No fallback to local-position/attitude approximation
is allowed when `vehicle_odometry` is absent.

The comparator consumes already decoded records. It cannot itself verify raw
ULog framing, logger dropouts, complete capture duration, CDR deserialization,
Agent/process ownership, clock epoch against the camera, EKF2 health or camera
calibration. Those are independent gates in the later same-episode producer.
The two historical 25-second ULogs have no `vehicle_odometry` and must remain
explicit refusals; no old result is reclassified. The diagnostic logger
changes load, so future physical work requires its own frozen study and the
unchanged resource/safety limits.

## Verification

Use synthetic pyulog-shaped columns and synthetic v2 journal geometry for
matched values, missing topic, missing sample, duplicate/ambiguous topic,
timestamp changes, reset/quality/coordinate changes, one-component float32
changes and nonfinite values. Preserve an attempted actual-old-ULog refusal
as negative evidence if the installed WSL parser is available. Focused and
adjacent tests, changed-file Ruff, diff check and independent review must
finish before reporting the stage. The tests do not substitute for a real
same-episode PX4/Agent/ROS run.
