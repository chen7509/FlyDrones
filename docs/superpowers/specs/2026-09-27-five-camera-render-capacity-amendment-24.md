# Five-camera render-capacity amendment 24

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-223817/`
preserved the first complete per-process consoles. They show that unconditional
`gz_bridge` restart created replacement uORB sensor instances inside PX4:
`BARO switch from #0 -> #1`, `MAG switch from #0 -> #1`, repeated selected
sensor ID lookup failures, and stale accelerometer, gyroscope, barometer, and
magnetometer checks. Strict health therefore rejected vehicles 1, 2, and 3.

Restarting the bridge after PX4's sensor consumers are running is not a neutral
transport repair and must not be part of the benchmark startup path.

## Binding correction

1. Remove every capacity-mode `gz_bridge` stop/start command.
2. Keep Gazebo paused while each model is inserted and its four required sensor
   publishers are registered.
3. Immediately after one model's publishers appear, resume Gazebo and wait for
   that PX4 process to report `Startup script returned successfully`, proving
   its original bridge initialization completed.
4. Pause Gazebo again before creating the next model. Repeat in numeric vehicle
   order, then perform one final resume after all five instances complete.
5. Bound every resume, startup, and pause operation. Fail closed if a service
   call fails, a PX4 process exits, or startup does not complete. Preserve all
   ten per-instance world-control responses.
6. Retain the exact 1:1 sensor topic topology audit, renderer image-readiness,
   strict MAVLink/EKF2 health, ULog evidence, and all Gazebo/PX4 logs.
7. Keep models, poses, parameters, sensor rates, camera schedule, scored window,
   timeout, and performance thresholds unchanged.

This sequence initializes each original bridge exactly once while serializing
the first simulation-clock handoff that gates its sensor subscriptions.
