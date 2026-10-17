# OpenVINS to PX4 EKF2 staged integration design

## Scope and decision

This design joins the already sealed OpenVINS geometry and health contracts to
the pinned PX4 external-vision ingress. It authorizes offline construction and
shadow observation only. It does not authorize a network ODOMETRY sender, PX4
parameter changes, EKF2 fusion, arming, flight, training, or multi-aircraft
execution.

Use MAVLink 2 ODOMETRY through the pinned PX4 MAVLink receiver. This reuses the
verified `pymavlink==2.4.49` serializer and the actual PX4 consumer instead of
adding a private uORB publisher. uXRCE-DDS is not selected because the current
host has no Agent or ROS installation and it would add a second transport and
timestamp contract. A direct PX4 module or simulator plugin is rejected because
it would bypass the production MAVLink ingress that this stage needs to test.

The supported set is deliberately narrow:

- OpenVINS `69488123ed9362dd44b6f28e7f4680abbff1442b`, GPL-3.0;
- PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, BSD-3-Clause;
- pymavlink `2.4.49`, LGPL-3.0, MAVLink common v2 dialect;
- identity IMU/body mounting and the frozen simulated camera calibration;
- `MAV_FRAME_LOCAL_FRD` pose and `MAV_FRAME_BODY_FRD` velocity;
- `MAV_ESTIMATOR_TYPE_VIO` and the `px4-d6f12ad-body-tangent` covariance
  convention.

PX4 and pymavlink are non-archived and had upstream activity when checked on
2026-10-07. The OpenVINS repository is non-archived, but its last observed push
was 2025-11-30, so its maintenance cadence remains uncertain. These observations
do not replace the exact commit and package pins.

## Provenance and existing evidence

The design consumes, without rewriting, these earlier results:

- the offline coordinate, covariance, clock and MAVLink round-trip contract in
  `2026-10-06-openvins-odometry-contract-design.md`;
- the fail-closed quality, reset and simulation-domain covariance contract in
  `2026-10-07-openvins-health-contract-design.md`;
- the runtime binding and process ownership evidence in PR65;
- the 25 s health cohort and fault runs summarized in
  `OPENVINS_HEALTH_CONTRACT_REPORT.md`.

The current components are not yet safe to compose directly. The old
`ShadowSession` accepts caller supplied quality values through 100 and always
labels covariance uncalibrated. The newer health contract owns the authoritative
`-1/0/1` quality, reset total, bounded 15x15 covariance and simulation-domain
qualification. The integration adapter must consume the health result; it must
not accept an independent quality or reset argument.

The pinned PX4 receiver converts ODOMETRY to `vehicle_visual_odometry`, sets
`timestamp_sample` with `MavlinkTimesync::sync_stamp`, stamps arrival separately
with `hrt_absolute_time`, and publishes only supported estimator types. EKF2 then
applies its parameter noise lower bounds, preserves `reset_counter` and `quality`,
uses 200 ms as its maximum continuity/start interval, and stops active external
vision fusion after twice that interval, about 400 ms. Before MAVLink time
synchronization converges, `sync_stamp` substitutes arrival time. That fallback
is useful for transport but cannot count as verified measurement time.

## Geometry and covariance

OpenVINS exposes the 16-value nominal IMU state
`(q_GtoI_xyzw, p_IinG, v_IinG, b_g, b_a)` and the corresponding 15-dimensional
error covariance ordered `(theta_I, p_G, v_G, b_g, b_a)`. Let
`S = diag(1,-1,-1)`, `R_GI` be the OpenVINS JPL global-to-IMU rotation and
`[a]x b = a cross b`.

The fixed message transform is:

```text
p_LOCAL_FRD = S p_IinG
R_BODY_to_LOCAL_FRD = S R_GI^T
v_BODY_FRD = R_GI v_IinG
q_wxyz = Hamilton(R_BODY_to_LOCAL_FRD)
```

Quaternion sign is canonicalized exactly as in the sealed odometry contract;
the arbitrary local heading is not North. For the output error ordered
`(p_LOCAL_FRD, theta_BODY_FRD, v_BODY_FRD)`, use the 9x15 first-order Jacobian:

```text
J[p, p_G]       = S
J[theta,theta]  = I
J[v, theta]     = [v_BODY_FRD]x
J[v, v_G]       = R_GI
all other blocks = 0
P_out = J P_imu15_bounded J^T
```

The velocity/orientation coupling is required because the new 15x15 covariance
stores velocity in the global frame. It differs from the sealed fast-propagation
12x12 contract, whose velocity was already expressed in the IMU frame. Analytic
and finite-difference tests must establish the sign of the skew block before any
packet is accepted.

