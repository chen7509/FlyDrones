# Stationary-prelude development capture for OpenVINS

The frozen textured development capture gave OpenVINS a static initialization
while PX4 EKF2 estimated about 0.4 m/s motion. Test one controlled hypothesis:
with the same single-vehicle development world, sensors, PX4 model, estimator,
camera/IMU adapter, thresholds and flight controller, does a genuinely quiet
post-takeoff interval permit a better initialization and any visual updates?
This remains a development diagnosis; it does not alter or pass the 20 frozen
evaluation worlds, five-vehicle capacity, or flight-readiness gates.

[OpenVINS's static initializer](https://docs.openvins.com/classov__init_1_1StaticInitializer.html)
explicitly assumes the IMU starts stationary. Add an optional, off-by-default
**development-only** hover prelude to the existing episode runner, after PX4
takeoff and before the controller's first decision. Use the existing
`Gateway.advance(Command((0,0,0),0))` path, so PX4 offboard, fixed-step
dynamics and command shaping remain in charge. Accept only a finite whole
number of the configured 50 ms steps, at most eight simulated seconds, and
only with RGB and camera-info recording and no formal freeze manifest. Score
each prelude step for bounds/contact; preserve any failure. Record requested
and actual prelude steps, start/end simulated times and the unchanged default
zero-prelude behavior in the result. No policy state or model weights change.

Run **one** new capture using the already saved textured development fixture
and a new output directory. Copy the two texture PNGs beside the snapshot SDF
before launch, preserving source hashes. Preserve the complete episode,
including unsuccessful result, PX4 ULog, RGB, camera info, clocks and process
records. After the run, verify no related PX4/Gazebo process remains. Before
OpenVINS replay, score the last two seconds before the first controller step
using valid PX4 EKF2 velocity with no resets or >20 ms gaps. A speed-median
below 0.1 m/s is an **offline prelude criterion**, not physical ground truth.
If this fails or camera frames are missing, report the failure and stop this
experiment without tuning or re-running it to get a pass.

If the quiet-window data gate passes, export IMU/RGB with the existing adapter
and replay once using the pinned upstream OpenVINS commit
`69488123ed9362dd44b6f28e7f4680abbff1442b` (GPL-3.0), same v2 config,
runner and library. Compare initialization, state divergence and actual visual
update counts against the earlier development capture. Changing a prelude
changes subsequent timestamps and path, so do not present this as a causal
paired-flight result or policy benchmark. In all outcomes keep hashes, logs,
unscored cases and clear simulation/replay limitations; never inject EKF2 or
Gazebo truth into VIO.
