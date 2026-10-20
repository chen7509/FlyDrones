# Bounded PX4 EstimatorStatus ROS type build

## Intent and scope

The fixed PX4 `d6f12ad` cannot be compared to a typed ROS status subscriber
until its message definition has generated ROS 2 type support. The sealed
source-only overlay (`source-v2`, profile SHA-256
`fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654`)
contains 260 source files and differs from the official parent in exactly
`EstimatorStatus.msg`. This stage makes a **separate, one-shot offline build**
of that overlay. It does not rebuild PX4 firmware, run an Agent or subscriber,
or qualify an online PX4 source.

PX4's [uXRCE-DDS guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
requires matching message definitions between compiled firmware and ROS 2.
The already studied official PX4/px4_msgs commits are BSD-3-Clause; the
existing ROS Humble/rclcpp consumer and
[colcon-cmake](https://github.com/colcon/colcon-cmake/blob/master/colcon_cmake/task/cmake/build.py)
are Apache-2.0. The installed image and library versions, maintenance
observation, interfaces and adaptation costs remain documented in
[the source journal](../../PX4_ROS2_SOURCE_JOURNAL_REPORT.md) and
[the full build report](../../PX4_ROS2_FULL_ODOMETRY_JOURNAL_REPORT.md).
The prior full-state build succeeded only after `MAKEFLAGS=-j1`; its 768 MiB
container and 900,000 KiB host-free minimum are retained. That build took
2,483 s. The old v1 attempt exceeded 768 MiB with inner parallel Make jobs.

## Frozen execution and eligibility

Use the existing pinned `fly-ego-benchmark:humble` image ID
`sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`.
The command is the source profile's declared `MAKEFLAGS=-j1` sequential
`colcon build --base-paths src --packages-select px4_msgs
flydrones_px4_ros2_source --executor sequential --parallel-workers 1
--event-handlers console_direct+`. The collector remains the existing
odometry-only collector; no new status subscriber is built in this stage.
Use one CPU, 768 MiB memory and swap limit, 128 PIDs, no network and a
3,600-second timeout. Before launch require at least 900,000 KiB host
available memory, the exact image ID, no running Docker container or
competing build/physics/training process, and no existing owned container.
The physical PX4/Gazebo gate remains 4 GiB; this offline build's lower gate
does not relax it.

The one exclusive result directory contains a frozen run profile, source
copy, preflight, launch arguments, complete colcon log, process exit,
post-build source verification, generated type hashes and owned-container
cleanup observation. Source and copy profiles must match the pinned overlay
SHA, and the verifier must report 260 source files before and after the build.
The Docker daemon identity used before launch must equal the identity used
for postflight cleanup inspection; unknown identity or cleanup means fail.
An observed failure remains a distinct failed attempt and is never retried
in place.

Only exit 0, source stability, no timeout/launch error, exact installed
`EstimatorStatus.msg` SHA
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`,
present nonempty generated IDL/struct/type-support header and compiled
type-support library files with hashes, and
an empty owned-container postflight may qualify **compiled ROS status type**.
That qualification says nothing about firmware code generation, DDS wire
compatibility, publisher identity, latency, EKF2 safety or training.

## Failure and test evidence

Before a build, synthetic tests reject changed source/profile, wrong image,
insufficient memory, competing process/container, existing output/name,
malformed daemon identity and cleanup-query failure. A postflight result
classifier must refuse nonzero Docker exit, timeout, missing generated files,
wrong installed message, changed source or residual container. RED/GREEN,
adjacent regressions, changed-file lint, independent review and a sealed
evidence archive precede any success claim. The build itself may take about
40 minutes; preserve all logs and do not start another competing job.
