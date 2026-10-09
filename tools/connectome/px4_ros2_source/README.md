# Read-only PX4 odometry source collector

This ROS 2 Humble program subscribes to `/fmu/out/vehicle_odometry` and never publishes a ROS/PX4 topic. It writes one exclusive-create JSONL journal of ROS serialized CDR bytes, local callback time and RMW metadata. A `complete` terminal row means only that a syntactically complete journal was written; the caller must also retain the process exit, selected binary and source hashes, Agent/PX4 identity, and file hash. The journal reader in `src/flydrones/connectome_training/px4_ros2_source_journal.py` always leaves live capture ineligible.

Build prerequisites are ROS 2 Humble `rclcpp`, OpenSSL and **official** `PX4/px4_msgs` at commit `148bdb4b8214a4d8de83029777fe8d334c74db6f`. Its `msg/VehicleOdometry.msg` Git blob must be `cf117ff82cdbf191bf576db91db900b7ce34f6a7`, matching the fixed local PX4 checkout. Do not replace it with whatever `px4_msgs` main branch happens to contain. Run `colcon build --packages-select px4_msgs flydrones_px4_ros2_source --executor sequential --parallel-workers 1` in a writable ROS workspace containing those two packages, after sourcing `/opt/ros/humble/setup.bash`. Before a build, check host free memory and existing tests/PX4/Gazebo; the 2026-10-10 host had only about 0.5–1.3 GiB free, so a full `px4_msgs` build was not dispatched in that state.

Usage after a verified build:

```text
px4_odometry_source OUTPUT.jsonl RUN_ID MAX_SECONDS MAX_SAMPLES
```

The output path must not exist. The process has bounded duration and sample count, stops on observed source identity/reset/time change, and leaves all failures in the journal or as an incomplete file with a nonzero exit. CDR is the representation delivered by ROS RMW; it is not the Ethernet/XRCE packet. RMW publisher GID is only local-context continuity evidence and cannot authenticate an owned PX4 process. `quality=0` in the pinned PX4 EKF2 publisher is an unused field and is never treated as health. No camera calibration, goal-frame reset, EGO teacher or VIO fusion is inferred from this program.
