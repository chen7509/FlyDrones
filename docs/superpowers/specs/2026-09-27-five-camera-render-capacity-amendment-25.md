# Five-camera render-capacity amendment 25

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-224351/`
completed five successful per-instance resume/startup/pause handshakes. Vehicles
0 through 3 produced hundreds of phased depth frames, while vehicle 4 produced
none. ULogs still showed isolated missing low-rate sensor streams on other
vehicles. All corresponding topics had exact 1:1 transport topology and Gazebo
reported no explicit sensor creation error.

The remaining shared condition is runtime EntityFactory insertion: every model
and its sensor graph is added after the sensor system has already started.

## Binding correction

1. Extend the deterministic forest-world generator with an optional list of
   vehicle Y poses. It must emit five named `model://x500_depth_fly` includes at
   the existing frozen poses.
2. In capacity mode, generate the world with all five vehicles preloaded before
   Gazebo starts. Non-capacity launch behavior remains unchanged.
3. Start each PX4 with `PX4_GZ_MODEL_NAME=x500_depth_fly_N` so it attaches to
   the pre-existing model. Do not pass `PX4_SIM_MODEL` or request runtime model
   creation in capacity mode.
4. Retain the sequential per-instance resume/startup/pause handshake so the
   original bridges still receive their first clock and initialize one at a
   time.
5. Retain exact sensor topology, renderer image readiness, strict MAVLink/EKF2
   health, ULog, process ownership, and cleanup gates.
6. Keep model assets, poses, physics, sensor rates, camera schedule, timing,
   score window, and thresholds unchanged.

This removes runtime model and sensor creation from the capacity experiment
while preserving the tested physical system.
