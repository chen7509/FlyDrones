# Five-camera render-capacity amendment 18

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-220047/` used the
entire shared 150 wall second startup budget. Vehicles 0 through 2 became
strictly healthy, but vehicle 3, which joined the already advancing lockstep
world later, retained missing accelerometer, barometer, EKF2, and gyroscope
inputs for the rest of the budget. Its `gz_bridge` had registered and the PX4
process stayed alive, so additional waiting did not repair the sensor stream.

Sequentially waiting for one PX4 to become healthy before adding the next made
later bridges join an already running multi-participant lockstep simulation.
That ordering can leave a newly added participant registered without receiving
the sensor ticks needed to initialize.

## Binding correction

1. In capacity mode only, start Gazebo paused and start/register all five PX4
   instances before advancing simulation time. Non-capacity launch behavior
   remains unchanged.
2. After all five processes are alive and registered, resume the world through
   the Gazebo world-control service and retain the service response as setup
   evidence.
3. Remove the per-instance temporary MAVLink gate. Use the existing concurrent
   five-vehicle MAVLink gate after renderer attestation, with the unchanged
   strict estimator-healthy, landed, and disarmed predicate.
4. Retain the 150 second scheduler/witness readiness deadlines and outer
   180 second setup deadline. Keep all PX4 parameters, poses, sensor models,
   trigger timing, scoring windows, and thresholds unchanged.
5. Preserve this failed run, update frozen hashes, and restart all three Task 6
   checks with new identifiers.

This aligns all lockstep participants at simulation start instead of retrying
or weakening failed sensor health.
