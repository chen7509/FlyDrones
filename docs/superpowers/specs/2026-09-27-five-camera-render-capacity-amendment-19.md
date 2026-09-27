# Five-camera render-capacity amendment 19

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-220647/` resumed the
paused world after creating all five PX4 processes. Vehicles 0, 2, and 3 became
healthy; vehicles 1 and 4 retained missing inertial/EKF streams. Their ULogs
confirm a transport-side distinction: healthy vehicles recorded roughly 9,000
`sensor_combined` samples plus barometer and estimator data, while vehicle 1
had no `sensor_combined`, barometer, or estimator stream and vehicle 4 lacked
those streams plus GPS. All camera topics and image streams were healthy.

The launcher resumed Gazebo immediately after process creation, before proving
that each PX4 process had completed its `gz_bridge` world/model binding. Some
participants therefore still joined after simulation time began, despite the
server itself having started paused.

## Binding correction

1. While Gazebo remains paused, wait until all five owned PX4 processes are
   alive and every instance log contains its exact `gz_bridge` world/model
   binding.
2. Use one bounded pre-resume loop; fail closed with per-instance logs if the
   bridge barrier is incomplete.
3. Resume Gazebo only after that barrier. Retain the existing post-resume topic,
   renderer, and concurrent strict MAVLink health gates.
4. Keep all PX4 parameters, models, poses, sensor rates, camera timing, scoring
   windows, and thresholds unchanged.
5. Preserve this failed run, update frozen hashes, and restart all three Task 6
   checks with new identifiers.

This completes the paused-start barrier; process creation alone is no longer
treated as lockstep participation.
