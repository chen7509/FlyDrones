# PX4 EKF2 ULog Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align preserved development RGB frames with preceding PX4 EKF2 ULog estimates and retain every health/freshness failure without enabling live capture.

**Architecture:** A pure NumPy audit module accepts timestamped topic arrays and returns per-frame outcomes. A thin WSL CLI verifies the exact evidence archive, reads its ULog with `pyulog`, writes one immutable JSON report, and never changes control code.

**Tech Stack:** Python 3, NumPy, pyulog in WSL, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-03-ekf2-ulog-shadow-design.md`

## Global Constraints

- Input archive SHA-256 is `82f9377c1ad11f824064e1cbbc5feb834f77803af3ec83d00bfb0c8355072ddd`; ULog SHA-256 is `5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55`.
- Match only the latest PX4 sample at or before each frame; local, attitude and estimator status maximum age is 100 ms, sparse source flags maximum age is 2 s.
- Save raw NED and explicitly converted ENU position/velocity; do not produce camera pose, control commands, a training sequence, or a live-capture pass.
- Preserve all 629 source frame outcomes and refuse to overwrite a report.

## Review Focus

- A frame before the first PX4 sample must be retained as missing, not matched to the first future sample (Task 1 test).
- An estimator/attitude sample from the future must be rejected even if it is numerically closest (Task 1 test).
- Bad validity, dead reckoning, filter fault, and stale sparse source flags must remain distinct (Task 1 tests).
- A tampered ZIP, duplicated or unsafe member path, or changed required member must fail before `pyulog` analysis (Task 2 tests).
- A failed or interrupted run must leave no successful report, no overwritten source, and no persistent extracted ULog (Task 2 tests).

---

### Task 1: Pure per-frame EKF2 shadow audit

**Files:** Create `src/flydrones/benchmark/ekf2_shadow.py`; test in `tests/benchmark/test_ekf2_shadow.py`.

**Interfaces:** `audit_shadow_frames(frame_ns: list[int], topics: dict[str, dict[str, np.ndarray]]) -> dict` returns a schema-tagged JSON-compatible dict with one record per input frame, counts by reason/source, and `eligible_for_live_capture=false`.

- [ ] **Step 1: Write failing tests.** Cover no-future matching, 100 ms/2 s ages, all named health flags, finite NED/ENU mapping, monotonic timestamps, missing columns, and all-frame retention.
- [ ] **Step 2: Run red.** `PYTHONPATH=src python -m pytest tests/benchmark/test_ekf2_shadow.py -q` must fail on missing implementation.
- [ ] **Step 3: Implement.** Use `np.searchsorted(..., side="right")-1`, strict required fields, explicit reason codes and no truth input.
- [ ] **Step 4: Run green.** Same focused test command and `python -m ruff check` on both files.
- [ ] **Step 5: Commit.** `feat: audit px4 ekf2 shadow at rgb frames`.

### Task 2: Immutable fixed-archive CLI and real development replay

**Files:** Create `tools/benchmark/audit_ekf2_shadow.py`, `tests/benchmark/test_ekf2_shadow_cli.py`, `docs/EKF2_SHADOW_REPORT.md`, and small report `evidence/ekf2-shadow-dev-1701.json` only after a valid replay.

**Interfaces:** Public `audit_archive(archive_path: Path, index_path: Path) -> dict` pins historical hashes and reads the one archived ULog in a temporary directory, then calls Task 1. A private `_audit_verified_archive(..., expected_archive_sha256, expected_ulog_sha256, read_ulog)` allows tiny synthetic fixtures in tests; the CLI cannot override the pins. CLI `--archive`, `--index`, `--output` refuses an existing output.

- [ ] **Step 1: Write failing tests.** A minimal synthetic archive verifies digest/path/required-member rejection, no overwrite and temporary cleanup; one valid fake ULog reader reaches Task 1.
- [ ] **Step 2: Run red.** `PYTHONPATH=src python -m pytest tests/benchmark/test_ekf2_shadow_cli.py -q` fails on missing CLI behavior.
- [ ] **Step 3: Implement.** Pin the archive and ULog digests, verify required indexed members and manifest frames, read ULog with `pyulog` only inside a temporary directory, and atomically write JSON with no overwrite.
- [ ] **Step 4: Run green.** Focused tests plus `tests/benchmark/test_ulog_health.py`; Ruff and `git diff --check`.
- [ ] **Step 5: Run fixed WSL replay once.** Record all 629 frame outcomes and source hashes; keep all failures. If `pyulog`/archive is unavailable, preserve the exact blocker rather than fabricate a report.
- [ ] **Step 6: Verify and commit.** Full Python regression, independent report recheck, then `test: record immutable ekf2 shadow evidence`.

## Completion Report

State the number of aligned, invalid and missing frames; split GNSS and external-vision source counts; show first/last ULog coverage and time-age distribution. Label this offline PX4 EKF2/GNSS shadow evidence, not VIO fusion, PX4 closed-loop estimator input, safe training data, HITL or flight.
