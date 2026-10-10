# Causal pair corrected physical attempt design

## Authorization boundary

The original `study-v10/capture-v1` candidate was refused before dispatch because adding the required post-startup member gate changed an auditor file included in its frozen runtime baseline. `study-v10` and its successful non-physical preflight remain immutable evidence; its physical destination remains absent.

Run exactly one new physical development attempt at a freshly generated `study-v11/capture-v1` destination. The attempt is permitted only after the `study-v11` prepare-only audit and its separate production startup-preflight audit both have no failures, the current committed tree still passes the package audit, the package command identifies that exact destination, and the resource scan is empty. Any precondition failure stops before dispatch. The destination, dispatch, completion and output files are never overwritten or retried.

## Frozen workload

Use the command prospectively declared in `study-v11/study-manifest.json`: 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, the same vehicle, board texture, gravity, supported-motion and lateral-force profiles, 200 ms future anchor, 8 s readiness limit, 2 s source/native/fan-out watchdogs, unchanged 250 ms causal stage deadlines, frozen OpenVINS configuration/binary and native-reference module. Do not lower physics/sensor load, raise timeouts, alter noise, initialize from Gazebo truth, publish ODOMETRY, arm, or bypass PX4/safety gates.

## Evidence and interpretation

Before launch record the current full commit, prepare audit, startup audit, resource scan and exact command. After the process exits record return code, destination existence and a new resource scan. Preserve the complete capture whether it succeeds or fails, including supervisor journal, runtime mappings, ULog manifest, source/fan-out/native/estimator records, physics/motion traces and all error files. Cleanup claims remain limited to the owned original process group; escaped descendants are not inferred absent from group cleanup alone.

A platform/runtime refusal is not a fruit-fly learning failure. Public OpenVINS initialization alone is not accuracy or health. VIO qualification requires the prospectively frozen trajectory gauge, full retained run, credible fresh reference only for offline scoring, estimator health/loss/reset evidence and closed safety/fusion gates. The attempt cannot qualify EKF2 injection, arming or flight by itself. Whatever the outcome, this exact target is immutable and no automatic rerun is allowed.
