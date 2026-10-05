# OpenVINS Fast Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task by task.

**Goal:** Verify fresh 50 Hz native inertial propagation on the sealed 10 Hz camera replay, without granting flight/fusion permission.
**Architecture:** Optional side stream from existing C++ probe; frozen-library API plus fail-closed Python auditor.
**Tech Stack:** C++17/OpenVINS/OpenCV, Python/NumPy/pytest, existing WSL.
**Spec:** docs/superpowers/specs/2026-10-05-openvins-fast-propagation-design.md

## Tasks

- [x] Add failing tests in tests/benchmark/test_openvins_fast_propagation.py for grid completeness, no future camera, exact source IMU boundary, bad arrays/covariance, stale filter, nonzero offset, failed propagation and missing prearm endpoints. Implement audit in tools/benchmark/audit_openvins_fast_propagation.py;20 focused tests passed.
- [x] Add tools/benchmark/openvins_fast_probe.h using actual pinned propagator, no substitute integrator. Extend optional side-stream scheduling in openvins_state_probe.cpp and protect three outputs against aliases/overwrite. Compile and record all source/binary/library hashes.
- [x] Verify source hashes, execute one fixed replay in fresh directory, compare original CSV SHA, audit every target including failed rows and prearm202 targets; save wall/RSS/API latency and source-input boundary limitations.
- [x] Run regressions and independent code/evidence/report review;627 Python tests passed, no review findings. Preserve all unsuccessful initialization targets and ten offline fault corruptions. Native propagation evidence reviewed; frame/message implementation is the next dependency.
- [x] Seal report/evidence and open stacked draft PR: https://github.com/chen7509/FlyDrones/pull/32 . Evidence43members, ZIP SHA25c50d945156e6a05e14e52afa73b9acffd048a1bb3dbdfb6d484e7685015d29. Checklist closure recorded after publication; sealed archive retains the pre-publication checklist unchanged.

## Review Focus

- Future images or IMU lookahead hidden as online latency: explicit boundary metadata and strict source-list checks.
- Propagation cache alters camera filter or mixes time bases: before/after invariance and CSV parity; reject nonzero offset.
- State/covariance ordering or velocity frame mislabeled: exact native shape/schema and no premature MAVLink packet.
- Failed/null rows dropped to inflate pass rate: complete frozen grid and prearm expected count.
- Output alias and source overwrite: use existing exclusive output helper across all output paths; do not mutate old evidence.
