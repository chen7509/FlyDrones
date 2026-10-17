# PX4 odometry causal adapter implementation plan

**Goal:** Preserve genuine PX4 `VehicleOdometry` callback timing and coordinate-reset boundaries for a future non-truth EGO student-capture producer.

**Spec:** `docs/superpowers/specs/2026-10-10-px4-odometry-causal-adapter-design.md`.

**Interfaces:** New `src/flydrones/connectome_training/px4_odometry_adapter.py` consumes typed callback records and an explicit camera extrinsic. It emits only a noneligible diagnostic candidate. It must not modify `capture_input.py`, the recorder, flight control or sealed old evidence.

**Global constraints:** No DDS/PX4/Gazebo/training launch while resource gate fails. No Gazebo truth in estimator input. `VehicleOdometry.quality=0` is unused and does not grant health. No automatic rebase after reset/session switch. No held-out comparison world inspection or tuning.

## Task 1: Input validation and reset/time latch

- [x] Write failing tests for valid source, malformed source/frame/covariance/quaternion, future or regressing sample/publication/receipt, changed instance/session, reset/wrap and permanent refusal.
- [x] Implement bounded event history and fail-closed latch; retain validated numeric source coefficients and refusal cause. Original DDS wire bytes await a subscriber.
- [x] Run targeted tests and adjacent reset/capture tests.

## Task 2: Causal camera candidate and transforms

- [x] Write failing tests for no-future publication and receipt, stale/missing event, NED→ENU position/velocity, rotated camera lever arm and orientation, and tilted yaw-rate against a finite-rotation oracle.
- [x] Implement candidate composition with explicit input domains and `eligible_for_live_capture=false`; no recorder call.
- [x] Run targeted tests, adjacent tests, changed Ruff and diff check.

## Task 3: Evidence and review

- [x] Record pinned source hashes, resource state, RED/GREEN/full adjacent outputs, known limits and all failures.
- [x] Obtain an independent read-only review and fix any safety-significant finding with a failing test first.
- [ ] Seal member hashes/CRC and archive SHA, commit to the current worktree, push only `personal`, update draft PR65 and the continuation prompt.
