# OpenVINS Prearm Board Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether two honest, textured, near-start physical boards make the fixed OpenVINS front end establish enough prearm tracks without changing the aircraft, estimator or formal benchmark.

**Architecture:** An isolated development-world generator composes existing world routing/SDF/texture helpers and emits provenance hashes. The existing single-aircraft PX4 runner captures a new episode; the pinned offline runner and feature audit compare it to the preserved failure.

**Tech Stack:** Python 3.12, PIL, existing FlyDrones world/SDF code, PX4 SITL/Gazebo in WSL Ubuntu, pinned OpenVINS C++/OpenCV.

**Spec:** `docs/superpowers/specs/2026-10-04-openvins-prearm-board-fixture-design.md`

## Global Constraints

- Development seed 1701 only; do not edit formal 20-scene inputs, safety supervision, policy, OpenVINS/PX4 parameters, camera calibration or old evidence.
- Add two physically collidable boards with matching visuals; validate geometry/route and source provenance before PX4.
- One fresh PX4/Gazebo run and one fresh offline replay; leave failures intact and record actual WSL RTF and compute delays.
- Never label offline VIO as PX4 fusion or Gazebo truth as VIO.

## Review Focus

- Wrong input world or a non-empty output directory must fail without overwriting.
- Source SDF and JSON disagreement must fail instead of silently changing physics.
- Board collision/visual geometry and textures must match, with a route still open.
- A board outside actual RGB frame must be recorded as an integration failure, not an OpenVINS failure.
- A process exit code 0 with `out_of_bounds` remains a failed flight.

### Task 1: Deterministic physical-board fixture

**Files:** Create `tools/benchmark/make_prearm_board_fixture.py`, `tests/benchmark/test_prearm_board_fixture.py`.

**Interface:** `make_prearm_board_fixture(source_json: Path, source_sdf: Path, output_dir: Path, *, texture_seed: int = 1701) -> dict` consumes the unmodified public 1701 world; produces two physical boards, existing deterministic textures, complete provenance. Reuse `generate_development_world`, `has_route`, `write_sdf`, and `make_vio_texture_fixture.make_fixture`.

- [x] Write tests for deterministic output, exact two-board bounds/clearance, SDF collision/visual consistency, source mismatch, existing output and unsupported seed.
- [x] Run tests to observe the expected missing implementation failure.
- [x] Implement the smallest wrapper around existing world and texture helpers.
- [x] Run focused tests, Ruff and route/SDF checks; preserve the generated fixture in a fresh result directory.
- [x] Review and commit Task 1.

### Task 2: One single-aircraft capture and pinned VIO replay

**Files:** Fresh `results/openvins-prearm-board-dev-1701/` only; a report under `docs/`; a new sealed evidence ZIP/index under `evidence/`.

- [ ] Verify no competing PX4/Gazebo/training process, free resources, fixed runner/config/library hashes and source world/fixture manifest.
- [ ] Invoke `run_episode.py` once with `fly_raw`, fixed 4-second prearm, RGB and camera-info capture and fixture texture directory; preserve exit status, process log, ULog and all failures.
- [ ] Audit camera-visible boards, prearm RGB/IMU intervals, EKF2 validity and policy/safety status; if acquisition fails, stop and report the actual stage.
- [ ] Export the same IMU and frames into a new directory, replay once with pinned OpenVINS and logging-only feature patch, then run strict frame audit and trajectory analysis. A failed initialization is a valid result.
- [ ] Seal raw evidence and hashes; report the actual capability boundary, run targeted/full tests and Ruff, request independent read-only review, commit and create a stacked draft PR only if the evidence is remotely verifiable.
