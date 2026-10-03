# Frozen OpenVINS IMU feed and initialization audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the frozen IMU export and determine whether OpenVINS static initialization occurred while the PX4 EKF2 velocity estimate was nonzero.

**Architecture:** A read-only audit module checks pinned files, compares all ULog and CSV IMU samples, extracts the replay's initialization record, and summarizes valid EKF2 velocity in the preceding two seconds. It writes a new evidence directory once; a separate archive indexes the output and raw references.

**Tech Stack:** Python 3, NumPy, pyulog in WSL Ubuntu, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-03-openvins-imu-init-audit.md`

## Global Constraints

- Use only the frozen textured development episode 1701 and pinned OpenVINS upstream `69488123ed9362dd44b6f28e7f4680abbff1442b` (GPL-3.0).
- Do not alter the VIO input, config, runner, estimator, safety layer, flight controller, or formal evaluation scenes.
- PX4 EKF2 velocity is an offline reference, not independent ground truth; no visual fusion or real-flight claim.
- Never overwrite prior outputs. Include failed checks in the report and keep source hashes.

## Review Focus

- A single changed axis sample must fail full export equality, even when all counts match.
- A shifted timestamp must fail despite identical IMU values.
- A reset or invalid EKF2 velocity within the initialization interval must mark the comparison unscored.
- A duplicated or missing successful initialization record must fail instead of selecting one arbitrarily.
- A low-variance but nonzero-velocity window must be reported as an assumption conflict, not as a calibrated bias estimate.

---

### Task 1: Full frozen IMU mapping and initialization audit

**Files:** Create `tools/benchmark/audit_openvins_imu_init.py`; create `tests/benchmark/test_openvins_imu_init.py`.

**Interfaces:** `compare_imu_rows(ulog: dict, csv_rows: list[dict]) -> dict`; `extract_static_init(log_text: str, states: list[dict]) -> dict`; `score_ekf_init_velocity(data: dict, start_s: float, init_s: float) -> tuple[list[dict], dict]`; CLI writes `velocity_window.csv` and `summary.json` in an absent output directory.

- [ ] Write tests for exact normal export, changed value/timestamp rejection, duplicate init record, and velocity validity/reset/gap handling.
- [ ] Run those tests and observe expected missing-interface failures.
- [ ] Implement the minimal parser, checks and summary with hard-pinned SHA-256 input gates; import pyulog only inside the CLI.
- [ ] Run targeted tests and a single frozen-data audit; inspect every reported metric against raw source.
- [ ] Commit the audit implementation and raw result hashes.

### Task 2: Evidence, interpretation and review

**Files:** Create `docs/OPENVINS_IMU_INIT_REPORT.md`; create indexed `evidence/openvins-imu-init-dev-1701.zip` and adjacent SHA-256 JSON.

**Interfaces:** The archive contains the CLI source, tests, report, frozen runner/config, new summary and per-sample velocity CSV, and hash references to the earlier full ULog/image evidence.

- [ ] Build and independently verify a non-overwriting archive, including all member lengths and SHA-256 digests.
- [ ] Explain what the EKF2 comparison supports, what it cannot prove, and the next single experimental hypothesis.
- [ ] Run focused tests, Ruff, `git diff --check`, and the full suite using this worktree's `src` on `PYTHONPATH`; record failures accurately.
- [ ] Request read-only review, fix actionable findings, commit, and create a draft PR based on the clone-motion branch.
