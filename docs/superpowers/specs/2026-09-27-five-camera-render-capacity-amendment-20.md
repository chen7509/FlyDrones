# Five-camera render-capacity amendment 20

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-/` passed the
paused-world process and model-name barrier and produced all five camera
streams. Strict MAVLink health still rejected vehicle 3. Its preserved ULog
contained GPS and barometer data but no `sensor_combined`, magnetometer, or
estimator datasets. The other four vehicles reached estimator health.

Local PX4 source inspection establishes why the earlier barrier is
insufficient: `GZBridge::task_spawn()` prints the world/model line before
calling `GZBridge::init()`. Initialization then waits for the first simulation
clock sample before registering pose, IMU, magnetometer, GPS, and barometer
subscriptions. The log line therefore proves model selection, not completed
sensor binding.

## Binding correction

1. Retain the paused-world five-process and five-model-name barrier.
2. Resume Gazebo and wait for all five models' IMU, magnetometer, GPS, and
   barometer topics to be advertised.
3. Restart each owned PX4 instance's `gz_bridge` once, after those publishers
   exist, using its stable world and model name.
4. Require publisher and subscriber presence on all 20 sensor topics before
   renderer attestation and MAVLink/EKF2 health checks. Preserve the raw topic
   introspection as `px4-sensor-topic-connections.json`.
5. Fail closed on any rebind command, missing publisher, missing subscriber, or
   dead PX4 process. Preserve rebind logs and all failed-run evidence.
6. Keep vehicle parameters, models, poses, camera schedule, sensor rates,
   scoring windows, and performance thresholds unchanged.

This amendment distinguishes model selection from completed transport binding
and makes the latter directly auditable.
