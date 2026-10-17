# EKF2 capture-health evidence completion

## Problem and evidence

The existing checked teacher recorder accepts `CaptureInputEvidence` with
position and heading booleans, but it does not require PX4 horizontal/vertical
velocity validity, dead-reckoning state, filter-fault state or a fresh separate
estimator-status sample. Its stored `Observation` includes velocity. A caller
could therefore mark a synthetic position/heading valid while supplying an
invalid velocity or a stale/faulted estimator-status stream. This is a missing
input gate, not a demonstrated exploit of a real PX4 producer: no such producer
is connected yet.

Use the already pinned PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`
[VehicleLocalPosition.msg](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleLocalPosition.msg)
and [EstimatorStatus.msg](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg),
both BSD-3-Clause. The former defines `v_xy_valid`, `v_z_valid`,
`heading_good_for_control` and `dead_reckoning`; the latter defines
`filter_fault_flags` and its own timestamp. The existing `pyulog` 1.2.4
BSD-3-Clause parser, NumPy and `audit_shadow_frames`/`audit_state_sample_times`
are sufficient for a retrospective check; no new library or simulator load is
needed. Upstream maintenance and adapter resource choices were recorded in
`docs/PX4_ODOMETRY_CAUSAL_ADAPTER_REPORT.md` and
`docs/PX4_ULOG_ODOMETRY_PREFLIGHT_REPORT.md`.

## Behavior

Extend the required `CaptureInputEvidence` shape with both velocity-valid
flags, `dead_reckoning`, an integer `filter_fault_flags` and an independent
`estimator_status_sim_ns`. The checked gate requires both velocity flags true,
dead reckoning false, fault flags exactly zero, and the status sample causal
and at most the existing 100 ms estimator age at the observation. Preserve the
existing position/heading, calibration, teacher and no-Gazebo-truth checks.
Malformed types fail closed. `TeacherSequenceRecorder` must reject bad health
before appending any frame/target/reference. The legacy recorder remains as it
was; no synthetic passing input grants training or flight authority.

Use the already frozen four-run OpenVINS health cohort (`development 27201`,
held-out `27211/27212/27213`) for a **read-only retrospective diagnosis**.
Select all public VIO camera rows, align only preceding ULog position,
attitude, status and source-flag records using existing auditors, and keep
publication-only health separate from sample-time usability. Verify each
original ULog against its capture manifest; preserve every failing frame.
The post-run audit may expose a gap but may not change the frozen covariance
cohort, tune parameters against held-out seeds, reclassify source identity,
start a new physical run or authorize capture. A passing VIO covariance
cohort is not the same requirement as PX4 heading/velocity/fusion health.

## Validation and limits

Add explicit RED/GREEN tests for invalid velocity, dead reckoning, faults,
stale/future status and malformed types, including recorder no-mutation.
Run the affected recorder/capture suite and full connectome suite if resources
allow, changed-file Ruff, staged diff check, and independent review. Retain
actual ULog hashes, frame counts, refusal reasons, test failures and a sealed
report. The retrospective timestamp alignment assumes the same simulation
epoch without independent cross-process clock proof. Existing ULogs lack
`vehicle_odometry`; source authentication, calibrated camera, EGO teacher,
training, fusion, HITL and flight all remain unqualified.
