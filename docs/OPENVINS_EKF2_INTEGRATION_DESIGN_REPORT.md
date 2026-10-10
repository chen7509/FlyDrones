# OpenVINS to EKF2 integration design report

## Outcome

The VIO-to-EKF2 route is now specified as a five-gate progression: offline
composition, no-network online shadow, disarmed PX4 receiver injection, disarmed
EKF2 fusion observation, and single-aircraft closed loop. This stage performed
only source review, design and offline regression checks. It did not publish
ODOMETRY, change PX4 parameters, run physics, arm, train or expand the swarm.

The selected route is MAVLink 2 ODOMETRY through the pinned PX4 receiver. It
reuses pymavlink 2.4.49 and exercises the production consumer. uXRCE-DDS remains
unselected because its Agent/ROS dependencies are absent on this host. Direct
uORB or simulator injection remains rejected because it would bypass the
receiver under test.

## Material findings

1. The current health and odometry components cannot be joined by simply calling
   both. The historical odometry recorder accepts caller-provided quality through
   100, while the current health contract is authoritative for `-1/0/1`, reset,
   covariance profile and session. The new adapter must remove that second
   authority.
2. The new 15x15 OpenVINS covariance stores global velocity. Transforming it to
   BODY_FRD requires a velocity/orientation cross Jacobian, not the identity
   velocity block used by the earlier 12x12 fast contract.
3. PX4 replaces remote sample time with arrival time until MAVLink TIMESYNC has
   converged. A future passing run must use one monotonic remote clock for
   ODOMETRY and TIMESYNC, freeze the lockstep simulation-to-remote transform,
   budget the pinned 500-sample convergence window, and compare sender sample,
   receiver sample and arrival clocks.
4. The qualified public OpenVINS output is currently at the 10 Hz camera rate.
   This is enough for offline and receiver-only observation, but PX4 recommends
   30-50 Hz when covariance is supplied. Fusion therefore remains blocked until
   unique propagated samples and their covariance are separately qualified. Old
   frames cannot be repeated to meet the rate.
5. The first network study must keep `EKF2_EV_CTRL=0`. Only after exact field and
   timestamp parity may a separate disarmed study enable position, height and
   velocity fusion. Yaw remains disabled because the VIO frame has arbitrary
   heading.
6. Pinned EKF2 corrects vision observations by the difference between the EV and
   IMU reference positions. A future profile must bind both `EKF2_EV_POS_*` and
   `EKF2_IMU_POS_*`; zero is valid only when both baselines prove it.
7. The pinned receiver publishes supported ODOMETRY estimator types without
   enforcing the adapter's duplicate, time-order or PSD checks. Those faults are
   blocked before transmission; a malformed-wire diagnostic would record actual
   receiver behavior instead of expecting rejection.

## Upstream and resource record

| Component | Pin/license | Maintenance observation | Interface and cost | Decision |
| --- | --- | --- | --- | --- |
| PX4-Autopilot | `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, BSD-3-Clause | Non-archived; upstream push observed 2026-10-07. Local checkout contains previously documented simulation/VehicleIMU modifications, so only exact pinned files and runtime hashes are authoritative. | MAVLink receiver to `vehicle_visual_odometry`, EKF2 external vision, ULog. Existing SITL resource cost; no new dependency. | Adopt pinned consumer. |
| pymavlink | `2.4.49`, LGPL-3.0 | Non-archived repository; release published 2025-08-01 and later releases exist. | In-memory common-v2 pack/decode already validated. Network use remains future work. | Adopt exact installed release. |
| OpenVINS | `69488123ed9362dd44b6f28e7f4680abbff1442b`, GPL-3.0 | Non-archived; last observed upstream push 2025-11-30, current cadence uncertain. | Existing single native worker; 16-value IMU state and 15x15 covariance. | Adopt existing pin only. |
| MAVLink common ODOMETRY | Common message 331 | Maintained as the official MAVLink common dialect. | LOCAL_FRD/BODY_FRD, upper-triangle covariance, reset and quality. | Adopt through pymavlink. |
| uXRCE-DDS | PX4 supported alternative | Not evaluated as a runtime in this stage. | Would require Agent/ROS packages absent on this host and a separate timestamp/transport contract. | Reject for this integration. |

The design follows the pinned consumer rather than assuming current PX4 `main`
behavior. Official PX4 documentation confirms the external-vision parameter
bits, covariance/noise selection and recommended stream rate; the pinned source
defines the exact behavior used for acceptance.

## Validation performed

- Read the exact PX4 receiver, `VehicleOdometry`, EKF2 external-vision ingest and
  control, timesync, parameter and aid-source message sources at the pinned
  commit.
- Read the installed pymavlink 2.4.49 package metadata and official release
  record.
- Read the pinned OpenVINS IMU state layout and the project health/odometry
  contracts.
- Re-ran the focused offline odometry and health tests, including pymavlink
  round trips, plus changed-file formatting and diff checks.
- Reviewed the design for claim boundaries, parameter rollback, clock fallback,
  fault behavior and stage exits.

This validation does not prove the new 15x15 Jacobian implementation because it
has not been implemented yet. It also does not prove a live receiver, TIMESYNC,
EKF2 innovation behavior or parameter rollback. Those remain explicit tasks in
the execution plan.

## Status

| State | Items |
| --- | --- |
| Verified | Existing offline frame/packet contract; health/reset contract; simulation-domain camera covariance cohort; pinned source semantics; fixed pymavlink round trips. |
| Designed only | 15x15 Jacobian, composed health gate, TIMESYNC qualification, reversible PX4 profile, fault matrix, ULog/EKF2 acceptance and all later stage exits. |
| Not tested | 30-50 Hz propagated covariance, live ODOMETRY, `vehicle_visual_odometry` parity, disarmed fusion, loss timeout, closed loop, HITL and flight. |
| Failed/open | Historical VIO failures remain retained; five-camera WSL2 RTF remains 0.873 below 0.95; raw IMU hardware calibration is absent. |

The next authorized work is Task 1 of the plan: implement and test the pure
15x15 geometry/covariance transform. It still creates no network traffic and
does not change PX4.
