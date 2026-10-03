# PX4 EKF2 ULog shadow alignment on preserved development evidence

## Intent and boundary

Establish whether the saved single-aircraft textured development capture
contains a timely, healthy, non-Gazebo PX4 estimate at each camera frame.
This is a read-only **offline shadow audit**. It must not change the historical
controller's truth-derived observation, inject VIO into PX4, produce a
train/validation sequence, or upgrade the `out_of_bounds` flight result.

Choose ULog rather than adding another reader to the live pymavlink socket:
the existing benchmark has separate heartbeat/telemetry consumers, while its
saved PX4 ULog already contains high-rate `vehicle_local_position`,
`vehicle_attitude`, `estimator_status`, and sparse
`estimator_status_flags`. A live consumer and capture-time provenance remain a
later task; this audit tests the candidate source and clock assumption first.

## Fixed inputs and method

Use only `evidence/openvins-texture-dev-1701.zip` (SHA-256
`82f9377c1ad11f824064e1cbbc5feb834f77803af3ec83d00bfb0c8355072ddd`)
and its index, which pins every member. The source contains 629 RGB records
with Gazebo frame nanoseconds and one PX4 ULog (SHA-256
`5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55`).
Verify archive/index hashes, member paths, the RGB manifest, and ULog identity
before analysis. Never rewrite either source. Extract the ULog only to a
private temporary directory for `pyulog` and remove it after reading.

For each original RGB timestamp, use the latest PX4 sample **at or before**
that time; never interpolate from a later state. Require local position,
attitude, and estimator status each no more than 100 ms old. Record sparse
source flags separately with a 2 s maximum age; do not imply they have
frame-rate resolution. Require `xy_valid`, `z_valid`, `v_xy_valid`,
`v_z_valid`, and `heading_good_for_control`; reject `dead_reckoning`,
nonzero `filter_fault_flags`, nonfinite position/velocity/quaternion, or
nonmonotonic topic time. Preserve every frame's outcome and missing reason,
including frames before PX4 logging began. Position/velocity may be reported
in raw NED and converted ENU with the fixed axis map, but no camera pose is
constructed while the extrinsic remains unvalidated.

Record distinct counts for timely samples, valid health, GNSS source,
external-vision source, unclassified source, and failures; include every
per-frame source timestamp/age and the exact thresholds. The output path is
write-once. `eligible_for_live_capture` remains false regardless of offline
statistics because timestamp epoch and camera extrinsic are not calibrated
for online use and no producer is wired to `validate_capture_input()`.

## Validation and limitations

Unit tests use small synthetic topic arrays to prove no future samples,
staleness, invalid flags, missing fields, clock rollback, and all-failure
retention. A single real replay against the fixed archive runs under WSL
Ubuntu where `pyulog` is installed, and preserves its report plus source
hashes. Compare its outcome to the original PX4 ULog health summary, without
using Gazebo truth as an estimator input.

PX4's local-position and estimator-status streams are defined in the pinned
PX4 checkout `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`; both timestamp
fields come from uORB topics. See [PX4 EKF2](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf)
and [MAVLink estimator status](https://mavlink.io/en/messages/common.html#ESTIMATOR_STATUS).
