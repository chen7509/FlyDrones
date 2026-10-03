# Stationary-prelude development capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture one post-takeoff stationary development interval and test whether pinned OpenVINS can initialize and use visual features.

**Architecture:** An optional development-only runner flag advances zero velocity setpoints through the existing PX4/Gazebo gateway before policy decisions. A separate offline gate verifies EKF2 velocity and camera/ULog evidence, then the existing adapter and OpenVINS runner replay the episode unchanged.

**Tech Stack:** Python 3, pytest, PX4 SITL, Gazebo Sim in WSL Ubuntu, pyulog, pinned OpenVINS.

**Spec:** `docs/superpowers/specs/2026-10-03-vio-stationary-prelude.md`

## Global Constraints

- Existing formal benchmark runner behavior remains identical when the new flag is absent.
- Prelude requires RGB and camera-info recording, no formal freeze manifest, a finite 50 ms step multiple and at most 8 s.
- Use only saved textured development fixture 1701; preserve every failed run and do not repeat for tuning.
- PX4 and the existing safety/command shaping stay in control; EKF2 speed is an offline gate only, not VIO input or true pose.

## Review Focus

- Non-finite, negative, over-8-second and non-step-multiple prelude values reject before simulator startup.
- A formal freeze manifest or missing camera capture rejects a nonzero prelude.
- A collision/out-of-bounds during prelude terminates the episode and is not hidden by subsequent controller decisions.
- A quiet interval missing valid EKF2 speed or synchronized RGB/ULog must not trigger a VIO replay.
- The original no-flag runner must keep its command and scoring order.

---

### Task 1: Development-only hover prelude

**Files:** Modify `tools/benchmark/run_episode.py`; create `tests/benchmark/test_stationary_prelude.py`.

**Interfaces:** `prelude_step_count(seconds: float, dt_s: float, *, frozen: bool, record_rgb: bool, record_camera_info: bool) -> int`; the CLI uses this before start and advances `Command((0,0,0),0)` exactly that many steps.

- [ ] Add failing tests for valid count, zero default, invalid boundary values, formal-manifest/camera guards, and prelude termination on scorer status.
- [ ] Run red, implement minimal flag and helper without changing the zero-step path, then run green.
- [ ] Run targeted tests, Ruff and full regression; commit the runner change.

### Task 2: One capture, conditional replay and evidence

**Files:** Create `tools/benchmark/audit_stationary_prelude.py` and tests as needed; create `docs/OPENVINS_STATIONARY_PRELUDE_REPORT.md` and indexed evidence ZIP.

**Interfaces:** The audit consumes a completed episode directory, verifies RGB/camera/ULog manifests and scores valid EKF2 velocity over the two seconds before first policy decision. It writes a non-overwriting JSON and per-sample CSV. Successful gate permits exactly one existing-adapter export and one unchanged OpenVINS replay.

- [ ] Test gate rejection for missing/invalid data and verify normal calculation on a small fixture.
- [ ] Run one new PX4/Gazebo capture with prelude in an isolated output directory; preserve result even on failure, inspect process cleanup and raw hashes.
- [ ] Audit the data gate; if it passes, export and replay OpenVINS once, preserving stdout/stderr/states and actual visual-update counts; otherwise stop this experiment and explain why.
- [ ] Build and independently verify a non-overwriting indexed evidence archive, report limits and all failures.
- [ ] Run focused tests, Ruff, `git diff --check` and full regression; request read-only review, fix important issues and create a draft PR.
