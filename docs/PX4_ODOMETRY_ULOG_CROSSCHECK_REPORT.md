# PX4 odometry ROS journal / ULog cross-check

This stage adds a read-only comparison between a v2 ROS 2 `VehicleOdometry`
journal projection and the **same named** PX4 ULog topic. It does not capture a
new source, launch PX4/Gazebo, or authorize training. The comparator reports
`matching_samples_only` for matching synthetic records while permanently
returning `source_authenticated=false`, `capture_eligible=false`, and
`training_eligible=false`. The full connection-group regression passed **560
tests, with 2 skips and 2 existing PyTorch warnings**. Changed-file Ruff and
staged diff checks passed.

The contract follows PX4
[`VehicleOdometry.msg` at `d6f12ad`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleOdometry.msg)
(BSD-3-Clause), the pinned `px4_msgs` blob
`cf117ff82cdbf191bf576db91db900b7ce34f6a7`, and the existing
[`pyulog` 1.2.4](https://github.com/PX4/pyulog/tree/v1.2.4) dataset interface
(BSD-3-Clause). The preceding
`docs/PX4_ULOG_ODOMETRY_PREFLIGHT_REPORT.md` records upstream maintenance and
the extra logger load. This implementation reuses those interfaces and NumPy;
it adds no dependency or physical load. A future same-episode logger study
must freeze the complete PX4 topic selection and account for its load.

The comparator requires one instance-zero ULog `vehicle_odometry` dataset,
valid schema and timestamps, and at least two ordered journal rows from one
declared run/GID/RMW identity and stable reset epoch. It joins each journal
row by its exact `(timestamp_sample, timestamp)` pair, compares frame/reset/
quality scalars exactly, then all seven finite float arrays by float32 bits.
Extra ULog samples are reported, not interpreted as continuity proof. It
rejects absent/ambiguous topics, missing samples, malformed identity, changed
reset, nonfinite values, and a one-ULP field change. The journal CDR digest is
shape-checked on every row, but this module does not compare raw CDR bytes.

| Evidence | Result | Limit |
| --- | --- | --- |
| Synthetic pyulog-shaped datasets and v2 journal | 22 focused tests pass, including seven array changes and malformed identity refusals | No actual PX4/Agent/ROS source |
| Historical `study-v23/capture-v1` ULog, SHA-256 `2877d4d872eb187598f1b5e8312dc97757214650423754aaec6fd8e2cd435008` | Installed WSL `pyulog` 1.2.4 CLI exits 1, reason `vehicle_odometry_not_logged`, 0 samples, 84 topics | Cannot perform same-message cross-check on this old run |

The actual-old-ULog refusal is in
`results/px4-odometry-ulog-crosscheck-dev-1701/historical-ulog-refusal.json`.
The second historical ULog refusal remains in the preceding preflight report.
No local-position/attitude approximation was substituted. The old physical
VIO successes, first PX4 TIMESYNC failure and five-camera 0.873 RTF result
are unchanged.

TDD first reproduced the missing comparator, then two more malformed-input
failures: a later journal row with no CDR digest incorrectly passed, and
NumPy-valued RMW identity raised an uncaught ambiguity exception. Both are
now structured refusals. Independent review found no Critical or Important
issue; its Minor RMW finding is covered by the latter regression. A mistyped
adjacent test path and an incorrect test timestamp fixture failed locally,
were corrected and did not affect production evidence. The actual ULog is
negative evidence only. The full test output and review/failure record are
retained in the stage evidence archive.
The first archive preflight stopped before archive creation because the
successful diff check produced an empty stream and `Tee-Object` did not create
its output file. An explicit empty file now records that successful check;
the failed preflight is retained in the review/failure record.

**Next gate:** a fresh, prospectively frozen, same-episode owned PX4/Agent/ROS
journal and PX4 ULog with actual `vehicle_odometry` samples, complete source
and clock/session ownership, calibrated camera evidence, EKF2/ULog health and
unchanged safety/resource gates. Even exact matching samples alone cannot
identify the originating PX4 process or authorize fusion, training, hardware
or flight. Current free memory is below the established 4 GiB physical probe
gate, so no new physical run was started in this stage.
