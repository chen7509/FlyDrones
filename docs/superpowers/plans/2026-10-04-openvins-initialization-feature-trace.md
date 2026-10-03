# OpenVINS Initialization Feature Trace Plan

**Spec:** `docs/superpowers/specs/2026-10-04-openvins-initialization-feature-trace-design.md`

**Goal:** Explain, with frame-aligned evidence from the frozen prearm capture, why the fixed OpenVINS initializer did not accept the early stationary RGB/IMU interval.

## Constraints

- Read saved input only; no new PX4/Gazebo, training, or formal test-set tuning.
- New isolated upstream checkout at `69488123ed9362dd44b6f28e7f4680abbff1442b`; logging-only patch; preserve original library and replay.
- Same input export/config/runner; compare the full state CSV SHA to the original before interpreting feature counts.
- No PX4 visual fusion or safety success claim from offline analysis.

## Task 1: Instrument and parse

- [x] Verify source hashes, upstream commit/license, original replay inputs and available resources.
- [x] Add failing tests for timestamp alignment, absent feature records, duplicate/out-of-order frames and phase counts.
- [x] Add minimal structured feature/initializer logs in the isolated upstream clone and build a separate library.
- [x] Replay once in a new output directory; save command, build-verification log, source patch, library/runner/config/input hashes, state and raw logs.
- [x] Parse and audit each attempted image, record missing/ambiguous links, and assert state CSV equality to prior replay.

## Task 2: Interpret and preserve

- [x] Quantify before/prearm/after-prearm-to-initialization feature counts and rejection stages; inspect representative raw frames only as supporting context.
- [x] Report what this proves and does not prove; propose the next independent development fixture only if the gate is actually supported.
- [x] Run focused/full regression and Ruff; request independent read-only review; seal logs with SHA-256, preserving the first seal and reviewed v2.
- [x] Commit and push draft stacked PR #24 after PR #23's 20 evidence parts were uploaded and both ZIPs reconstructed from a fresh remote checkout with member-hash verification.
