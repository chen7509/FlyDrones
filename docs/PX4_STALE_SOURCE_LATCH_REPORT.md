# PX4 odometry source-loss latch (2026-10-10)

The read-only `Px4OdometryCausalAdapter` now latches the existing `PX4 state stale at camera` refusal for the rest of its session. Previously it rejected only that camera query; a later odometry event could make the same adapter emit a candidate again without any explicit source/session reset. That would hide an observed source-health gap from a future student capture producer.

The fix changes one branch: if the selected causal PX4 event is older than the existing 100 ms sample-age or receipt-age limit, it stores the refusal in `failure_reason` before raising. Subsequent `push()` and `at_camera()` calls reject until a separately constructed adapter begins a new session. A camera query before the first PX4 event still refuses without latching, so startup can await its first state. The age limits, NED/ENU geometry, calibration placeholder, and `eligible_for_live_capture=false` are unchanged.

The pinned PX4 `VehicleOdometry` interface carries separate publication and sample timestamps plus `reset_counter`; its `quality` field is unused in the reviewed version. This change does not reinterpret those fields or grant EKF2 health. The fixed upstream source remains [PX4 `VehicleOdometry.msg`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleOdometry.msg), BSD-3-Clause. The existing adapter consumes no extra CPU-intensive dependency, and the change adds one assignment on an already failing path. No new package or alternative estimator was adopted.

The new regression first failed twice because stale camera refusals left `failure_reason=None`; the no-state startup control passed. After the one-branch change, an exact 100 ms boundary case was added as GREEN coverage. The final adjacent run of the adapter, capture-input gate, ROS 2 source-journal and reset-epoch suites passed **117/117**. Changed-file Ruff and `git diff --check` passed. Independent read-only review found no Critical, Important or Minor findings and confirmed that no production caller or live-source grant follows from this change. These are synthetic/file-level tests; no ROS 2 Agent, PX4, Gazebo, EGO, full MaleCNS, or training process ran. The later physical study-v5 remains unstarted below the frozen 900,000 KiB memory reserve.

| Status | Evidence |
| --- | --- |
| Verified | Deterministic RED/GREEN for stale sample and stale receipt, session latch after failure, recoverable pre-first-state refusal, exact-boundary coverage and 117 adjacent tests. |
| Implemented only | Fail-closed state in the local causal adapter. A future live producer must still bind its callbacks to an owned PX4/Agent source. |
| Not tested | Actual DDS provenance and receipt clocks, camera calibration/epoch mapping, EKF2 fusion, EGO teacher trajectory, student training, multi-aircraft performance, hardware or flight. |
| Failed or blocked | Prior PX4 TIMESYNC, five-camera 0.873 RTF and study-v3 startup failures remain; study-v5 physical run awaits sufficient host memory. |

This local safety correction is a prerequisite for a provenance-bound producer, not that producer itself. In particular, an arbitrary caller can still fabricate `VehicleOdometryEvent` and `CameraStamp`; the adapter's candidate remains unqualified for live capture or training.
