# Causal camera-pair stage design

## Evidence and problem

The immutable `study-v9/capture-v1` failed before motion at simulation time 10 ms. CameraInfo and RGB for the same 2 ms frame reached the source 258,765,752 ns apart. The unchanged wall-wait limit is 250,000,000 ns. The current scheduler advances the source-arrival watermark and expires all pending records before inserting the arriving record, so the exact-stamp RGB cannot complete the CameraInfo dependency. A 4 ms IMU had already reached the source before the failure, but the single writer had not consumed it.

This is a dependency-stage defect, not evidence about OpenVINS accuracy, fruit-fly learning, PX4 control or flight. The previous correction remains valid: local record/native service time must not advance the source watermark. No physical retry is part of this stage.

## Upstream basis and scope

ROS 2 `message_filters` ExactTime groups inputs by their header timestamp and emits only after every channel with that exact timestamp has arrived; its queues are bounded by count. Fixed OpenVINS `ROS1Visualizer` queues camera data by sample timestamp and consumes it only after a strictly later IMU is available. These are reference semantics, not proof that this adapter is accurate or real-time. FlyDrones retains its stricter source-arrival, queue-capacity, image/IMU sample-lag, IMU-gap, session and failure-latch gates.

No new ROS dependency, transport, estimator, clock, timeout value or queue size is introduced. The fixed 250 ms limit remains a development transport refusal limit. The change is confined to when that same limit is evaluated while an exact-stamp dependency changes state.

## Required state machine

Each camera stamp has one current pending stage:

1. **Unmatched stage:** only RGB or only CameraInfo exists. Its stage start is that record's captured source-arrival time.
2. **Paired stage:** exact-stamp RGB and CameraInfo both exist but no consumed strictly later IMU exists. Its stage start is the later captured source-arrival time of the two records.
3. **Released:** a strictly later consumed IMU exists and the camera action is emitted once; both pending records are removed.

An arriving RGB or CameraInfo may transition only its exact-stamp counterpart from unmatched to paired before the old unmatched stage is expired. It must still pass the existing schema, fixed calibration/resolution, per-kind timestamp and arrival monotonicity, strict source sequence, input-age and capacity checks. It cannot revive a different stamp. The transition does not release the camera unless an actually consumed later IMU already exists.

Every unrelated camera record and every IMU must first expire all stages that it cannot complete. A paired stage waiting for IMU therefore still fails after 250 ms. An explicit idle tick expires every current stage. At exactly 250 ms the stage remains valid; one nanosecond later it fails and latches. If a matching record completes a stage, the paired stage uses the later arrival as its start and gets no exemption from the next-stage limit.

The watermark remains the maximum captured source arrival or an explicit proven-idle wall time. It never uses post-processing time or simulation-time extrapolation. The existing 200 ms image-to-latest-IMU sample lag, 4 ms maximum IMU gap, eight-per-kind capacity, 2 s source/native/fan-out watchdogs, transactional rollback, refusal record, reset/quality nulls and closed fusion gates remain unchanged.

## Verification

TDD must first reproduce the exact `study-v9` arrival clocks and fail on the late exact-stamp RGB. Additional RED cases must prove that an unrelated record cannot rescue an expired unmatched stage and that a paired stage still expires while waiting for IMU. Reverse RGB/CameraInfo order, exact 250 ms and plus-one-nanosecond idle boundaries, stale incoming records, queue capacity, IMU gap, rollback and latched failure remain covered.

After the minimal scheduler change, the exact fixed replay must emit one 2 ms camera only after consuming the actual 4 ms IMU. It must retain original source identities and bytes. No simulator, PX4, OpenVINS process, training, ODOMETRY, arming or fusion is run. A separate independent audit must reject changed limits, reordered input, missing failure cases or any positive downstream qualification.
