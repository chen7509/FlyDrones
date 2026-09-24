# PX4 VIO Degradation Stress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run reproducible, source-verified PX4/Gazebo trials with delayed, drifting, dropped, and false external-vision odometry.

**Architecture:** Intercept only the Gazebo covariance-odometry topic in fault-trial launches. A deterministic Python relay perturbs the stream and republishes it to the existing PX4 topic. Fault activation follows the GNSS-fusion-off event. Trial artifacts and acceptance checks preserve failures.

**Tech Stack:** Python 3, pytest, Gazebo Sim 8 / gz-transport13, PX4 SITL, pyulog, PowerShell/WSL.

**Spec:** `docs/superpowers/specs/2026-09-24-vio-degradation-stress-design.md`

## Global Constraints

- Keep the existing policy checkpoint fixed; no PPO or MaleCNS training.
- Preserve direct Gazebo-to-PX4 behavior in existing launch scripts when the relay is disabled.
- Use separate run directories and deterministic seeds; retain every failure artifact.
- Run single-vehicle wiring and fault trials before five-vehicle trials.
- Distinguish perturbed Gazebo ground-truth odometry from camera-derived VIO.

## Review Focus

- A malformed model name must not route an odometry sample to another vehicle.
- A delayed sample must retain its original Gazebo timestamp and be logged with actual wall-clock delay.
- A missing GNSS-fault marker must keep the relay in pass-through mode.
- A queue backlog must have a bounded size and a visible drop reason.
- A missing PX4 ULog or estimator source dataset must fail acceptance.

---

### Task 1: Deterministic fault engine

**Files:** Create `src/flydrones/vio_faults.py`, `tests/test_vio_faults.py`.

- [ ] Write tests for identity, delay, scheduled loss, seeded random loss, drift, false pose, profile validation, and marker activation.
- [ ] Run targeted tests and confirm they fail for missing behavior.
- [ ] Implement a bounded queue and pure sample transformation; log reason codes and source timestamps.
- [ ] Run targeted tests, refactor, then commit.

### Task 2: Gazebo transport relay and isolated launch

**Files:** Create `tools/relay_gazebo_vio.py`, `tools/configure_gazebo_vio_model.py`; modify `tools/launch_px4_depth_swarm_wsl.sh`, `tools/stop_px4_swarm_wsl.sh`, and the agent fault marker path; add tests.

- [ ] Write failing tests for SDF raw-topic routing, frame-ID routing, activation marker, and cleanup.
- [ ] Implement the optional raw-topic model copy, relay process and lifecycle.
- [ ] Verify Gazebo Python transport imports and message round-trip on one model.
- [ ] Run tests and commit.

### Task 3: Trial runner and source-level acceptance

**Files:** Modify `tools/run_distributed_px4_swarm.py`, `src/flydrones/distributed_px4.py`, `src/flydrones/px4_ulog_evidence.py`; add tests and a fault profile catalog.

- [ ] Write failing tests that require relay evidence, PX4 ULog continuity, correct outcome classification, and preservation of failed runs.
- [ ] Implement one- and five-vehicle invocation, immutable run manifests and per-fault reports.
- [ ] Run focused tests and commit.

### Task 4: Execute and report

**Files:** Add `docs/VIO_DEGRADATION_STRESS.md` and result artifacts under distinct `results/` directories.

- [ ] Run baseline and four isolated fault profiles on one vehicle, retain every run.
- [ ] Freeze configurations; run five-vehicle profiles without tuning them against the held-out runs.
- [ ] Check ULog EKF fusion, safety outcomes, delay, clearance, minimum spacing and landing.
- [ ] Run relevant tests and report results, limitations, process cleanup and commit hash.
