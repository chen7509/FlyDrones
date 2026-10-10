# Raw-depth capture startup-only binding probe

## Question

The first study-v3 physical attempt failed before Gazebo/PX4 startup because its declared runtime inventory omitted imported collector modules. Study-v5 adds those modules but has only static diagnostics. Determine whether the **real capture worker** accepts the exact frozen study-v5 files and resource graph before committing another expensive physical attempt.

## Boundary

Use the existing `capture_disarmed_sensors.py --startup-preflight` path. Source study-v5 is immutable; derive a new, exclusive output destination and command with only `--output` redirected and `--startup-preflight` appended. Do not alter its execution contract, binding, estimator/config, camera/IMU load, source audit, safety thresholds or physical run destination. The startup path copies the fixed scene, checks the binding and returns before importing `gz.sim8.TestFixture`, starting PX4 or stepping physics. The result is a startup-binding check, **not** a 25-second sensor/VIO or depth capture.

Record an exclusive probe manifest with source manifest hash, exact command, resource observation and declared nonphysical scope before dispatch. Refuse a preexisting output, relevant competing process or any declaration mismatch. Retain stdout, result, supervisor events, resource map, errors and all partial output on failure. Never retest the same destination. A passing probe can reduce startup uncertainty but cannot authorize fusion, training or flight; study-v5 still requires independent host memory and process checks for any future physical dispatch.
