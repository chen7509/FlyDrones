# PX4 EstimatorStatus ROS source overlay

## Purpose and source choice

The pinned PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` message
`EstimatorStatus.msg` has SHA-256
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
The already byte-verified, unbuilt 260-file ROS source tree at
`results/px4-ros2-full-byte-build-dev-1701/source-v1` comes from official
`PX4/px4_msgs` commit `148bdb4b8214a4d8de83029777fe8d334c74db6f`.
Its `EstimatorStatus.msg` SHA-256 is
`dfef1210ff72fea4e37edbf493cce441825048eda460992d981813aa2cd113ea`;
the byte diff adds `GPS_CHECK_FAIL_JAMMED = 11` relative to fixed PX4.
The current `VehicleOdometry.msg` already matches the fixed PX4 blob.

[PX4's official uXRCE-DDS guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
requires ROS message definitions to match PX4 and says the configured topics
are compiled into the client. Use the fixed PX4 and official `px4_msgs`
sources already researched in
[the source-journal report](../../PX4_ROS2_SOURCE_JOURNAL_REPORT.md): both
BSD-3-Clause, with the latter pinned to the above commit; ROS 2 Humble/rclcpp
remains the existing Apache-2.0 consumer. No new runtime or dependency is
selected. The exact commit is not called an exact source match after this
derived overlay.

## Contract

Derive a **new** ROS build source tree from the previously verified v2 tree.
Reject a changed parent profile, wrong Git commit, non-260-file parent,
different original status message, invalid or linked PX4 replacement, and an
existing destination before copying. Copy every other source byte, replace
only `src/px4_msgs/msg/EstimatorStatus.msg` with the pinned PX4 bytes, and
write a new profile with the parent profile digest, old/new message hashes and
explicit derived schema. Verification checks the complete file set, bytes,
directory links, unchanged `VehicleOdometry.msg`, exact status overlay and
declared build command. The original parent remains unchanged.

The derived profile is a source candidate only: `build_started=false` and no
ROS type support, PX4 firmware, Agent source, EKF2 health, capture or training
qualification. It cannot be passed to the existing v2 build runner as if it
were the official unmodified Git tree; any later build needs a separately
declared runner/profile and the existing resource gate. Current host memory
is below the physical 4 GiB gate, so this phase launches no PX4/Gazebo/Agent,
Docker build or training.

## Verification

Use RED/GREEN tests on a small synthetic Git-derived parent for exact single
file replacement, original parent immutability, wrong source bytes, changed
parent, existing output, output tampering, link/extra-file rejection and
strict profile metadata. Then derive once from the real sealed parent and
the fixed PX4 fixture, verify all 260 files and report the actual byte-diff.
Keep refusal output and all earlier failed builds. Run affected build-source
regression, changed Ruff/diff checks and independent read-only review before
sealing. No test here is a compiled `px4_msgs` or live transport test.
