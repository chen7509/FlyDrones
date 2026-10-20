# PX4 Estimator-Status Transport Prerequisite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Prove the pinned PX4 ROS bridge lacks the checked-capture fault field and prepare an exact, non-authorizing source candidate to expose it.

**Architecture:** A small PyYAML-based read-only preflight validates exact pinned YAML and message bytes, checks unique publication mappings, and compares a candidate with the pinned base. An immutable candidate YAML snapshot adds one publication. No live runtime is changed.

**Tech Stack:** Python 3.12, existing PyYAML 6, pytest, pinned PX4 d6f12ad source.

**Spec:** `docs/superpowers/specs/2026-10-12-px4-estimator-status-transport-design.md`

## Global Constraints

- Pinned PX4 commit and source SHA values are those in the spec.
- Candidate status publication is exactly `/fmu/out/estimator_status`, `px4_msgs::msg::EstimatorStatus`, `rate_limit: 20.`.
- All other topic entries and original files remain byte-for-byte unchanged.
- No PX4/Gazebo/Agent launch, no installed checkout mutation, no capture/training/fusion grant.

## Review Focus

- Duplicate YAML keys or publication topics must refuse, including when a naive safe-load would keep only one.
- A wrong status type or missing `filter_fault_flags` definition must refuse.
- Identically named but non-pinned base bytes and mismatched installed ROS messages must refuse.
- A syntactically valid candidate must remain unverified as a built or live PX4 transport.
- The candidate may not change the existing local-position or camera/physics load declarations.

### Task 1: Fixed-source preflight and candidate

**Files:** Create `src/flydrones/connectome_training/px4_status_transport.py`, `tests/connectome_training/test_px4_status_transport.py`, `configs/px4/estimator-status-dds-candidate.yaml`, and pinned test-source fixtures under `tests/fixtures/px4_status_transport/`.

**Interfaces:** `audit_status_transport(base_yaml: bytes, candidate_yaml: bytes, px4_msg: bytes, ros_msg: bytes) -> dict` returns exact topic/type findings and always-false runtime/capture qualifications. No launcher integration.

- [x] Write and run RED tests on the actual pinned base: status absent, candidate single permitted addition, duplicate/malformed/wrong type or field refusals, and permanent non-authorizing flags.
- [x] Implement the minimal parser and exact candidate comparison; run tests GREEN.
- [x] Verify original checkout source SHA and candidate serialization/diff without changing PX4.

### Task 2: Evidence and publication

**Files:** Create `docs/PX4_ESTIMATOR_STATUS_TRANSPORT_REPORT.md` and sealed evidence ZIP, including fixed-source hashes, rejected mutations, code, tests, changed Ruff/diff and independent review.

- [x] Run affected connection-group regression and changed Ruff/diff checks, then obtain read-only independent review and resolve findings with RED/GREEN.
- [x] Seal archive with per-member hashes and CRC; commit and push only `personal`, update PR65 and continuing automation.