PX4 d6f12ad reads only the position, body-tangent orientation and linear velocity
variance diagonals from the MAVLink upper triangles. The adapter preserves the
complete transformed 9x9 matrix in evidence and records the off-diagonal terms
discarded by PX4. Angular-rate covariance is separate from the 15x15 IMU state;
it may be included only from the pinned fast-propagation evidence and remains
explicitly unqualified. It must never be synthesized from a zero or arbitrary
constant. This consumer-specific mapping must be revalidated if PX4, the frame
profile, or the mounting changes.

## Rate, timestamps and session identity

Each message represents a new estimator sample. Repeating a camera state to
reach a higher rate is prohibited. The current publicly healthy states are at
the 10 Hz camera rate. That is suitable for an offline contract and a disarmed
receiver-only probe, but PX4 documentation recommends 30-50 Hz when covariance
is present. A fusion-enabled stage therefore requires a distinct 30-50 Hz
producer based on native IMU propagation, with a strictly increasing sample
timestamp and covariance qualified at those propagated targets. The existing
camera-cohort qualification cannot silently qualify the old 12x12 fast
covariance.

`time_usec` is the OpenVINS sample time transformed into one explicit remote
monotonic MAVLink clock domain. The ODOMETRY sender and TIMESYNC responder must
use that same clock. Under lockstep SITL, host wall time is not interchangeable
with Gazebo/PX4 simulation time: the study records and freezes the sim-to-remote
clock transform and starts a new clock session after any pause, jump or process
restart. Arrival time is recorded separately and never placed in the sample
field. A network stage must implement the MAVLink TIMESYNC microservice, budget
the pinned 500 accepted samples needed for convergence before the bounded study
window starts, and wait for convergence. Acceptance requires that the received
`vehicle_visual_odometry.timestamp_sample` matches the declared clock transform
within a frozen tolerance and that arrival minus sample stays inside the
declared latency budget. If PX4 falls back to arrival time, the run is retained
but fails timestamp qualification.

An estimator process identity, clock identity and publisher identity form one
session. `OpenVinsHealthContract.replace_session()` is the only allowed
replacement path. It increments the unbounded reset total once; the wire value
is `reset_total % 256`. Publisher restart without a validated estimator session
replacement is a fault, not a reset. Old-session packets, duplicate or regressed
sample times, reset rollback/jump, reordered acknowledgements and a changed
clock identity latch failure.

## Health gate and fail-closed behavior

Only a composed record satisfying every condition below may become a candidate
for a future publisher:

1. the native acknowledgement and source record have exact identity and order;
2. internal and public initialization are true;
3. state time equals sample time and the last regular visual update is no more
   than 200 ms old;
4. source, native worker, runtime binding and supervisor are healthy;
5. the 15x15 covariance is finite, symmetric and PSD, and the frozen
   `px4-d6f12ad-gate-floor-v1` profile is simulation-domain qualified;
6. the coordinate/Jacobian conversion succeeds without normalization outside
   tolerance;
7. the sample clock, reset total and publisher session are monotonic;
8. the result from the health contract is exactly `quality=1`.

Quality 0 and -1 remain in the shadow journal and are never promoted to a
network packet. On any fault after publication has started, the supervisor
latches, stops publication, blocks subsequent setpoints and retains the failed
run. It does not keep sending stale poses or claim rollback of already delivered
packets. A future PX4 integration relies on the pinned external-vision timeout
as a second layer and verifies that fusion stops. A terminal quality -1 packet
is not required and cannot substitute for cessation and timeout evidence.

## PX4 parameter and rollback profile

No parameter is changed in this design stage. A future integration trial must
capture all baseline values before writing, verify each acknowledged write,
record whether reboot is required, and restore and verify the baseline even
after failure.

The progression is:

1. **Receiver-only, disarmed:** keep `EKF2_EV_CTRL=0`; receive ODOMETRY and
   verify `vehicle_visual_odometry`, timestamps, frames, covariance diagonals,
   reset and quality without EKF2 fusion.
2. **Disarmed fusion observation:** after the receiver gate passes, use
   `EKF2_EV_CTRL` bits 0, 1 and 2 for horizontal position, vertical position and
   3D velocity. Keep yaw bit 3 off because the VIO heading is arbitrary. Use
   `EKF2_EV_NOISE_MD=0`, `EKF2_EV_QMIN=1`, and a prospectively frozen
   `EKF2_EV_DELAY`. Because the OpenVINS position is the IMU point, the profile
   snapshots `EKF2_IMU_POS_X/Y/Z` as well as `EKF2_EV_POS_X/Y/Z` and sets the EV
   point equal to the IMU reference point. Both may be zero only after the
   baseline proves that equality. Height reference and all other aiding sources
   remain explicit in the profile rather than being silently changed.
3. **Single-aircraft closed loop:** only after sustained disarmed fusion passes,
   use PX4 state for the existing safety-supervised velocity/yaw target loop.
   The policy still cannot write attitude or actuator commands or bypass PX4.

