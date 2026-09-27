# Five-camera render-capacity amendment 14

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-214439/` gave the
strict PX4 health gate 30 wall seconds. Vehicles 1, 2, and 4 became estimator
healthy, but vehicles 0 and 3 still had no `ESTIMATOR_STATUS`. Their retained
PX4 console logs never reached `Ready for takeoff!` and continued to report
missing accelerometer, gyroscope, compass, and EKF2 data. The launcher had
already classified all instances as started because it required only a running
process and a `gz_bridge` world/model log line.

The five PX4/Gazebo bridge initializations were launched at fixed two-second
intervals without proving that the prior instance had received its simulated
sensor streams. Under the measured slow, loaded simulator this allowed several
bridge/model startups to overlap; a bridge log line alone did not prove sensor
fusion readiness, and waiting after all five starts did not repair an instance
whose sensor stream attachment never completed.

## Binding correction

1. Keep a single 120 wall second startup budget for all five PX4 instances.
2. After starting and registering each instance, require that same instance's
   console reach PX4's `Ready for takeoff!` health marker before starting the
   next instance. Fail closed if the process exits or the shared startup budget
   expires.
3. Retain the later concurrent MAVLink gate as independent evidence: every
   estimator must still be healthy and every vehicle landed and disarmed.
4. Keep poses, model, world, PX4 revision, camera scheduling, renderer, scoring
   windows, and thresholds unchanged.
5. Preserve this failed run, update launcher frozen hashes, and restart all
   three Task 6 development checks with new identifiers.

This changes only setup ordering. No PX4 or estimator parameter is relaxed.
