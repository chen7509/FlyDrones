# OpenVINS to PX4 disarmed receiver preflight report

Date: 2026-10-08

Branch: `codex/estimator-aware-physical-diagnosis`

Review: draft PR 65

## Decision

Task 4 prepare-only work passes. The future receiver-only study now has a
frozen endpoint, a clock/TIMESYNC contract matching the pinned PX4 filter, an
actual retained parameter baseline, a reversible transaction model, runtime
resource identities and ULog acceptance rules. This stage did not create a
network destination, send ODOMETRY, access live PX4 parameters, start
PX4/Gazebo/OpenVINS, arm, fuse EKF2 or train a policy.

Task 5 is still the first network/PX4-mutation stage and remains separately
gated.

## Upstream selection

The implementation reuses PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`
(BSD-3-Clause), pymavlink 2.4.49 and the installed MAVLink common-v2 dialect.
Exact pinned sources, repository metadata, license, interfaces, resource cost
and the adoption/rejection record are retained under
`results/openvins-ekf2-disarmed-preflight-dev-1701`. MAVROS was rejected because
ROS is absent and it would add an unqualified clock/bridge layer. uXRCE-DDS was
rejected for this study because the Agent is absent and the reviewed path is
the pinned MAVLink receiver.

## Frozen endpoint and runtime

The retained instance-eight PX4 log proves:

- target system/component `9/1`;
- Onboard PX4 UDP local port 14588 and companion port 14548;
- future companion system/component `254/191` (component 191 is a prospective
  onboard-computer choice, not historical evidence);
- model `gz_x500_benchmark`;
- PX4 binary SHA-256
  `e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb`;
- rootfs `gz_env.sh` SHA-256
  `ab02c6a75a47a56a1ca133f07248d7c42b952c4038eb29a97da062e90c796bd3`;
- startup `rcS` SHA-256
  `8f7c3edd7ab4622f42f30b281584464b325c947e21152c4fcac0cb4acba17705`;
- model SDF SHA-256
  `ff8eaa1dbb73b77d693e1d29908bc0ebee6ffa64311951e133db38fda82e7ee9`.

The preflight deliberately records `runtime_closure_qualified=false`: it binds
the selected resources needed by this study, not every kernel, host or lazy
runtime dependency.

## Clock contract

`RemoteMonotonicClock` uses the same slope-one simulation-to-remote mapping for
ODOMETRY sample time and TIMESYNC replies. Duplicate/regressed simulation time
or a process/session change requires a new clock identity; arrival time cannot
replace sample time.

`BoundedTimesyncVerifier` mirrors the pinned PX4 constants and filter update:
500 accepted samples before convergence, RTT strictly below 10 ms, 100 ms
maximum post-convergence deviation and reset on the eleventh consecutive high
deviation. These are synthetic predictions. Actual transport delivery and PX4
`timesync_status` agreement are untested until Task 5.

## Parameter and ULog contract

The accepted development ULog is 7,484,079 bytes, SHA-256
`bb84abacfecb838c1a21cec6c0dc9116a2a4a2216882ff519fb7799e87299c2c`.
Its initial parameters supply the baseline: `MAV_SYS_ID=9`,
`EKF2_EV_CTRL=0`, `EKF2_EV_NOISE_MD=0`, `EKF2_EV_QMIN=0`, zero EV delay,
equal zero EV/IMU reference triplets, `EKF2_HGT_REF=1`, GPS control 7, optical
flow/barometer/range controls 1 and magnetometer type 0. EV noise floors and
gates are also frozen.

The receiver-only prospective profile contains only `EKF2_EV_CTRL=0`, already
equal to baseline. The transaction model rejects missing or ambiguous values,
requires write acknowledgement and readback, preserves the first failure, and
still performs reverse-order restore/verification. It reports rollback failures
separately.

Future ULog acceptance requires `vehicle_visual_odometry`, `timesync_status`,
`vehicle_status`, `estimator_status`, `estimator_status_flags` and EV
position/velocity/height aid-source topics. The vehicle must remain unarmed and
all EV fusion flags must stay false. The baseline ULog does not contain the
visual-odometry/timesync/EV aid topics because no message was sent; it is only
parameter and logging provenance.

## Verification and status

- Targeted preflight/extractor tests: 21 passed.
- Changed-file Ruff: passed.
- Full repository regression: 1,967 passed, 3 skipped and two existing warnings
  in 367.81 seconds.
- One-shot preflight output is bound to committed implementation
  `ebf2680477bb1eb61d287d4a081171cc058c13b9` and refuses overwrite.
- `physical_destination_present=false`, `network_odometry=false`,
  `px4_parameter_access=false`, `ekf2_fusion=false`, `arming=false`.

|Status|Items|
|---|---|
|Verified|Pinned TIMESYNC math; retained endpoint/runtime/parameter identities; synthetic clock faults; acknowledged parameter apply/readback/restore faults; immutable prepare output.|
|Implemented only|Remote clock/TIMESYNC responder and abstract parameter transaction. They have no live transport in Task 4.|
|Not tested|UDP connection, actual 500-sample PX4 convergence, live parameter snapshot/write/rollback, `vehicle_visual_odometry`, receiver parity and EKF2 fusion.|
|External/downstream|Hardware covariance, HITL, real flight, single-aircraft closed loop, 5/20-aircraft scaling and the full fruit-fly learning comparison.|

## Sealed evidence

The curated archive is
`evidence/openvins-ekf2-disarmed-preflight-dev-1701.zip` (2,298,769 bytes,
45 members including its embedded manifest), SHA-256
`e226c8ec4239804c31c9bdde62c8ee86103994fe097c166641178728a530e8b5`.
CRC verification passed. The companion publication record is
`evidence/openvins-ekf2-disarmed-preflight-dev-1701-manifest.json`.

The archive includes the retained parameter-source ULog, runtime binding,
fixed upstream source snapshots, repository metadata, targeted and full test
logs, terminal audit, implementation/spec/plan/report files, the preliminary
pre-commit preflight and the accepted implementation-bound preflight. Its
embedded manifest records `task4_qualified=true` and
`task5_authorized=false`.
