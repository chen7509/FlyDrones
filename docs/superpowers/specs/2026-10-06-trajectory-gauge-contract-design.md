# Trajectory and Gauge Contract Design

## Question

How can a future supported-motion OpenVINS run be scored when the estimator may initialize only after external lift begins, without choosing a favorable origin after seeing truth or hiding gravity/attitude error with a full-trajectory fit?

This stage is an offline contract and fixed-evidence audit. It does not run PX4, Gazebo, OpenVINS, training, ODOMETRY, arming, or EKF2.

## Source decision

Use pinned OpenVINS `69488123ed9362dd44b6f28e7f4680abbff1442b` (GPL-3.0) and the existing SciPy `Rotation` dependency. OpenVINS exposes the active IMU state as `q_GtoI, p_IinG, v_IinG, bg, ba`. Its JPL quaternion matrix is the transpose of the numerical Hamilton matrix, so the producer's `xyzw` values are interpreted by SciPy as the IMU-to-estimator-global rotation. Camera-state velocity is global; it must not be confused with the body-frame velocity in `fast_state_propagate`.

Use evo's documented origin alignment and APE/RPE definitions as evaluation references, but do not add evo as a runtime dependency. Whole-trajectory Umeyama fitting and time-shift or scale fitting are rejected here because they can hide startup drift on this short trajectory. The adapter remains small, source-auditable, and based on existing NumPy/SciPy.

The fixed PX4 odometry bridge remains a separate contract: `LOCAL_FRD` position and `BODY_FRD` velocity are wire semantics. This audit scores the native estimator-global state against an offline world reference and emits no PX4 message.

## Prospective gauge

Select the **first internally initialized state in the estimator session**, using only ordered estimator records. Truth, error values, public initialization, and later trajectory quality may not influence the selection.

If this state occurs after the immutable motion anchor, retain `[anchor, origin)` as `startup_unavailable`; do not claim accuracy for it. The first internal state must occur no later than the prospectively fixed lateral-excitation start `anchor + 3 s`. Otherwise the trajectory diagnostic is indeterminate. A later state may never replace the first state to obtain a better score.

At the selected origin, align only the unobservable global yaw and translation:

- `R_n` is native IMU-to-G from the numerical Hamilton interpretation of `q_GtoI`;
- `R_t = R_world_from_FLU * diag(1,-1,-1)` is reference BODY_FRD-to-world;
- yaw is the signed angle between the horizontal projections of the two body x axes;
- `A = Rz(yaw)`; position is `A(p-p0)+p_truth0`, velocity is `A v`, attitude is `A R_n`;
- scale is fixed at one; time shift is zero; there is no later realignment.

The initial gravity-axis error is measured after yaw alignment and therefore cannot be hidden by the gauge. Degenerate horizontal headings are refused.

## Time and lifecycle contract

Estimator `state_time_s` converts to integer nanoseconds only when within one nanosecond of an integer. An internally initialized state must have `state_time_ns == sample_ns`. Reference association is exact by integer nanoseconds; no nearest-neighbor selection or interpolation is allowed in this first contract.

State sequence, sample time, receive/start/end clocks, internal initialization, public initialization, and last regular-update time must be monotonic under their documented domains. Public initialized implies internal initialized and may not revert. `zupt_flag_latched` is recorded as a state flag, not counted as an accepted ZUPT update. `last_regular_update_s` is reported separately from internal state availability.

The estimator process/session identity is immutable. A known reset counter must remain constant; a reset makes the single-session qualification fail and is retained. Unknown reset and quality may still permit a labeled trajectory diagnostic, but they keep estimator-health and fusion qualification false. Unknown covariance calibration also keeps fusion false.

## Screens and boundaries

Development screens remain position `<=0.25 m`, global velocity `<=0.25 m/s`, relative attitude `<=10 deg`, and initial gravity-axis error `<=5 deg`. The first public state must occur by lateral start and public state must remain available with gaps `<=200 ms` through `24.9 s`. A complete run requires the original 25 s capture and all expected source/reference evidence.

Report diagnostic metrics even for a partial capture when the gauge and exact matches are valid. Separate `post_origin_trajectory_qualified` from `full_motion_trajectory_qualified`: a startup-unavailable interval always keeps the latter false, even when every post-origin gate later passes. Duration, coverage, reset/quality, covariance, or capture-health gaps keep both false. The diagnostic is not an ATE/RPE benchmark, a fusion gate, or flight evidence.

Gazebo truth is consumed only by this offline audit and the already isolated abort monitor. It must never initialize, correct, or enter the VIO input or online policy.

## Fixed-evidence projection

Consume the sealed PR48 archive `evidence/supported-online-vio-dev-1701.zip` with expected SHA-256 `07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2`. Verify every consumed member against the archive manifest before parsing it.

The projection must select the first internal state at 2.4 s without consulting truth, retain the unavailable interval from anchor 1.622 s, and keep qualification false because the capture ended at 6.42 s with unknown reset/quality and uncalibrated covariance. All rows and failures remain in the evidence; no estimator or physics rerun is allowed.

## Failure handling

Reject malformed JSON, duplicate keys, duplicate or regressed samples, nonfinite or oversized values, invalid quaternions, state/sample mismatch, missing exact truth, initialization reversion, public-before-internal, public reversion, impossible clocks, changed session identity, unsupported frame/profile, manifest/hash mismatch, and output overwrite.

An audit failure must not silently drop rows or choose a different origin. All broad claims default false.
