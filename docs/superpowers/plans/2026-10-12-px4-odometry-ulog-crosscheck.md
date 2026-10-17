# PX4 odometry ULog cross-check implementation plan

> **For agentic workers:** Use the existing task's TDD and independent-review workflow. The user has already authorized continued implementation without another plan approval.

**Goal:** Add the missing exact-field ULog/ROS journal comparison prerequisite for a future owned PX4 source capture.

**Architecture:** Keep a small pure comparator beside the existing ULog preflight and source-journal reader. Reuse their validated shapes, perform an exact timestamp join and float32 bit comparison, and return a permanently non-authorizing audit. No network or simulator code changes.

**Tech stack:** Python standard library, NumPy already required by the source journal, existing `pyulog` dataset shape; no new installation.

**Spec:** `docs/superpowers/specs/2026-10-12-px4-odometry-ulog-crosscheck-design.md`.

## Tasks

1. Add synthetic two-row journal/ULog tests for exact scalar and float32 field parity and permanent false authority flags. Observe RED for missing comparator.
2. Implement the narrow join and comparison. Run focused tests GREEN.
3. Add refusal cases for absent/duplicate topic, missing/duplicate keys, changed timestamp, frame, reset, quality, individual array component, nonfinite or malformed value. Run them GREEN.
4. Run the existing historical ULog preflight to confirm absence of `vehicle_odometry` remains a refusal. Do not launch a competing PX4/Agent/Gazebo process.
5. Run adjacent regression, Ruff and diff checks; obtain independent read-only review and fix material findings. Seal all outputs and source, update report, commit and push only `personal`, then update draft PR65. The later physical study must still establish actual process/clock/camera/EKF2 identity.
