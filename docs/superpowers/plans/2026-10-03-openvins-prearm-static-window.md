# OpenVINS Prearm Static Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a development-only prearm static RGB/IMU window and determine from saved PX4/Gazebo/OpenVINS evidence whether initialization actually uses a stationary interval.

**Architecture:** The existing single-aircraft backend continues Gazebo/PX4 startup, then optionally waits for a bounded simulated-time interval while still disarmed. The episode CLI gates the option before output creation. All downstream controller and scorer paths remain unchanged; postrun audit uses saved ULog and RGB only.

**Tech Stack:** Python 3.12, pytest, Ruff, WSL Ubuntu, PX4 SITL, Gazebo Sim 8, pyulog, isolated OpenVINS `69488123` research adapter.

**Spec:** `docs/superpowers/specs/2026-10-03-openvins-prearm-static-window-design.md`

## Global Constraints

- Explicit dev option only; default 0 s, no frozen benchmark manifest, requires raw RGB and camera-info recording.
- Simulated duration 4 s for the actual experiment; 0–8 s validation bound, finite wall-clock watchdog.
- No Gazebo position or EKF2 reference to OpenVINS inputs. PX4 still controls motors; original full fly controller remains unchanged.
- New result path, never overwrite existing evidence. Preserve every terminal failure and ULog.

## Review Focus

- Default formal runner remains unchanged and the option rejects frozen/uncaptured runs before creating output.
- Startup interval uses increasing simulation time, cannot pass through wall sleep alone, and times out safely.
- A PX4/Gazebo exception still closes resources and reports partial prearm progress.
- RGB/IMU window endpoints, reset counters and initialization time are checked rather than inferred from a CLI flag.
- OpenVINS visual updates and trajectory error cannot be replaced by merely successful initialization.

## Task 1: Development option and bounded prearm interval

**Files:** `src/flydrones/benchmark/gateway.py`, `tools/benchmark/run_episode.py`, `tests/benchmark/test_stationary_prelude.py`.

**Interfaces:** `NativeGazeboPx4Backend(..., development_prearm_stationary_s: float = 0.)` exposes `prearm_stationary_evidence: dict`; `prearm_duration(seconds, *, frozen, record_rgb, record_camera_info) -> float` validates CLI admission.

- [x] Write tests for default zero, invalid/forbidden options, simulated-clock completion and timeout/partial evidence.
- [x] Run tests and confirm the new cases fail for the intended missing behavior.
- [x] Implement the opt-in backend wait between `connect()`/settling and `takeoff()` with a bounded wall guard; record timestamps and progress without changing standard startup.
- [x] Route the CLI option into the backend and persist `prearm_stationary_evidence` in all terminal result paths.
- [x] Run focused regression/Ruff, then commit. (37 focused; 501 full; Ruff pass)
- [x] Review fix: reject every preexisting episode directory, move formal-batch logs to a separate directory, and copy development textures with hashes from an explicit source. Focused tests, 504-test full regression, and Ruff pass.

## Task 2: One fixed-world development run and offline VIO audit

**Files:** an independent `results/openvins-prearm-static-dev-1701/` output, `docs/OPENVINS_PREARM_STATIC_REPORT.md`, sealed evidence ZIP and index.

**Interfaces:** use the existing `run_episode.py` RGB/camera capture and existing OpenVINS offline preparation/replay/audit tools; no new PX4 fusion input.

- [ ] Verify pinned archive fixture, PX4/OpenVINS versions, available disk and absence of competing simulation processes.
- [ ] Run one development episode with `--development-prearm-stationary-s 4`, preserving output and any failure. Do not rerun into the same path.
- [ ] Audit ULog/RGB prearm coverage and PX4 velocity validity/reset flags, then replay saved inputs through fixed OpenVINS configuration once.
- [ ] Compare initialization time, true visual-update count, trajectory error and task terminal status; report all gaps and limitations.
- [ ] Seal logs and outputs with SHA-256 index, verify archive readback; run focused tests/review and commit a draft stacked PR.
