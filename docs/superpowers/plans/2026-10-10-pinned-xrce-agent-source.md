# Pinned XRCE Agent Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a hash-bound, separately copied Agent v2.4.3 source candidate with immutable dependency references for a later bounded build.

**Architecture:** A standard-library preparer reads exact Git blobs from the known Agent checkout, checks the fixed commit/tree and selected source hashes, then writes a new source directory with five exact CMake reference substitutions and a file-hash manifest. No build or simulator is invoked.

**Tech Stack:** Python 3.12, Git, pytest; upstream Agent v2.4.3 source already present in `results/px4-agent-v243-source-dev-1701/upstream`.

**Spec:** [pinned source design](../specs/2026-10-10-pinned-xrce-agent-source-design.md)

## Global Constraints

- Preserve the upstream checkout, every prior evidence directory, and default Agent feature profiles.
- Require Agent commit/tree and selected-file hashes from the spec; replace only the five exact old CMake values.
- No dependency download, build, Agent/PX4/Gazebo/ROS run, ODOMETRY publishing, EKF2 change or training grant in this stage.

## Review Focus

- A wrong HEAD with the same-looking worktree must refuse.
- Windows checkout CRLF must not change copied Git blob bytes.
- A duplicated dependency declaration must refuse rather than replacing both.
- A symlink/gitlink or traversal-like Git name must not escape the destination.
- A failed preparation must never be misread as a qualified binary.

## Task 1: Exact source transformation

- [x] Write a synthetic Git fixture and RED tests for fixed tree/blob copying, exact five replacements, wrong commit/hash, duplicated/missing literal, unsupported Git mode, and existing destination.
- [x] Implement the minimal standard-library preparer with strict source limits and a manifest that leaves binary/interop qualifications false.
- [x] Run focused and adjacent tests, Ruff and diff check.

## Task 2: Real fixed source preparation and evidence

- [x] Verify no conflicting process; run the preparer once against the fixed Agent checkout into a new results directory.
- [x] Independently compare all output hashes, original Git blob hashes and five substituted CMake values; retain errors if any.
- [x] Record upstream license/version/maintenance/resource/adapter limits, seal source/manifest/tests/report with member hashes and CRC, request independent review, then commit and update PR65.

## Later build gate (outside this stage)

- [ ] Fetch each exact dependency Git object, prove commit type/tree/license/submodule closure, and freeze compiler/CMake/linked libraries.
- [ ] Only with adequate memory and no competing process, use a new bounded build directory and validate executable/version/UDP handshake with the fixed PX4 v2 client in a separately authorized unarmed study.
