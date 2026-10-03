# Frozen OpenVINS track geometry audit

## Purpose and boundary

The textured development replay initialized OpenVINS but all 183 candidates
with at least two clone observations failed linear triangulation or refinement.
Find out whether the captured image tracks have plausible static-scene geometry
under an **independent PX4 EKF2 pose reference**. This is a diagnostic of the
VIO input, not an alternative estimator or a flight-ready localization result.

Use only the preserved development-world `1701` RGB, PX4 ULog, and OpenVINS
config from the preceding stages. Keep the pinned OpenVINS commit, input order,
calibration, feature thresholds, and runner fixed. Do not touch sealed evaluation
worlds or feed PX4 pose, Gazebo truth, or triangulated points into OpenVINS.

## Method

In a separate GPL-3.0 OpenVINS checkout, add logging-only output for normalized
camera measurements of candidates **after clone-time cleaning**. Replay the
same input and require the state CSV to have the same SHA-256 as the original
run. Archive the patch, binary hash, exact input/config hashes, raw trace and
failures. Report candidate attempts, not distinct physical landmarks.

Read `vehicle_attitude` and `vehicle_local_position` from the same PX4 ULog.
PX4 defines attitude quaternion as FRD body to NED earth; local position is
NED with validity and reset counters. Use `timestamp_sample`; interpolate
position and orientation only inside valid, monotonic, closely bracketed
intervals. Reject estimates around resets, invalid flags, large timing gaps,
or nonfinite values. Apply the already checked development camera-to-IMU
rotation and translation without fitting it to these tracks. PX4 EKF2 pose is
only an offline reference and may itself have GNSS and other errors.

For each exported candidate, intersect its observations with valid PX4 pose.
Triangulate normalized bearings in a shared NED coordinate frame using the
fixed metric pose and assess condition number, positive camera depth, baseline,
and reprojection residual. Preserve each attempt and rejection reason, even if
the same feature ID occurs again. Compare aggregates to OpenVINS's 183 cleaned
attempts. A reference-positive result would narrow suspicion to the VIO
propagated geometry/calibration; a reference-negative result would implicate
track quality, insufficient parallax, or the provisional camera/IMU transform.
Neither result alone identifies a unique root cause or passes VIO.

## Gates

1. Synthetic geometry tests exercise a valid static point, a wrong
   correspondence, and invalid/ambiguous pose interpolation before tooling is
   used on the real episode.
2. Diagnostic replay must produce identical state CSV; trace count must equal
   the 183 post-clean candidates without silently dropping attempts.
3. Pose validity and reset checks must pass for every scored track observation;
   otherwise report coverage and leave affected attempts unscored.
4. Archive source/version hashes, raw trace, per-attempt metrics, aggregate
   report, and all failures. Distinguish PX4 EKF2-derived reference geometry
   from Gazebo truth, VIO, HITL and real flight.

References: [PX4 attitude](https://docs.px4.io/main/en/msg_docs/VehicleAttitude),
[PX4 local position](https://docs.px4.io/main/en/msg_docs/VehicleLocalPosition),
[OpenVINS camera calibration](https://docs.openvins.com/gs-tutorial.html).
