# PX4 visual odometry degradation stress design

## Purpose

Measure whether the existing fixed PX4 forest policy remains safe when the external-vision stream becomes imperfect after GNSS fusion is disabled. This phase changes sensor inputs and evidence collection; it does not train policy weights or claim real-camera VIO validation.

## Architecture

The Gazebo `OdometryPublisher` sends its covariance odometry to a raw topic only in the fault-trial model copy. A separate Python Gazebo Transport relay receives that raw stream and republishes one stream per vehicle on the unchanged `/model/<name>/odometry_with_covariance` topic consumed by PX4. The relay preserves the raw message header and covariance except for explicitly configured perturbations. Default launch paths continue using the original direct topic.

A versioned JSON profile fixes the random seed, affected vehicle, delay, dropout window/probability, position drift, and false-pose offset. A marker written when the worker disables GNSS fusion activates the fault. The relay writes per-message input/output events, monotonic receipt and publish times, perturbation values, and counts. Every run gets a distinct output directory and profile/hash manifest. No failed run is deleted or reclassified.

## Sequence

1. Validate the perturbation engine with deterministic unit tests, including no-fault identity, delay order, dropouts, drift, false pose, and malformed profiles.
2. Validate Gazebo raw-to-relay-to-PX4 wiring with one vehicle and check ULog `vehicle_visual_odometry` against relay output.
3. Run one vehicle with GNSS fusion off and one fault at a time. Keep the fixed policy and flight limits.
4. Freeze the profile set, then run the same fault implementation for five independent vehicles, faulting vehicle 0, while recording all outcomes.
5. Assess both safe continuation and fail-closed landing. Collision, missed landing, or continued autonomous commands with invalid estimator state are failures, even if the process exits normally.

## Evidence and interpretation

Preserve the profile and SHA-256, relay event log, worker CSV/JSON, PX4 ULog, EKF aid-source evidence, and aggregate report for each run. Report mission completion, tree contacts, minimum tree clearance and intervehicle distance, estimator validity/fusion, actual input-to-output delay, position error against simulator truth when available, landing action, and decision time. `accepted` must require the stated safety outcomes rather than just a configuration acknowledgement.

The model input is Gazebo ground-truth odometry perturbed at the transport layer. It does not reproduce a camera/IMU VIO algorithm, image texture, blur, lighting, calibration errors, or onboard compute latency. The next phase must replace this stream with image-and-IMU-derived VIO before hardware claims.
