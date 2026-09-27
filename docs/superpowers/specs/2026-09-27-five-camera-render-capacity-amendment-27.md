# Five-Camera Render Capacity Amendment 27: Per-Instance EKF Gate

## Trigger

After the selected-observer readiness correction, two retained native single-
subscriber reruns reached all five camera streams and exact 20/20 sensor transport
topology but failed the final PX4 gate. Different vehicles failed on each run. In
the second run, vehicle 4 remained missing accelerometer, gyroscope, and barometer
data and its ULog contained no `estimator_status_flags` dataset despite exact
Gazebo publisher/subscriber cardinality. The sequential startup currently pauses
each vehicle as soon as the PX4 startup script returns, before proving sensor data
has produced a complete safe EKF state.

## Correction

While each statically preloaded vehicle's existing resume pulse is active, restore
the bounded per-instance MAVLink health gate previously validated by the capacity
startup design. Require estimator healthy, disarmed, and landed before pausing and
starting the next vehicle. All five checks share a 120-second wall-time budget and
each check remains capped at 30 seconds. Preserve each `startup-health.json` with
the trial evidence. Do not restart bridges, weaken EKF flags, change camera
scoring, or retry a failed vehicle silently.

## Acceptance

- A structural test proves the health gate occurs after PX4 startup and before the
  per-instance pause.
- Every successful trial must preserve five per-instance startup-health records.
- The focused regression suite, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with all failures kept.