The delay is measured on development data from sample, wire send, PX4 arrival
and ULog timestamps. It is frozen before held-out evaluation. It is not tuned on
the sealed test set.

## Fault matrix

Every injected fault keeps its full journal, ULog and supervisor evidence.

| Fault | Local adapter response | Required PX4 observation |
| --- | --- | --- |
| IMU or camera loss | Health becomes failed, publication stops | EV continuity fails after 200 ms and active aiding stops by about 400 ms; no stale fusion |
| Packet loss | Sequence gap recorded; bounded loss test continues only if health and freshness still pass | Innovation/aiding timestamps show the missing sample |
| Excess latency | Reject before send when known; reject qualification if observed after send | No sample-time substitution accepted as pass |
| Reorder or duplicate | Latch before send | No corresponding uORB update |
| Estimator restart | Explicit new session, reset total +1, quality returns to 0 until healthy | Reset counter changes once; no old-session fusion |
| Publisher restart alone | Latch as identity fault | No reset is invented |
| Invalid/indefinite covariance | Latch before serialization | No corresponding uORB update |
| Quality 0/-1 or stale visual update | Shadow only, no send | No new EV sample |
| TIMESYNC loss/reset | Stop publication and require a new clock session | No arrival-time fallback may qualify |
| Native processing timeout | Stop publication and block later setpoints | EV fusion stops within the pinned timeout |

## Evidence and acceptance gates

### Gate A: offline packet composition

- Analytic and finite-difference geometry/Jacobian tests, including nonidentity
  attitude and nonzero velocity.
- Exact health-to-message composition; callers cannot override quality, reset,
  covariance profile or session.
- pymavlink 2.4.49 pack/decode checks for every field and float32 boundary.
- Synthetic loss, delay, reorder, restart, covariance and clock faults.
- No socket creation, PX4 parameter access or simulator process.

### Gate B: no-network online shadow

- Actual single native worker and journaled sources produce would-be packets,
  but the transport is a file sink that cannot open a network endpoint.
- Exact sample, health, reset and covariance provenance is retained.
- 10 Hz camera records may validate the composition; fusion-rate qualification
  remains false until unique propagated samples meet the frozen 30-50 Hz gate.

### Gate C: disarmed SITL receiver-only injection

- Requires separate authorization after Gates A and B.
- Full runtime binding, TIMESYNC convergence and reversible parameter baseline.
- `EKF2_EV_CTRL=0`, vehicle unarmed, no controller/policy commands.
- Verify received uORB fields and ULog identity; truth is used only by the
  offline scorer.
- Duplicate, reorder and invalid-covariance fault candidates are injected before
  the local adapter and must therefore produce no packet and no uORB update. The
  pinned receiver itself does not enforce those adapter invariants. Any separate
  malformed-wire study must expect, retain and document the receiver's actual
  publication behavior rather than claim that PX4 rejected it.

### Gate D: disarmed EKF2 fusion observation

- Requires separate authorization and a frozen development profile.
- Verify `estimator_aid_src_ev_pos`, `estimator_aid_src_ev_vel`,
  `estimator_aid_src_ev_hgt`, `estimator_status`, `estimator_status_flags`,
  `vehicle_local_position`, `vehicle_attitude` and `timesync_status`.
- Required evidence includes finite innovations and variances, test ratios at or
  below the frozen gates, `fused=true` at the expected samples, EV control flags,
  zero EKF fault flags, reset behavior, bounded tracking error, no arming,
  continuity loss after the 200 ms interval and active fusion stop by the pinned
  roughly 400 ms timeout.

### Gate E: single-aircraft closed loop

- Requires Gate D under normal and fault cases, restored parameters, and a new
  explicit authorization.
- The VIO/EKF2 state becomes the state input to the safety supervisor; the
  autonomous policy still emits only bounded velocity and yaw targets.
- Collision, tracking, command latency, ULog and recovery criteria are frozen
  before held-out runs.

Five- and twenty-aircraft execution remain downstream of Gate E and the existing
five-camera capacity failure. Hardware covariance, HITL and real flight remain
external requirements.

## Current status after this design

- **Verified:** pinned offline frame/packet contract; fail-closed health and
  reset contract; simulation-domain camera covariance cohort; fixed pymavlink
  round trips; source-loss and process-restart shutdown evidence.
- **Designed only:** health-to-packet composition, 15x15 Jacobian, TIMESYNC
  qualification, reversible PX4 parameter profile, uORB/ULog acceptance and the
  staged injection gates.
- **Not tested:** 30-50 Hz propagated covariance qualification, live MAVLink
  receive path, disarmed EKF2 fusion, loss timeout inside EKF2, closed-loop PX4
  control, HITL and flight.
- **Still failed/open:** old drift and startup failures remain preserved; the
  five-camera WSL2 result remains 0.873 RTF against the 0.95 gate; the raw IMU
  model has no hardware calibration.
