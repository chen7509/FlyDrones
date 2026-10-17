# OpenVINS 15x15 to PX4 Transform Report

Date: 2026-10-08

Branch: `codex/estimator-aware-physical-diagnosis`

Review: draft PR 65

## Decision

The pure OpenVINS IMU-state transform now implements the pinned geometry and
15x15 covariance equations for a future PX4 ODOMETRY candidate. Analytic and
finite-difference tests establish the JPL-to-Hamilton direction, quaternion
sign, LOCAL_FRD position, BODY_FRD global-velocity rotation, and the positive
`[v_BODY_FRD]x` attitude/velocity block. The implementation remains incapable
of serializing or sending a MAVLink message and does not grant fusion.

## Implementation

`tools/benchmark/openvins_ekf2_transform.py` consumes the 16-value OpenVINS
nominal state `(q_GtoI_xyzw, p_IinG, v_IinG, b_g, b_a)` and an already bounded
15x15 covariance ordered `(theta_I, p_G, v_G, b_g, b_a)`. It returns:

- `p_LOCAL_FRD = diag(1,-1,-1) p_IinG`;
- `R_BODY_to_LOCAL_FRD = diag(1,-1,-1) R_GI^T` as canonical Hamilton `wxyz`;
- `v_BODY_FRD = R_GI v_IinG`;
- the full 9x15 Jacobian and transformed 9x9 covariance;
- the position, body-tangent attitude, and body-velocity variance diagonals
  consumed by the pinned PX4 receiver.

All numeric inputs, transformed outputs, and covariance entries must be finite
and float32 representable. The quaternion must be unit length within the pinned
tolerance. Covariance must have the exact shape, be symmetric, and be positive
semidefinite. Bias covariance remains present in the input contract but has zero
columns in this first-order output Jacobian. Angular-rate covariance is not
synthesized.

The earlier `openvins_odometry_contract.convert_native` is unchanged. Its
12x12 fast-state covariance already stores velocity in the IMU frame; it cannot
replace this new transform because the 15x15 covariance stores global velocity
and therefore requires attitude/velocity coupling.

## Source provenance

The write-once development result contains exact source snapshots and SHA-256
identities for PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, OpenVINS
`69488123ed9362dd44b6f28e7f4680abbff1442b`, pymavlink `2.4.49`, and MAVLink
common ODOMETRY. It covers the PX4 receiver, `VehicleOdometry`, EKF2 ingest and
external-vision control, continuity constants, parameters, aid-source messages,
TIMESYNC, the OpenVINS IMU/state declarations, generated pymavlink dialect, XML
dialect, package metadata, and licenses. The 14 snapshots shared with the
earlier design evidence match its hashes exactly. The relevant pinned checkout
files were clean when copied; the broader PX4 checkout remains documented as
modified outside this exact set.

PX4 and pymavlink were non-archived with upstream activity observed on
2026-10-07 and 2026-10-06 respectively. OpenVINS was non-archived, but its last
observed push was 2025-11-30, so its maintenance cadence remains uncertain.
No new dependency was installed.

## Validation

The focused transform suite exercises five analytic orientations, including
noncommuting roll/pitch/yaw, a numerical 9x15 finite-difference Jacobian with
nonzero velocity, dense cross covariance, the old/new covariance distinction,
quaternion sign invariance, exact profile selection, malformed input, indefinite
covariance, and input/output float32 limits. The final evidence archive records
the RED failure before implementation, focused GREEN output, changed-file Ruff,
repository diff checks, source identities, and archive manifest/CRC verification.

Final verification reports 76 focused transform/odometry/health tests passing,
changed-file Ruff passing, and `git diff --check` passing. The first full-suite
invocation inherited a different editable FlyDrones installation and stopped
during collection with 69 `flydrones.benchmark` import errors; that environmental
failure is retained. With `PYTHONPATH` explicitly bound to this worktree's
`src`, the complete suite reports 1,898 passed, 3 skipped, and the same 2
existing warnings in 227.11 seconds.

The sealed archive is `evidence/openvins-ekf2-transform-dev-1701.zip`, 424,973
bytes with 35 members and SHA-256
`734f11db482a4cd96b8381068962f80d580f344a04dbf0d42bcd951cca0d2e7e`.
CRC and every member hash verify. This archive identity statement postdates the
report copy inside the archive; the archive was not rewritten afterward.

## Claim boundary and next gate

This is an offline unit/analytic result. It did not start PX4, Gazebo, OpenVINS,
or training; it did not open a socket, encode ODOMETRY, change a PX4 parameter,
arm an aircraft, or feed EKF2. Gazebo truth was not used. `fusion=false` remains
the only valid state.

The next dependency is the transport-neutral composition state machine. It must
consume the authoritative `OpenVinsHealthContract` result so callers cannot
override quality, reset, covariance profile, or estimator session. Quality 0 or
-1 and every stale/faulted condition must remain a structured refusal.
