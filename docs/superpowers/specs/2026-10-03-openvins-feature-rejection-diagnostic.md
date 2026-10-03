# OpenVINS feature rejection diagnostic on development data

The textured development-world run initialized OpenVINS for 361 frames but
reported zero accepted MSCKF features and zero SLAM landmarks. Its inertial-only
trajectory diverged badly. The existing log is printed after the updater has
mutated its candidate vector, so it cannot identify which stage removed the
features.

Use the same 604 RGB frames, 15,107 PX4 ULog IMU samples, fixed camera/IMU
calibration, and static-initialization config from that run. Instrument a
separate checkout of the pinned upstream OpenVINS commit with **logging-only**
stage counts: candidates selected by VioManager; measurements retained after
clone filtering; features retained after triangulation/refinement and after
chi-squared screening. Rebuild the ROS-free library and adapter in isolation.
Keep the patch, source/binary hashes, exact command, raw logs, and output
states. Confirm the diagnostic replay produces byte-identical state CSV to the
uninstrumented run before attributing any rejection stage. No truth position
or pose enters the estimator. This is a development diagnosis, not a VIO pass,
PX4 EKF2 connection, or formal scenario result.

If a stage rejects all candidates, report that observation and the unresolved
causes. Do not loosen gates or tune against the held-out evaluation worlds.
The upstream remains GPL-3.0 and this diagnostic library is not part of the
FlyDrones flight stack.
