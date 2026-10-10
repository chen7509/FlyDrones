# Full PX4 Odometry Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve complete typed PX4 odometry alongside raw CDR without granting unproven live-source or training qualification.

**Architecture:** Add an opt-in v2 to the existing read-only C++ subscriber and a versioned Python auditor/extractor. Keep v1 exact behavior; use the existing causal adapter only for explicitly unqualified offline geometry.

**Tech Stack:** PX4 `d6f12ad`, pinned `px4_msgs` `148bdb4`, ROS 2 Humble typed `rclcpp`, Python 3.12, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-px4-ros2-full-odometry-journal-design.md`.

## Global constraints

- Preserve v1 CLI/schema/evidence and all historical failures.
- `quality=0` remains unused; no source, camera, training, fusion or flight grant.
- Keep exact CDR and typed geometry distinct; JSON hash is not source authentication.
- No C++ build, PX4/Gazebo, Docker or training while the existing host-memory/process guard fails.

## Review focus

- Nonfinite PX4 pre-estimation coefficients must be retained as null and rejected for geometry use.
- A row with valid-looking geometry but unrelated CDR must remain unqualified.
- V1 files must never acquire v2 semantics by inference.
- A quaternion with wrong order or norm must fail adapter conversion.
- A reset/GID/clock change must retain the existing fail-closed journal behavior.

### Task 1: Versioned reader and offline geometry

**Files:** `src/flydrones/connectome_training/px4_ros2_source_journal.py`, `tests/connectome_training/test_px4_ros2_source_journal.py`, new focused v2 tests if needed.

**Interfaces:** `audit_source_journal(path)` keeps v1 behavior and audits v2; `read_offline_odometry_geometry(path)` returns bounded v2 rows with a permanent false live-capture flag.

- [x] Write v2 normal/null/malformed/schema-mixing tests and verify RED.
- [x] Implement v2 validation and extraction; verify GREEN and v1 regression.
- [x] Add explicit unqualified conversion to the existing `VehicleOdometryEvent` shape, with invalid quaternion/variance/reset rejection; verify RED then GREEN.
- [x] Run reader and causal-adapter tests, Ruff and diff check.

### Task 2: Typed opt-in C++ writer

**Files:** `tools/connectome/px4_ros2_source/px4_odometry_source.cpp`, corresponding ROS source/build tests.

**Interfaces:** existing four arguments preserve v1; optional `--full-state-v2` selects v2 sample/fault/finish rows.

- [x] Write a failing test for v2 field layout, finite/null encoding and unchanged v1 route.
- [x] Implement bounded float32 serialization from the already decoded typed message; run tests.
- [x] Prepare exact-byte source and build typed collector under the guarded Docker run; retain the failed historical v1 build.
- [ ] Run typed synthetic callback and independent CDR parity. Three preserved attempts produced no ROS callback; two were memory refusals and one failed before ROS initialization.

### Task 3: Evidence and publication

**Files:** `docs/PX4_ROS2_FULL_ODOMETRY_JOURNAL_REPORT.md`, `evidence/px4-ros2-full-odometry-dev-1701.zip` and local results.

- [x] Preserve RED/GREEN, versions, hashes, test output, every failed run and build limitation.
- [x] Independently inspect reader/writer schema parity and qualification boundaries.
- [x] Run final targeted/adjacent tests, Ruff and `git diff --check`; seal ZIP with per-member hashes/CRC.
- [ ] Commit and push only `personal`, update draft PR65, leave owned live PX4/Agent, camera calibration and EGO integration as explicit later gates.
