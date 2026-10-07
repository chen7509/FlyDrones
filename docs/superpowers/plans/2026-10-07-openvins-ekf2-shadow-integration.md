# OpenVINS to PX4 EKF2 staged integration plan

> Execute this plan inline with `superpowers:executing-plans`. Every stage has
> its own immutable evidence destination. Do not begin a later gate because an
> earlier gate merely produced output; all acceptance checks must pass.

**Goal:** Connect the qualified OpenVINS health evidence to the pinned PX4
external-vision path in auditable stages while keeping network publication,
fusion and control disabled until their respective gates are explicitly
authorized.

**Architecture:** A pure adapter composes native state, the authoritative health
result, session/clock evidence and the pinned covariance transform into an
immutable packet candidate. A file-only online shadow validates real source
timing. Later, separately authorized stages add MAVLink TIMESYNC and ODOMETRY,
first with EKF2 fusion disabled and then with disarmed fusion observation.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-ekf2-shadow-integration-design.md`

## Global constraints

- Pin OpenVINS `6948812`, PX4 `d6f12ad` and pymavlink `2.4.49`.
- Never accept quality, reset or covariance qualification from two independent
  callers. `OpenVinsHealthContract` is authoritative.
- Never repeat a state to manufacture 30-50 Hz. Each message has a unique native
  sample and covariance.
- Truth stays outside the estimator and is used only by the offline scorer.
- No network ODOMETRY, parameter mutation, EKF2 injection, arming, training or
  multi-aircraft execution in Tasks 1-3.
- Preserve all failed attempts, runtime bindings, ULogs and source identities.
- Push only to the `personal` remote on the current PR65 branch.

## Task 1: Freeze source semantics and executable math fixtures

**Files:** Add focused source snapshots and metadata under a new write-once
results destination; add tests for the design equations.

- [x] Record exact source/hash/license/maintenance evidence for PX4 receiver,
  VehicleOdometry, EKF2 external-vision ingest/control, timesync, aid-source
  messages, MAVLink common ODOMETRY, pymavlink 2.4.49 and OpenVINS IMU state.
- [x] Write RED analytic and finite-difference tests for the 9x15 Jacobian,
  including noncommuting attitude, nonzero velocity, cross covariance and the
  old-12x12/new-15x15 distinction.
- [x] Implement a pure transform that consumes the bounded 15x15 covariance and
  retains the full 9x9 output covariance plus PX4-consumed diagonals.
- [x] Verify quaternion direction/sign and float32 representability.
- [x] Run focused tests, Ruff and diff checks; seal evidence.

**Exit:** Geometry and covariance tests pass against exact pins. No serializer,
socket, PX4 process or simulator is used.

## Task 2: Compose health, clock, reset and packet evidence

**Files:** Add a transport-neutral integration contract and focused tests. Keep
the existing offline contract for historical replay compatibility.

- [x] Write RED tests proving that quality/reset/profile/session cannot be
  overridden, and that quality 0/-1, stale visual updates, source/native faults,
  time regression and invalid covariance cannot produce a packet candidate.
- [x] Implement one state machine that consumes the health result and emits
  either a candidate with quality 1 or a structured refusal.
- [x] Add explicit estimator, clock and publisher identities; validate session
  replacement, reset increment/wrap and old-session rejection.
- [x] Encode/decode in memory with pymavlink 2.4.49 and verify every field,
  upper-triangle index, frame enum and estimator type. Monkeypatch socket APIs in
  tests so any network attempt fails.
- [x] Inject loss, delay, duplicate, reorder, restart, covariance and write/close
  faults; retain every refusal.

**Exit:** Offline composition is fail closed and packet bytes round-trip without
opening a transport. `fusion_eligible` remains false.

## Task 3: No-network real-source shadow

**Files:** Extend the existing single-worker fan-out with a file-only packet
candidate sink and immutable audit.

- [x] Predeclare source, binary/config, health profile, thresholds, rate and
  output identities; bind them into the runtime snapshot.
- [x] Feed actual journaled IMU/camera/native acknowledgements through the
  integration contract once. Keep the sink incapable of constructing a socket.
- [x] Record capture, arrival, dispatch, native start/end, health, candidate and
  refusal times separately.
- [x] Run normal, source-loss, native-timeout and explicit session-replacement
  fixed-input cases. Preserve all failures.
- [x] Audit unique sample rate. If only 10 Hz camera candidates exist, mark
  receiver-shadow rate only and keep fusion-rate qualification false.
- [x] Add and validate a unique 30-50 Hz native propagation/covariance producer,
  then qualify its covariance on prospectively frozen held-out simulation runs;
  do not inherit camera-cohort qualification automatically.

**Exit:** Real source evidence produces ordered file-only candidates, fault cases
latch, and a separate propagated covariance cohort passes. No network or PX4
parameter access occurs.

## Task 4: Prepare a reversible disarmed PX4 study

**Files:** Add a spec, one-shot launcher and preflight only. Do not dispatch the
physical study in the same change.

- [x] Research and freeze the actual MAVLink endpoint, system/component IDs,
  TIMESYNC behavior, PX4 binary/rootfs, model, parameter baseline and ULog topic
  set.
- [x] Implement the pure TIMESYNC responder/filter using the same explicit remote
  monotonic clock as ODOMETRY; verify it with synthetic exchanges only.
- [ ] **Reopened after source/budget audit:** implement and verify a feasible live
  TIMESYNC startup and pre-publication convergence observer. See
  `docs/OPENVINS_TIMESYNC_STARTUP_REPORT.md`: default 10 Hz cannot satisfy the
  modeled 25-second run or 8-second readiness window, and companion replies do
  not prove PX4 acceptance. Any temporary stream-rate change requires a new
  declared transaction and rollback, not the old EV_CTRL-only preflight.
  Use the same explicit remote
  monotonic clock as ODOMETRY. Freeze the sim-to-remote transform, reset the
  clock session on pause/jump/restart, and require observed convergence before
  any ODOMETRY candidate can leave the sender. The old "before the study timer"
  warmup requirement conflicts with the unchanged total duration/readiness
  condition; resolve it explicitly in the replacement design rather than
  resetting the timer or silently adding warmup. It remains unqualified.
  Offline serial status matching is now implemented under
  `docs/OPENVINS_TIMESYNC_OBSERVER_REPORT.md`; its synthetic/native-filter
  checks do not qualify actual listener delivery or cold/channel identity.
- [x] Snapshot `EKF2_EV_CTRL`, `EKF2_EV_NOISE_MD`, `EKF2_EV_QMIN`,
  `EKF2_EV_DELAY`, `EKF2_EV_POS_X/Y/Z`, `EKF2_IMU_POS_X/Y/Z`, height reference
  and other active aiding source parameters. Refuse a missing/ambiguous value.
  Bind the EV point to the IMU reference point; use all-zero values only after
  the baseline proves both triplets are zero.
- [x] Implement acknowledged apply/verify/restore/verify transactions. Any
  failure latches and still attempts rollback without hiding the original error.
- [x] Correct the post-seal rollback gap: prevalidate the complete desired
  profile, restore all attempted writes despite lost acknowledgements, protect
  the complete apply phase against cancellation, and verify the full baseline.
  Preserve the old archive; use the replacement preflight recorded in
  `docs/OPENVINS_PARAMETER_ROLLBACK_REPORT.md` for any future launch.
- [x] Freeze `EKF2_EV_CTRL=0` for the first receiver-only run; no policy or
  setpoint source is permitted.
- [x] Predeclare ULog topics and acceptance rules for visual odometry, timesync,
  estimator status/flags and EV aid sources.

**Exit:** Pure preflight and synthetic rollback checks have passed. Full launch
readiness is reopened pending the live timing/observation requirements above;
physical destination is still absent. Obtain separate authorization for Task 5
after the corrected preflight is concrete and reviewed.

## Task 5: Disarmed receiver-only SITL injection

**Authorization required:** This is the first network ODOMETRY and PX4 parameter
stage.

Offline preparation only: `tools/benchmark/audit_openvins_receiver_parity.py`
compares retained bytes and ULog under the contract in
`docs/OPENVINS_RECEIVER_PARITY_REPORT.md`. A component field match does not
complete any physical Task 5 checkbox or qualify clock convergence/fusion.

- [ ] Confirm all training/PX4/Gazebo/OpenVINS resources are idle and the exact
  committed preflight head is checked out.
- [ ] Run one bounded study with the vehicle unarmed and `EKF2_EV_CTRL=0`.
- [ ] Verify TIMESYNC convergence; compare sender sample, send, receiver sample
  and receiver arrival clocks. Arrival-time fallback fails qualification.
- [ ] Verify `vehicle_visual_odometry` frames, quaternion, covariance diagonals,
  reset and quality against the sent packet identities.
- [ ] Inject duplicate/reorder/bad-covariance candidates upstream of the local
  adapter in separate predeclared runs; rejected candidates must not be
  transmitted and therefore create no uORB samples. Do not claim the pinned PX4
  receiver itself rejects these cases. A separate malformed-wire diagnostic, if
  ever authorized, records the receiver's actual publication behavior.
- [ ] Restore and verify all parameters, preserve ULog and confirm owned resource
  cleanup.

**Exit:** Receiver path is byte/field/time correct, no EV fusion flags are set,
vehicle remains unarmed, and rollback succeeds. Obtain separate authorization
for Task 6.

## Task 6: Disarmed EKF2 fusion observation

- [ ] Predeclare a development profile with EV position/height/velocity bits,
  yaw disabled, message variance mode, minimum quality 1, measured frozen delay,
  identity lever arm and explicit remaining aiding sources.
- [ ] Run normal, message-loss, source-loss, latency, restart/reset and covariance
  fault cases while disarmed.
- [ ] Audit EV aid-source observations, innovations, variances, test ratios,
  rejection/fused flags, EKF control/fault flags, reset counters, local position,
  attitude, timesync, ULog and supervisor evidence.
- [ ] Require bounded start/stop timing, continuity loss at the pinned 200 ms
  interval, active EV fusion stopped by about 400 ms, zero stale fusion after
  that timeout, no EKF numerical fault and exact parameter rollback.
- [ ] Freeze the accepted development profile before held-out random scenarios;
  retain every failure and prohibit test-set tuning.

**Exit:** Sustained disarmed fusion and all fault exits pass. This still does not
authorize arming or policy control.

## Task 7: Single-aircraft closed loop, then later scaling

- [ ] Write a separate closed-loop spec using PX4 state as the sole online state
  input to the safety supervisor; policy output remains bounded velocity/yaw.
- [ ] Pass development and frozen held-out single-aircraft scenarios with ULog,
  trajectories, collision, tracking, latency and recovery evidence.
- [ ] Only then revisit 5-aircraft capacity and the existing 0.873 RTF failure;
  do not reduce workload or acceptance thresholds.
- [ ] Consider 20 aircraft only after the five-aircraft evidence gate; 100
  aircraft remains downstream research.

## Review focus

- Direction of JPL-to-Hamilton conversion and the velocity skew Jacobian.
- Sample time never replaced by arrival time in a passing result.
- Camera covariance qualification never silently qualifies propagated samples.
- Health quality/reset evidence has one owner and cannot be caller supplied.
- Failure stops publication and setpoints; no stale replay or fabricated reset.
- Parameter rollback and ULog evidence survive every failed run.
- Unit, kinematic, physical SITL, HITL and flight claims remain explicitly
  separated.
